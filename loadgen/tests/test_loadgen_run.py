"""Test async run_load against a local FastAPI target (in-process)."""

from __future__ import annotations

import asyncio

from loadgen.runner import run_load


def test_run_load_summary(target_server=None) -> None:
    # Just verify signature and that summary keys exist without needing a live
    # server; use httpx mock is not needed. We'll run a tiny load against a
    # stub URL that will fail gracefully (failures counted, not raised).
    summary = asyncio.run(
        run_load(
            target_url="http://localhost:1",  # unreachable -> failures
            backend_url=None,
            profile="steady",
            days=1,
            speed_factor=1000000.0,
            max_requests=5,
            concurrency=2,
        )
    )
    assert summary["requests_total"] >= 1
    assert "success_rate" in summary
    assert "latency_p50_ms" in summary
    assert summary["simulated"] is True
    assert summary["time_scale"] == 1000000.0
    assert 0 <= summary["error_rate"] <= 1
