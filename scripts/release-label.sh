#!/usr/bin/env bash
# Prints the label CodePipeline shows for a release, e.g. "Version f8971db: Assign the delivery reference".
#   ./scripts/release-label.sh <git-sha> [<text>]   # text defaults to the commit's title
# The deploy bundle is uploaded with it as the S3 metadata codepipeline-artifact-revision-summary,
# which the pipeline shows as the DeployBundle source revision (run history and Rollback dialog).
# For a merge commit the title is the pull request's title (first line of the message body).
set -euo pipefail
sha="${1:?usage: release-label.sh <git-sha> [<text>]}"
text="${2:-}"
if [[ -z "$text" ]]; then
  text="$(git log -1 --format=%s "$sha" 2>/dev/null || true)"
  if [[ "$text" == "Merge pull request"* ]]; then
    text="$(git log -1 --format=%b "$sha" | sed '/^[[:space:]]*$/d' | head -1)"
  fi
fi
# S3 metadata must be printable ASCII; CodePipeline shows up to 2048 characters, keep it short.
label="Version ${sha:0:7}${text:+: $text}"
LC_ALL=C tr -cd '[:print:]' <<<"$label" | cut -c1-200
