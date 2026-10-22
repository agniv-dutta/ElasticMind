"""Async load generator using httpx/asyncio.

Replays a workload trace or a synthetic profile as real HTTP traffic at a
configurable speed-up factor. Logs request count, success rate and p50/p95
latency back to the backend (if configured).
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
import os
from pathlib import Path

import httpx
import pandas as pd
from ml.data.generate import generate_workload


def _load_trace(path: str | None, profile: str, days: int) -> pd.DataFrame:
    if path and Path(path).exists():
        p = Path(path)
        if p.suffix == ".csv":
            df = pd.read_csv(p)
        else:
            df = pd.read_parquet(p)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    return generate_workload(profile=profile, days=days, seed=42)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile / 100.0 * len(ordered)) - 1)
    return ordered[rank]


async def run_load(
    target_url: str,
    backend_url: str | None = None,
    trace_path: str | None = None,
    profile: str = "diurnal",
    days: int = 1,
    speed_factor: float | None = None,
    max_requests: int | None = None,
    concurrency: int = 8,
) -> dict:
    """Drive ``target_url /work`` at the scaled speed of ``trace_path``.

    Returns a summary dict with request count, success rate, p50, p95 latency.
    """
    speed_factor = float(os.getenv("LOADGEN_SPEED_FACTOR", "1")) if speed_factor is None else speed_factor
    if speed_factor <= 0:
        raise ValueError("speed_factor must be positive")
    if profile in {"steady", "ramp", "spike"}:
        # These live profiles are intentionally fixed-rate so their labels
        # describe the actual arrival rate independent of generated traces.
        rate = 60.0 if profile in {"steady", "ramp"} else 480.0
        requests_per_min = [rate] * (max(1, days) * 1440)
    else:
        trace = _load_trace(trace_path, profile, days)
        requests_per_min = trace["requests"].astype(float).tolist()

    latencies: list[float] = []
    successes = 0
    failures = 0
    total = 0

    start = time.time()
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def one(request_id: int) -> None:
            nonlocal successes, failures, total
            async with sem:
                try:
                    t0 = time.perf_counter()
                    r = await client.get(f"{target_url.rstrip('/')}/work", headers={"x-request-id": str(request_id)})
                    dt = (time.perf_counter() - t0) * 1000.0
                    latencies.append(dt)
                    if r.status_code == 200:
                        successes += 1
                    else:
                        failures += 1
                    total += 1
                except Exception:
                    failures += 1
                    total += 1

        tasks: list[asyncio.Task] = []
        spawned = 0
        replay_start = time.perf_counter()
        for i in range(len(requests_per_min)):
            if max_requests is not None and spawned >= max_requests:
                break
            tick_seconds = 60.0 / speed_factor
            tick_start = i * tick_seconds
            # Preserve each trace minute's arrival rate while compressing time.
            n = max(0, round(requests_per_min[i]))
            if max_requests is not None:
                n = min(n, max_requests - spawned)
            for j in range(n):
                due = tick_start + (j / max(n, 1)) * tick_seconds
                await asyncio.sleep(max(0.0, replay_start + due - time.perf_counter()))
                spawned += 1
                tasks.append(asyncio.create_task(one(spawned)))
        # run all
        await asyncio.gather(*tasks)

    dur = max(time.time() - start, 1e-6)
    summary = {
        "target": target_url,
        "requests_total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / max(total, 1), 4),
        "latency_p50_ms": round(_percentile(latencies, 50), 2),
        "latency_p95_ms": round(_percentile(latencies, 95), 2),
        "error_rate": round(failures / max(total, 1), 4),
        "duration_s": round(dur, 3),
        "simulated": True,
        "traffic_profile": profile,
        "time_scale": speed_factor,
        "telemetry_source": "gateway",
    }

    return summary


async def run_continuous(
    target_url: str,
    profile: str = "steady",
    speed_factor: float | None = None,
    concurrency: int = 8,
) -> None:
    """Send a fixed-rate live profile indefinitely and report each 10s window."""
    speed_factor = float(os.getenv("LOADGEN_SPEED_FACTOR", "1")) if speed_factor is None else speed_factor
    if speed_factor <= 0:
        raise ValueError("speed_factor must be positive")
    if profile not in {"steady", "ramp", "spike"}:
        raise ValueError("continuous profile must be steady, ramp, or spike")
    latencies: list[float] = []
    results: list[bool] = []
    semaphore = asyncio.Semaphore(concurrency)
    tasks: set[asyncio.Task] = set()
    request_id = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            health = await client.get(f"{target_url.rstrip('/')}/health")
            health.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"gateway unreachable at {target_url.rstrip('/')}/health: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        async def send_one(identifier: int) -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(
                        f"{target_url.rstrip('/')}/work",
                        headers={"x-request-id": str(identifier)},
                    )
                except httpx.ConnectError as exc:
                    raise RuntimeError(
                        f"gateway unreachable at {target_url.rstrip('/')}/work: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                latencies.append((time.perf_counter() - started) * 1000.0)
                results.append(response.status_code == 200)

        started = time.monotonic()
        next_report = started + 10.0
        next_send = started
        while True:
            # Surface worker failures quickly (especially a gateway going away).
            completed = [task for task in tasks if task.done()]
            for task in completed:
                tasks.remove(task)
                task.result()
            now = time.monotonic()
            elapsed = now - started
            if profile == "ramp":
                target_rpm = 60.0 + 540.0 * min(elapsed / 300.0, 1.0)
            elif profile == "spike":
                target_rpm = 480.0 if 60.0 <= elapsed < 180.0 else 60.0
            else:
                target_rpm = 60.0
            target_rpm *= speed_factor
            interval = 60.0 / target_rpm
            if now >= next_send:
                request_id += 1
                tasks.add(asyncio.create_task(send_one(request_id)))
                next_send += interval
            if now >= next_report:
                count = len(results)
                successes = sum(results)
                p95 = _percentile(latencies, 95)
                success_rate = successes / max(count, 1) * 100.0
                print(
                    f"loadgen {profile}: target {target_rpm:.0f} rpm, sent {count}, "
                    f"success {success_rate:.1f}%, p95 {p95:.1f} ms "
                    f"({count} requests/10s)",
                    flush=True,
                )
                results.clear()
                latencies.clear()
                next_report += 10.0
            await asyncio.sleep(min(0.1, max(0.01, next_send - time.monotonic())))


def main(argv: list[str] | None = None) -> None:
    import json
    import os

    p = argparse.ArgumentParser(description="ElasticMind load generator")
    p.add_argument("--target-url", default=os.getenv("LOADGEN_TARGET_URL", "http://localhost:8001"))
    p.add_argument("--backend-url", default=os.getenv("LOADGEN_BACKEND_URL"))
    p.add_argument("--trace", default=os.getenv("LOADGEN_TRACE"))
    p.add_argument("--profile", choices=["steady", "ramp", "spike"],
                   default=os.getenv("LOADGEN_PROFILE", "steady"))
    p.add_argument("--days", type=int, default=int(os.getenv("LOADGEN_DAYS", "1")))
    p.add_argument("--speed-factor", type=float, default=None)
    p.add_argument("--max-requests", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--once", action="store_true", help="run a finite profile instead of continuous traffic")
    args = p.parse_args(argv)

    factor = args.speed_factor if args.speed_factor is not None else float(os.getenv("LOADGEN_SPEED_FACTOR", "1"))
    base_rate = {"steady": 60.0, "ramp": 60.0, "spike": 480.0}[args.profile]
    actual_rate = base_rate * factor
    profile_label = " (8x steady during the 2-minute spike)" if args.profile == "spike" else ""
    headline = (f"Starting at 60 requests/minute; spike reaches 480{profile_label}"
                if args.profile == "spike" else f"Starting at {actual_rate:g} requests/minute")
    print(f"{headline} "
          f"to {args.target_url.rstrip('/')}/work via the configured target URL.", flush=True)

    try:
        if not args.once:
            asyncio.run(run_continuous(
                target_url=args.target_url,
                profile=args.profile,
                speed_factor=args.speed_factor,
                concurrency=args.concurrency,
            ))
        else:
            summary = asyncio.run(
                run_load(
                    target_url=args.target_url,
                    backend_url=args.backend_url,
                    trace_path=args.trace,
                    profile=args.profile,
                    days=args.days,
                    speed_factor=args.speed_factor,
                    max_requests=args.max_requests,
                    concurrency=args.concurrency,
                )
            )
            print(json.dumps(summary, indent=2))
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        print(f"loadgen failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
