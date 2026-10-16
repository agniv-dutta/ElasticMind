"""moto-based tests for the AWS ECS actuator, CloudWatch metrics and S3 model store."""

from __future__ import annotations

from pathlib import Path

import boto3
import pytest

moto = pytest.importorskip("moto")
from backend.app.autoscaler.aws_actuator import AwsEcsActuator  # noqa: E402
from backend.app.aws.metrics import CloudWatchMetricsPublisher  # noqa: E402
from backend.app.aws.model_store import load_model_from_s3  # noqa: E402
from moto import mock_aws  # noqa: E402

REGION = "us-east-1"
CLUSTER = "elasticmind"
SERVICE = "elasticmind-target"


@pytest.fixture
def ecs_with_service():
    with mock_aws():
        ec2 = boto3.client("ec2", region_name=REGION)
        vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
        sg = ec2.create_security_group(
            GroupName="ecs-tasks", Description="tasks", VpcId=vpc
        )["GroupId"]
        ecs = boto3.client("ecs", region_name=REGION)
        ecs.create_cluster(clusterName=CLUSTER)
        ecs.register_task_definition(
            family="target",
            networkMode="awsvpc",
            requiresCompatibilities=["FARGATE"],
            cpu="256",
            memory="512",
            containerDefinitions=[{"name": "target-app", "image": "nginx", "essential": True}],
        )
        ecs.create_service(
            cluster=CLUSTER,
            serviceName=SERVICE,
            taskDefinition="target",
            desiredCount=2,
            launchType="FARGATE",
            networkConfiguration={"awsvpcConfiguration": {"subnets": [subnet], "securityGroups": [sg]}},
        )
        yield ecs


def test_actuator_reads_initial_desired(ecs_with_service) -> None:
    act = AwsEcsActuator(cluster=CLUSTER, service=SERVICE, region=REGION, min_c=1, max_c=10)
    assert act.current() == 2
    assert act.desired() == 2


def test_actuator_scales_up_and_down(ecs_with_service) -> None:
    act = AwsEcsActuator(
        cluster=CLUSTER, service=SERVICE, region=REGION,
        min_c=1, max_c=10, scale_up_cooldown_s=0, scale_down_cooldown_s=0,
    )
    a1 = act.set_desired(5, now=1000.0)
    assert a1.desired == 5
    assert a1.current == 2
    resp = ecs_with_service.describe_services(cluster=CLUSTER, services=[SERVICE])
    assert resp["services"][0]["desiredCount"] == 5

    a2 = act.set_desired(1, now=2000.0)
    assert a2.desired == 1
    resp = ecs_with_service.describe_services(cluster=CLUSTER, services=[SERVICE])
    assert resp["services"][0]["desiredCount"] == 1


def test_actuator_clamps_bounds(ecs_with_service) -> None:
    act = AwsEcsActuator(cluster=CLUSTER, service=SERVICE, region=REGION, min_c=1, max_c=4)
    a = act.set_desired(99, now=1000.0)
    assert a.desired == 4
    a = act.set_desired(-5, now=2000.0)
    assert a.desired == 1


def test_actuator_cooldown_blocks_rapid_changes(ecs_with_service) -> None:
    act = AwsEcsActuator(
        cluster=CLUSTER, service=SERVICE, region=REGION,
        min_c=1, max_c=10, scale_up_cooldown_s=120, scale_down_cooldown_s=120,
    )
    act.set_desired(4, now=1000.0)
    blocked = act.set_desired(8, now=1010.0)  # 10 s later, inside cooldown
    assert blocked.desired == 4
    assert "cooldown" in blocked.reason
    allowed = act.set_desired(8, now=1200.0)  # after cooldown
    assert allowed.desired == 8


def test_cloudwatch_publish_and_read() -> None:
    with mock_aws():
        cw = boto3.client("cloudwatch", region_name=REGION)
        pub = CloudWatchMetricsPublisher(region=REGION, client=cw)
        pub.put_metrics(
            predicted_load=800, actual_load=760, desired_capacity=5,
            running_capacity=4, forecast_mape=12.5, sla_violations=2,
            estimated_cost=0.42,
        )
        metrics = cw.list_metrics(Namespace="ElasticMind")
        names = {m["MetricName"] for m in metrics["Metrics"]}
        assert {"PredictedLoad", "ActualLoad", "DesiredCapacity", "RunningCapacity",
                "ForecastMAPE", "SLAViolations", "EstimatedCost"} <= names


def test_s3_model_store_roundtrip(tmp_path: Path) -> None:
    from ml.data.generate import generate_workload
    from ml.models.lightgbm_model import LightGBMMultiHorizon

    hist = generate_workload(days=2, seed=1)
    model = LightGBMMultiHorizon(horizons=(5, 15), n_estimators=30).fit(hist)
    artifact = tmp_path / "lightgbm.joblib"
    model.save(artifact)

    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="elasticmind-artifacts")
        s3.upload_file(str(artifact), "elasticmind-artifacts", "models/lightgbm.joblib")
        s3.upload_file(str(artifact.with_suffix(".meta.json")), "elasticmind-artifacts",
                       "models/lightgbm.meta.json")

        fetched = load_model_from_s3(
            "s3://elasticmind-artifacts/models/lightgbm.joblib",
            local_dir=tmp_path / "dl",
            region=REGION,
            s3_client=s3,
        )
        fc = fetched.predict(hist)
        assert len(fc.frame) == 2


def test_s3_model_store_fallback(tmp_path: Path) -> None:
    # offline: empty uri, local fallback used
    from ml.data.generate import generate_workload
    from ml.models.reactive import ReactiveBaseline
    from ml.models.registry import save_predictor

    hist = generate_workload(days=1, seed=1)
    m = ReactiveBaseline(horizons=(5,)).fit(hist)
    p = tmp_path / "baseline.joblib"
    save_predictor(m, p)

    with mock_aws():
        loaded = load_model_from_s3(
            "", local_dir=tmp_path / "dl", region=REGION, local_fallback=p
        )
    assert loaded.name == "reactive_baseline"
