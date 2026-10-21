"""Tests for FastAPI backend endpoints."""

from __future__ import annotations

from backend.app.main import app, live_metrics
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


def test_post_metrics_from_loadgen() -> None:
    """Test that POST /metrics receives and stores loadgen data."""
    # Reset live metrics
    live_metrics.request_count = 0
    
    loadgen_data = {
        "target": "http://localhost:8001",
        "requests_total": 300,
        "successes": 300,
        "failures": 0,
        "success_rate": 1.0,
        "latency_p50_ms": 366.85,
        "latency_p95_ms": 391.14,
        "duration_s": 13.637,
        "simulated": True,
    }
    
    resp = client.post("/metrics", json=loadgen_data)
    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    assert resp.json()["simulated"] is True
    
    # Verify live metrics were updated
    assert live_metrics.request_count == 300
    assert live_metrics.latency_p50_ms == 366.85
    assert live_metrics.latency_p95_ms == 391.14
    assert live_metrics.success_rate == 1.0


def test_metrics_uses_live_data() -> None:
    """Test that GET /metrics uses live data from loadgen when available."""
    # Reset live metrics
    live_metrics.request_count = 0
    
    # Get metrics without live data (should be baseline)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["current_utilization"] == 0.0
    assert body["latency_ms"] == 0.0
    
    # Post live metrics
    loadgen_data = {
        "requests_total": 600,
        "successes": 600,
        "failures": 0,
        "success_rate": 1.0,
        "latency_p50_ms": 200.0,
        "latency_p95_ms": 250.0,
        "duration_s": 10.0,
        "simulated": True,
    }
    client.post("/metrics", json=loadgen_data)
    
    # Get metrics with live data (should reflect actual load)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    # requests_per_min = 600 / 10 * 60 = 3600 rpm
    # capacity = 1 * 100 = 100
    # utilization = 3600 / 100 = 36.0 (clamped to 1.0)
    assert body["current_utilization"] == 1.0  # saturated
    assert body["latency_ms"] == 200.0


def test_sla_violation_on_high_latency() -> None:
    """Test that high latency triggers SLA violation count."""
    live_metrics.request_count = 0
    
    # Post metrics with low latency (no SLA violation)
    low_latency_data = {
        "requests_total": 100,
        "successes": 100,
        "failures": 0,
        "success_rate": 1.0,
        "latency_p50_ms": 100.0,
        "latency_p95_ms": 150.0,
        "duration_s": 5.0,
        "simulated": True,
    }
    client.post("/metrics", json=low_latency_data)
    resp = client.get("/metrics")
    assert resp.json()["sla_count"] == 0
    
    # Post metrics with high latency (SLA violation)
    high_latency_data = {
        "requests_total": 100,
        "successes": 100,
        "failures": 0,
        "success_rate": 1.0,
        "latency_p50_ms": 600.0,
        "latency_p95_ms": 700.0,
        "duration_s": 5.0,
        "simulated": True,
    }
    client.post("/metrics", json=high_latency_data)
    resp = client.get("/metrics")
    assert resp.json()["sla_count"] == 1
