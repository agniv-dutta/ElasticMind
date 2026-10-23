# ElasticMind — AWS infrastructure (Terraform)

Fargate deployment of the same controller used locally. **CloudWatch is the only
monitoring tool.** All dollar figures shown by ElasticMind remain estimates.

## What this creates

- VPC with **2 public subnets** in 2 AZs (no NAT gateway → no NAT cost)
- ECR repositories: `elasticmind-backend`, `elasticmind-target-app`
- ECS cluster + two Fargate services: `target` (behind an ALB) and `backend`
- Application Load Balancer + target group (health check `/health`)
- S3 bucket for models / traces / results (versioned + encrypted)
- Least-privilege IAM for the controller
  (`ecs:UpdateService`, `ecs:DescribeServices`, `cloudwatch:PutMetricData`,
  `cloudwatch:GetMetricData`, `s3:GetObject/PutObject`)
- CloudWatch log groups (`/ecs/elasticmind/{target,backend}`)
- AWS **Budget alarm** at a low monthly threshold
- Tags: `Project=elasticmind` on everything

## AWS telemetry path

In AWS mode the backend reads the latest complete `AWS/ApplicationELB`/
`RequestCount` datapoint for the target ALB and target group every control tick.
The 60-second `Sum` is converted to requests per minute as
`sum * 60 / period_seconds`. The CloudWatch datapoint timestamp is retained;
missing, duplicate, or older-than-180-second datapoints cause the controller to
use its explicit reactive fallback for that tick. Request rate is labelled
`measured`; cost, energy, and queueing latency remain estimated/simulated.

Terraform injects these settings into the backend task:
`ELASTICMIND_AWS_ALB_LOAD_BALANCER`, `ELASTICMIND_AWS_ALB_TARGET_GROUP`,
`ELASTICMIND_AWS_TELEMETRY_PERIOD_S`, and
`ELASTICMIND_AWS_TELEMETRY_STALE_AFTER_S`. The controller then sends the ML or
fallback decision to the ECS target service through `AwsEcsActuator`.

## Prerequisites

- Terraform >= 1.5, AWS CLI v2 configured (`aws configure`)
- Docker for building/pushing images

## Apply

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit region/email/budget
terraform init
terraform plan
terraform apply
```

Then build & push images (from the repo root):

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$REGION.amazonaws.com

docker build -f infra/docker/target_app.Dockerfile -t $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/elasticmind-target-app:latest .
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/elasticmind-target-app:latest

docker build -f infra/docker/backend.Dockerfile -t $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/elasticmind-backend:latest .
docker push $ACCOUNT.dkr.ecr.$REGION.amazonaws.com/elasticmind-backend:latest

aws ecs update-service --cluster elasticmind --service elasticmind-target --force-new-deployment
aws ecs update-service --cluster elasticmind --service elasticmind-backend --force-new-deployment
```

Verify the actual control path while generating ALB traffic:

```bash
curl http://$(terraform output -raw alb_dns_name)/health
python -m experiments.aws_run --alb-dns "$(terraform output -raw alb_dns_name)" --duration 180
aws ecs describe-services --cluster "$(terraform output -raw ecs_cluster_name)" \
  --services "$(terraform output -raw target_service_name)" \
  --query 'services[0].{desired:desiredCount,running:runningCount,pending:pendingCount}'
```

The local dashboard/backend status endpoint reports `telemetry_source`,
`telemetry_status`, `forecast_source`, `actuator_status`, and a fallback reason.

Upload the trained model so the controller can load it at startup:

```bash
aws s3 cp ml/models/artifacts/lightgbm.joblib \
  s3://$(terraform output -raw artifacts_bucket)/models/lightgbm.joblib
```

## Destroy (do this to control cost)

```bash
./destroy.sh
# or: terraform destroy
```

## Cost notes

- Tasks are **0.25 vCPU / 0.5 GiB**. Record the demo in one short window.
- Public-only subnets avoid the NAT gateway (~$0.045/hr + data).
- The budget alarm emails you if spend crosses the threshold.
