#!/usr/bin/env bash
# Safe teardown: always destroy ElasticMind AWS resources after a demo to
# control cost. Usage: ./destroy.sh [--auto-approve]
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

echo "==> ElasticMind terraform destroy"
echo "This removes the VPC, ECS cluster/services, ALB, ECR repos, S3 bucket,"
echo "IAM roles, log groups and budget. Data in the artifacts bucket is deleted."
read -r -p "Type 'destroy' to confirm: " confirm
if [ "$confirm" != "destroy" ]; then
  echo "aborted"
  exit 1
fi

terraform destroy "$@"
