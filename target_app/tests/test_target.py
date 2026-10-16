"""Tests for target app."""

from __future__ import annotations

from fastapi.testclient import TestClient
from target_app.app import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_work_returns_latency() -> None:
    r = client.get("/work")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["simulated"] is True
    assert body["latency_ms"] >= 0
