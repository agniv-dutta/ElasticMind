"""Async load generator using httpx/asyncio.

Replays a workload trace or a synthetic profile as real HTTP traffic at a
configurable speed-up factor. Logs request count, success rate and p50/p95
latency back to the backend (if configured).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from pathlib import Path

import httpx
import pandas as pd
from ml.data.generate import generate_workload
from backend.app.core.config import Settings


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
    settings = Settings()
    speed_factor = settings.TIME_SCALE if speed_factor is None else speed_factor
    trace = _load_trace(trace_path, profile, days)
    requests_per_min = trace["requests"].astype(float).tolist()

    latencies: list[float] = []
    successes = 0
    failures = 0
    total = 0

    start = time.time()
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=10.0) as client:
        async def one() -> None:
            nonlocal successes, failures, total
            async with sem:
                try:
                    t0 = time.perf_counter()
                    r = await client.get(f"{target_url}/work")
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
        for i in range(len(trace)):
            if max_requests is not None and spawned >= max_requests:
                break
            # n requests to launch in this simulated minute: per-second rate
            # from the trace scaled by the speed-up factor.
            n = max(1, round(requests_per_min[i] / 60.0 * speed_factor))
            if max_requests is not None:
                n = min(n, max_requests - spawned)
            spawned += n
            for _ in range(n):
                tasks.append(asyncio.create_task(one()))
            # yield control so in-flight requests can progress
            await asyncio.sleep(0)
        # run all
        await asyncio.gather(*tasks)

    dur = max(time.time() - start, 1e-6)
    summary = {
        "target": target_url,
        "requests_total": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(successes / max(total, 1), 4),
        "latency_p50_ms": round(statistics.quantiles(latencies, n=5)[0], 2) if len(latencies) >= 5 else 0.0,
        "latency_p95_ms": round(statistics.quantiles(latencies, n=5)[-1], 2) if len(latencies) >= 5 else 0.0,
        "duration_s": round(dur, 3),
        "simulated": True,
    }

    if backend_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as bc:
                await bc.post(f"{backend_url}/metrics", json=summary)
        except Exception:
            pass

    return summary


def main(argv: list[str] | None = None) -> None:
    import json
    import os

    p = argparse.ArgumentParser(description="ElasticMind load generator")
    p.add_argument("--target-url", default="http://localhost:8001")
    p.add_argument("--backend-url", default=os.getenv("LOADGEN_BACKEND_URL"))
    p.add_argument("--trace", default=os.getenv("LOADGEN_TRACE"))
    p.add_argument("--profile", default=os.getenv("LOADGEN_PROFILE", "diurnal"))
    p.add_argument("--days", type=int, default=int(os.getenv("LOADGEN_DAYS", "1")))
    p.add_argument("--speed-factor", type=float, default=None)
    p.add_argument("--max-requests", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=8)
    args = p.parse_args(argv)

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


if __name__ == "__main__":
    main()
