"""Publish ElasticMind custom metrics to CloudWatch each control-loop iteration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

NAMESPACE = "ElasticMind"


class CloudWatchMetricsPublisher:
    """Publishes the metric set required by the CloudWatch dashboard.

    Metrics: PredictedLoad, ActualLoad, DesiredCapacity, RunningCapacity,
    ForecastMAPE, SLAViolations, EstimatedCost.
    """

    def __init__(self, region: str | None = None, namespace: str = NAMESPACE,
                 client: Any | None = None) -> None:
        if client is None and boto3 is None:  # pragma: no cover
            raise ImportError("boto3 required for CloudWatchMetricsPublisher")
        self._client = client or boto3.client("cloudwatch", region_name=region)
        self.namespace = namespace

    def put_metrics(
        self,
        predicted_load: float,
        actual_load: float,
        desired_capacity: int,
        running_capacity: int,
        forecast_mape: float,
        sla_violations: int,
        estimated_cost: float,
        dimensions: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> dict:
        ts = timestamp or datetime.now(UTC)
        dims = [{"Name": k, "Value": v} for k, v in (dimensions or {"Service": "elasticmind-target"}).items()]

        def metric(name: str, value: float, unit: str = "None") -> dict:
            return {
                "MetricName": name,
                "Value": float(value),
                "Unit": unit,
                "Timestamp": ts,
                "Dimensions": dims,
            }

        data = [
            metric("PredictedLoad", predicted_load, "Count"),
            metric("ActualLoad", actual_load, "Count"),
            metric("DesiredCapacity", desired_capacity, "Count"),
            metric("RunningCapacity", running_capacity, "Count"),
            metric("ForecastMAPE", forecast_mape, "Percent"),
            metric("SLAViolations", sla_violations, "Count"),
            metric("EstimatedCost", estimated_cost, "None"),
        ]
        return self._client.put_metric_data(Namespace=self.namespace, MetricData=data)

    def read_alb_and_ecs(
        self,
        load_balancer: str | None = None,
        target_group: str | None = None,
        cluster: str | None = None,
        service: str | None = None,
        region: str | None = None,
        period_s: int = 60,
    ) -> dict:
        """Read ALB RequestCount/TargetResponseTime and ECS CPUUtilization.

        Returns a dict of the latest values (missing keys omitted).
        """
        cw = self._client
        out: dict[str, float] = {}
        now = datetime.now(UTC)
        start = now.timestamp() - 2 * period_s
        start_dt = datetime.fromtimestamp(start, tz=UTC)

        def latest(namespace: str, metric_name: str, dims: list[dict[str, str]], stat: str = "Sum") -> float | None:
            try:
                resp = cw.get_metric_statistics(
                    Namespace=namespace,
                    MetricName=metric_name,
                    Dimensions=dims,
                    StartTime=start_dt,
                    EndTime=now,
                    Period=period_s,
                    Statistics=[stat],
                )
                points = resp.get("Datapoints", [])
                if not points:
                    return None
                points.sort(key=lambda p: p["Timestamp"])
                return float(points[-1][stat])
            except Exception:
                return None

        if load_balancer and target_group:
            dims = [
                {"Name": "LoadBalancer", "Value": load_balancer},
                {"Name": "TargetGroup", "Value": target_group},
            ]
            rc = latest("AWS/ApplicationELB", "RequestCount", dims, "Sum")
            rt = latest("AWS/ApplicationELB", "TargetResponseTime", dims, "Average")
            if rc is not None:
                out["alb_request_count"] = rc
            if rt is not None:
                out["alb_target_response_time"] = rt
        if cluster and service:
            dims = [
                {"Name": "ClusterName", "Value": cluster},
                {"Name": "ServiceName", "Value": service},
            ]
            cpu = latest("AWS/ECS", "CPUUtilization", dims, "Average")
            if cpu is not None:
                out["ecs_cpu_utilization"] = cpu
        return out
