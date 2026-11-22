#!/usr/bin/env bash
# Read-only SQL against the private RDS database, from a laptop with AWS access.
#   ./scripts/db-query.sh "SELECT delivery_reference, title, deleted_at FROM photos"
# The database is reachable only from the app tasks, so this starts a one-off copy of the app task
# (same subnets, security group and Secrets Manager credentials), runs the query inside a
# READ ONLY transaction, prints the rows from CloudWatch Logs and stops (about a minute).
set -euo pipefail
SQL="${1:?usage: ./scripts/db-query.sh \"SELECT ...\"}"
REGION="${AWS_REGION:-eu-west-1}"
CLUSTER="${CLUSTER_NAME:-onward-dev-cluster}"
SERVICE="${SERVICE_NAME:-onward-dev-delivery-photos}"
LOG_GROUP="${APP_LOG_GROUP:-/ecs/onward-dev/delivery-photos-app}"

service() {
  aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" --services "$SERVICE" \
    --query "services[0].$1" --output "$2"
}
task_definition="$(service taskDefinition text)"
network="$(service networkConfiguration json)"

python_code='
import os
from django.db import connection, transaction
with transaction.atomic(), connection.cursor() as cursor:
    cursor.execute("SET TRANSACTION READ ONLY")
    cursor.execute(os.environ["SQL"])
    columns = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
print("=== RESULT ===")
print(" | ".join(columns))
for row in rows:
    print(" | ".join("" if v is None else str(v) for v in row))
print(f"({len(rows)} rows)")
'
overrides="$(jq -n --arg sql "$SQL" --arg py "$python_code" \
  '{containerOverrides: [{name: "app", command: ["python", "manage.py", "shell", "-c", $py],
    environment: [{name: "SQL", value: $sql}]}]}')"

task="$(aws ecs run-task --region "$REGION" --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$task_definition" --network-configuration "$network" --overrides "$overrides" \
  --started-by db-query --query 'tasks[0].taskArn' --output text)"
task_id="${task##*/}"
echo "Running the query in task $task_id (about a minute) ..." >&2
aws ecs wait tasks-stopped --region "$REGION" --cluster "$CLUSTER" --tasks "$task"

aws logs get-log-events --region "$REGION" --log-group-name "$LOG_GROUP" \
  --log-stream-name "app/app/$task_id" --start-from-head --query 'events[].message' --output text \
  | tr '\t' '\n' | sed -n '/^=== RESULT ===$/,$p' | tail -n +2
exit_code="$(aws ecs describe-tasks --region "$REGION" --cluster "$CLUSTER" --tasks "$task" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
[[ "$exit_code" == 0 ]] || {
  echo "The query failed (exit $exit_code). Full log: $LOG_GROUP, stream app/app/$task_id" >&2
  exit 1
}
