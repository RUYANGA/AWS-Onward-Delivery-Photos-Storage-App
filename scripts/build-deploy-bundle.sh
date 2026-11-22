#!/usr/bin/env bash
# Builds deploy-bundle.zip (taskdef.json + appspec.yaml) for CodeDeploy.
# The task definition is owned by the infra repo: this reads the live revision and swaps the
# image for <IMAGE1_NAME>, which CodePipeline replaces with the released image digest.
# It also adds the container health check (ECS shows Healthy/Unhealthy and replaces a task whose
# app stops answering) unless the revision already has one: the check runs a command inside this
# image, so it belongs with the image, and CloudFormation can't change the task definition of a
# CodeDeploy-controlled service.
# Exit 3 = no task definition yet (first deployment).
set -euo pipefail
: "${TASK_FAMILY:?}" "${CONTAINER_NAME:?}"
OUT_DIR=${1:-build}
mkdir -p "$OUT_DIR"

if ! aws ecs describe-task-definition --task-definition "$TASK_FAMILY" --query taskDefinition --output json > "$OUT_DIR/current.json" 2>/dev/null; then
  echo "::warning::Task definition $TASK_FAMILY not found (first-time bootstrap). Skipping deployment bundle."
  exit 3
fi

# GET /healthz on the container itself (answered before host checks and the database); the image
# has no curl, so Python does the request.
HEALTH_CHECK='{
  "command": ["CMD", "python", "-c",
    "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8000/healthz\", timeout=4)"],
  "interval": 30, "timeout": 5, "retries": 3, "startPeriod": 60
}'

jq --arg name "$CONTAINER_NAME" --argjson health "$HEALTH_CHECK" '
  .containerDefinitions |= map(if .name == $name
    then .image = "<IMAGE1_NAME>" | .healthCheck = (.healthCheck // $health)
    else . end)
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
        .registeredAt, .registeredBy, .deregisteredAt)
' "$OUT_DIR/current.json" > "$OUT_DIR/taskdef.json"

grep -q '<IMAGE1_NAME>' "$OUT_DIR/taskdef.json" || { echo "Container $CONTAINER_NAME not in task definition"; exit 1; }
cp deploy/appspec.yaml "$OUT_DIR/appspec.yaml"
(cd "$OUT_DIR" && rm -f deploy-bundle.zip && zip -q deploy-bundle.zip taskdef.json appspec.yaml)
echo "Built $OUT_DIR/deploy-bundle.zip"
