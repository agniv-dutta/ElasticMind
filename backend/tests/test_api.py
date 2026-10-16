"""Tests for FastAPI backend endpoints."""

from __future__ import annotations

from backend.app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_predict_and_forecast() -> None:
    resp = client.post("/predict", json={"horizon_min": 15, "history_minutes": 240})
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"]
    assert len(data["forecast"]) == 3  # horizons 5/15/30


def test_forecast_get() -> None:
    resp = client.get("/forecast")
    assert resp.status_code == 200
    assert "forecast" in resp.json()


def test_capacity_endpoint() -> None:
    resp = client.get("/capacity")
    assert resp.status_code == 200
    body = resp.json()
    assert "current_instances" in body
    assert "capacity_per_instance" in body
    assert "target_utilization" in body


def test_autoscaler_policy_start_stop() -> None:
    resp = client.post("/autoscaler/policy", json={"policy": "ml"})
    assert resp.status_code == 200
    resp = client.post("/autoscaler/start")
    assert resp.status_code == 200
    resp = client.post("/autoscaler/stop")
    assert resp.status_code == 200


def test_faults_endpoints() -> None:
    resp = client.post("/faults/bias", json={"bias_percent": 10})
    assert resp.status_code == 200
    resp = client.post("/faults/spike", json={"magnitude": 2.0, "duration_minutes": 5})
    assert resp.status_code == 200


def test_metrics_current() -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "current_utilization" in body
    assert "latency_ms" in body
    assert "cost_usd" in body
    assert "energy_kwh" in body
    assert "sla_count" in body


def test_metrics_history_decisions_experiments() -> None:
    resp = client.get("/metrics/history")
    assert resp.status_code == 200
    resp = client.get("/decisions")
    assert resp.status_code == 200
    resp = client.get("/experiments")
    assert resp.status_code == 200
