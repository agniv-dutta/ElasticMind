"""Tests for robustness safeguards (Prompt 9)."""

from __future__ import annotations

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.robustness.safeguards import (
    ForecastErrorTracker,
    SafeguardedController,
)


def test_error_tracker_rolling_mape() -> None:
    t = ForecastErrorTracker(window=3)
    assert t.update(predicted=100, actual=100) == 0.0
    assert t.update(predicted=150, actual=100) == 0.25  # (0 + 0.5)/2
    assert t.update(predicted=200, actual=100) == (0 + 0.5 + 1.0) / 3
    # window bounds the history
    t.update(predicted=100, actual=100)
    t.update(predicted=100, actual=100)
    assert t.mape() < 1.0


def test_safety_net_triggers_on_high_utilization() -> None:
    cfg = AutoscalerConfig(min_instances=1, max_instances=10, capacity_per_instance=100)
    ctl = SafeguardedController(cfg=cfg)
    dec = ctl.step(
        predicted_load_p50=50,
        predicted_load_p90=55,
        current_capacity=100,
        current_utilization=0.95,
        current_instances=1,
        now=0.0,
    )
    assert ctl.state.safety_net_triggered
    assert dec.desired > 1
    assert "safety_net" in dec.reason


def test_drift_alarm_and_fallback() -> None:
    cfg = AutoscalerConfig(min_instances=1, max_instances=10, capacity_per_instance=100)
    ctl = SafeguardedController(cfg=cfg, drift_mape_threshold=0.20, recover_mape_threshold=0.05)
    # feed large errors -> drift
    for _ in range(20):
        ctl.observe(predicted=300, actual=100)
    assert ctl.state.drift_alarm
    assert ctl.state.active_mode == "reactive_fallback"
    # feed small errors -> recovery
    for _ in range(30):
        ctl.observe(predicted=100, actual=100)
    assert not ctl.state.drift_alarm
    assert ctl.state.active_mode == "ml"
    assert ctl.state.recoveries >= 1


def test_confidence_headroom_widens_with_error() -> None:
    cfg = AutoscalerConfig()
    ctl = SafeguardedController(cfg=cfg, confidence_gain=2.0)
    ctl.observe(predicted=150, actual=100)  # mape 0.5
    assert ctl.state.headroom_mult > 1.0


def test_fallback_uses_reactive_policy() -> None:
    cfg = AutoscalerConfig(min_instances=1, max_instances=10, capacity_per_instance=100)
    ctl = SafeguardedController(cfg=cfg, drift_mape_threshold=0.1, recover_mape_threshold=0.01)
    for _ in range(10):
        ctl.observe(predicted=300, actual=100)
    assert ctl.state.active_mode == "reactive_fallback"
    dec = ctl.step(
        predicted_load_p50=100,
        predicted_load_p90=110,
        current_capacity=100,
        current_utilization=0.85,
        current_instances=1,
        now=60.0,
    )
    assert "reactive_fallback" in dec.reason or "safety_net" in dec.reason
