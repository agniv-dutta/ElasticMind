"""httpx-based async tests for the FastAPI backend (ASGI transport)."""

from __future__ import annotations

import httpx
import pytest
from backend.app.main import app


@pytest.mark.asyncio
async def test_health_async() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_predict_async() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/predict", json={"horizon_min": 5, "history_minutes": 240})
    assert r.status_code == 200
    assert "forecast" in r.json()


@pytest.mark.asyncio
async def test_metrics_async() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["sla_count"] >= 0
