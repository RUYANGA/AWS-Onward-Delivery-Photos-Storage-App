#!/usr/bin/env bash
# The releases kept in ECR (the last 10), and rollback to any of them through the release pipeline.
#   ./scripts/rollback.sh                          # list releases, newest first, and which one is live
#   ./scripts/rollback.sh <git-sha> ["<reason>"]   # redeploy that release, blue/green with alarms
# The pipeline deploys the exact image digest, so "latest" is not moved and the next merge to main
# releases normally. Used by .github/workflows/rollback.yml; works the same from a laptop.
set -euo pipefail
: "${AWS_REGION:?set AWS_REGION}"
REPOSITORY="${ECR_REPOSITORY:-onward-dev/delivery-photos-app}"
PIPELINE="${PIPELINE_NAME:-onward-dev-photos-release}"
VERSION="${1:-}"
REASON="${2:-rollback}"
summary() { [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] && echo "$*" >> "$GITHUB_STEP_SUMMARY"; return 0; }

# digest <TAB> tags <TAB> pushed, newest first
releases="$(aws ecr describe-images --repository-name "$REPOSITORY" --filter tagStatus=TAGGED \
  --query 'reverse(sort_by(imageDetails,&imagePushedAt))[].[imageDigest, join(`,`, imageTags), imagePushedAt]' \
  --output text)"
# The image the last successful pipeline run deployed.
live="$(aws codepipeline list-pipeline-executions --pipeline-name "$PIPELINE" --max-items 20 \
  --query "pipelineExecutionSummaries[?status=='Succeeded'] | [0].sourceRevisions[?actionName=='Image'] | [0].revisionId" \
  --output text 2>/dev/null || true)"

version_of() { tr ',' '\n' <<<"$1" | grep -E '^[0-9a-f]{40}$' | head -1 || true; }

if [[ -z "$VERSION" ]]; then
  printf '%-9s %-20s %-14s %s\n' VERSION PUSHED DIGEST STATUS
  summary "| Version | Pushed (UTC) | Digest | Status |"
  summary "|---|---|---|---|"
  while IFS=$'\t' read -r digest tags pushed; do
    sha="$(version_of "$tags")"; name="${sha:0:7}"; [[ -z "$sha" ]] && name="${tags%%,*}"
    status=""
    [[ "$digest" == "$live" ]] && status="live"
    [[ ",$tags," == *",latest,"* ]] && status="${status:+$status, }latest"
    printf '%-9s %-20s %-14s %s\n' "$name" "${pushed:0:19}" "${digest:7:12}" "$status"
    summary "| \`$name\` | ${pushed:0:19} | \`${digest:7:12}\` | $status |"
  done <<<"$releases"
  echo; echo "Roll back with: ./scripts/rollback.sh <version> \"<reason>\""
  exit 0
fi

[[ "$VERSION" =~ ^[0-9a-f]{7,40}$ ]] || { echo "Version must be a git SHA (7 to 40 hex characters): $VERSION"; exit 1; }
matches="$(awk -F'\t' -v v="$VERSION" '{ n = split($2, t, ","); for (i = 1; i <= n; i++) if (index(t[i], v) == 1 && t[i] ~ /^[0-9a-f]{40}$/) print $1 "\t" t[i] }' <<<"$releases" | sort -u)"
count="$(grep -c . <<<"$matches" || true)"
[[ "$count" == 0 ]] && { echo "No release $VERSION in $REPOSITORY. Only the last 10 are kept; run without arguments to list them."; exit 1; }
[[ "$count" -gt 1 ]] && { echo "$VERSION matches more than one release; give more characters."; exit 1; }
IFS=$'\t' read -r digest sha <<<"$matches"
if [[ "$digest" == "$live" ]]; then
  echo "${sha:0:7} is already live. Nothing to do."; summary "${sha:0:7} is already live. Nothing to do."; exit 0
fi

variables="$(jq -cn --arg v "$sha" --arg r "$REASON" '[{name: "Version", value: $v}, {name: "Reason", value: $r}]')"

# A deploy bundle labelled with this version, so the run is named in the pipeline's history and
# Rollback dialog. The run is pinned to that exact S3 object version.
account="$(aws sts get-caller-identity --query Account --output text)"
bucket="${DEPLOY_BUCKET:-onward-dev-deploy-bundles-${account}-${AWS_REGION}}"
build_dir="$(mktemp -d)"; trap 'rm -rf "$build_dir"' EXIT
TASK_FAMILY="${TASK_FAMILY:-onward-dev-delivery-photos}" CONTAINER_NAME="${CONTAINER_NAME:-app}" \
  "$(dirname "$0")/build-deploy-bundle.sh" "$build_dir" >/dev/null
label="$("$(dirname "$0")/release-label.sh" "$sha" "rollback: $REASON")"
bundle_version="$(aws s3api put-object --bucket "$bucket" --key deploy/deploy-bundle.zip \
  --body "$build_dir/deploy-bundle.zip" --metadata "codepipeline-artifact-revision-summary=$label" \
  --query VersionId --output text)"

execution="$(aws codepipeline start-pipeline-execution --name "$PIPELINE" \
  --source-revisions "actionName=Image,revisionType=IMAGE_DIGEST,revisionValue=$digest" \
                     "actionName=DeployBundle,revisionType=S3_OBJECT_VERSION_ID,revisionValue=$bundle_version" \
  --variables "$variables" --query pipelineExecutionId --output text)"
url="https://${AWS_REGION}.console.aws.amazon.com/codesuite/codepipeline/pipelines/${PIPELINE}/executions/${execution}/timeline?region=${AWS_REGION}"
echo "Rolling back to ${sha:0:7} (${digest:7:12}): $url"
summary "### Rolling back to \`${sha:0:7}\`"
summary "Reason: $REASON. Pipeline run: [$execution]($url)"
