from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pandas as pd
import uvicorn

import gateway.app as gateway
from loadgen.runner import run_load


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_scale_from_one_to_four_reduces_p95_latency(tmp_path):
    gateway.pool = gateway.ReplicaPool(
        replicas=1, concurrency=1, queue_limit=256, cpu_burn_ms=25,
        capacity_per_replica_rpm=500,
    )
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(gateway.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health", timeout=0.2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)

        trace = tmp_path / "load.csv"
        pd.DataFrame({"timestamp": ["2026-01-01T00:00:00Z"], "requests": [60]}).to_csv(trace, index=False)
        before = asyncio.run(run_load(
            target_url=base, trace_path=str(trace), speed_factor=60,
            max_requests=60, concurrency=60,
        ))

        response = httpx.put(f"{base}/replicas", json={"desired": 4}, timeout=2)
        response.raise_for_status()
        after = asyncio.run(run_load(
            target_url=base, trace_path=str(trace), speed_factor=60,
            max_requests=60, concurrency=60,
        ))

        assert before["requests_total"] == after["requests_total"] == 60
        assert after["latency_p95_ms"] < before["latency_p95_ms"]
        records = httpx.get(f"{base}/requests").json()
        assert all({"request_id", "replica_id", "status", "latency_ms"} <= set(row) for row in records)
        assert {f"replica-{idx}" for idx in range(1, 5)} <= {
            row["replica_id"] for row in records if row["status"] == 200
        }
        interval = asyncio.run(gateway.pool.report_interval(None, 5))
        assert {"requests_total", "error_rate", "latency_p50_ms", "latency_p95_ms", "utilization"} <= set(interval)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
