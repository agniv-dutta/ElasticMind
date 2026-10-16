"""Drive an ElasticMind AWS deployment end-to-end.

Generates load against the ALB, watches the ECS target service scale via the
ElasticMind controller, reads custom CloudWatch metrics, and prints a report.
**Remember to run destroy afterwards to control cost.**

Usage:
    python -m experiments.aws_run --alb-dns elasticmind-alb-123.us-east-1.elb.amazonaws.com \
        --duration 120 --speed-factor 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from statistics import mean

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]

from loadgen.runner import run_load

NAMESPACE = "ElasticMind"


def _ecs_desired(ecs, cluster: str, service: str) -> int:
    resp = ecs.describe_services(cluster=cluster, services=[service])
    return int(resp["services"][0]["desiredCount"])


def _ecs_running(ecs, cluster: str, service: str) -> int:
    resp = ecs.describe_services(cluster=cluster, services=[service])
    return int(resp["services"][0]["runningCount"])


def _cw_series(cw, metric: str, minutes: int, region: str, period: int = 60) -> list[float]:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    resp = cw.get_metric_statistics(
        Namespace=NAMESPACE,
        MetricName=metric,
        Dimensions=[{"Name": "Service", "Value": "elasticmind-target"}],
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=["Average"],
    )
    pts = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
    return [float(p["Average"]) for p in pts]


async def _run(args) -> dict:
    if boto3 is None:
        raise SystemExit("boto3 is required for experiments.aws_run")
    ecs = boto3.client("ecs", region_name=args.region)
    cw = boto3.client("cloudwatch", region_name=args.region)

    target_url = f"http://{args.alb_dns}"
    print(f"[aws_run] target = {target_url}")
    print(f"[aws_run] cluster={args.cluster} service={args.service}")

    before = _ecs_desired(ecs, args.cluster, args.service)
    print(f"[aws_run] desired before = {before}")

    # run load (blocking) while polling ECS in a thread
    desired_samples: list[tuple[float, int]] = []

    async def poll() -> None:
        while not stop[0]:
            try:
                desired_samples.append((time.time(), _ecs_desired(ecs, args.cluster, args.service)))
            except Exception:
                pass
            await asyncio.sleep(args.poll_interval)

    stop = [False]
    poll_task = asyncio.create_task(poll())
    summary = await run_load(
        target_url=target_url,
        speed_factor=args.speed_factor,
        max_requests=args.max_requests,
        concurrency=args.concurrency,
        profile=args.profile,
    )
    # keep watching the desired count until the duration elapses
    await asyncio.sleep(max(0.0, args.duration - summary["duration_s"]))
    stop[0] = True
    await poll_task

    after = _ecs_desired(ecs, args.cluster, args.service)
    cw_metrics = {
        m: _cw_series(cw, m, args.observations_min, args.region)
        for m in ("PredictedLoad", "ActualLoad", "DesiredCapacity", "ForecastMAPE", "EstimatedCost")
    }

    desired_values = [d for _, d in desired_samples]
    report = {
        "alb_dns": args.alb_dns,
        "requests": {
            "total": summary["requests_total"],
            "success_rate": summary["success_rate"],
            "latency_p50_ms": summary["latency_p50_ms"],
            "latency_p95_ms": summary["latency_p95_ms"],
        },
        "scaling": {
            "desired_before": before,
            "desired_after": after,
            "desired_min": min(desired_values) if desired_values else before,
            "desired_max": max(desired_values) if desired_values else before,
            "samples": len(desired_values),
        },
        "cloudwatch": {
            k: (round(mean(v), 3) if v else None) for k, v in cw_metrics.items()
        },
        "simulated_cost_note": "EstimatedCost is an ElasticMind model estimate, not AWS billing.",
        "next_step": "Run 'terraform destroy' (infra/terraform/destroy.sh) to stop charges.",
    }
    return report


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Drive an ElasticMind AWS deployment")
    p.add_argument("--alb-dns", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--cluster", default="elasticmind")
    p.add_argument("--service", default="elasticmind-target")
    p.add_argument("--profile", default="diurnal")
    p.add_argument("--speed-factor", type=float, default=20.0)
    p.add_argument("--max-requests", type=int, default=600)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument("--duration", type=float, default=120.0, help="total wall-clock seconds to observe")
    p.add_argument("--poll-interval", type=float, default=5.0)
    p.add_argument("--observations-min", type=int, default=10)
    args = p.parse_args(argv)

    report = asyncio.run(_run(args))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
