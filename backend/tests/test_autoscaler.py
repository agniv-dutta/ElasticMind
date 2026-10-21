"""Tests for autoscaling engine: policies, cooldowns, hysteresis, clamps."""

from __future__ import annotations

import time

from backend.app.autoscaler.actuator import LocalSimActuator
from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.autoscaler.policy import (
    MLForecastPolicy,
    ReactiveThresholdPolicy,
    StaticPolicy,
)


def test_ml_policy_computes_desired_p90() -> None:
    p = MLForecastPolicy(prefer="p90")
    desired = p.compute_desired(
        predicted_load_p50=400,
        predicted_load_p90=900,
        current_capacity=1000,
        target_utilization=0.70,
        headroom=0.20,
        min_instances=1,
        max_instances=10,
        capacity_per_instance=500,
    )
    # effective per instance 350; 900*1.2/350 ~ 3.086 -> ceil to 4? 3.09 -> ceil 4
    assert desired == 4


def test_ml_policy_clamps_min_max() -> None:
    p = MLForecastPolicy()
    assert p.compute_desired(0, 0, 1000, 0.7, 0, 1, 10, 500) == 1
    high = p.compute_desired(1e6, 1e6, 1000, 0.7, 0, 1, 2, 100)
    assert high <= 2


def test_ml_policy_handles_zero_load_min() -> None:
    p = MLForecastPolicy()
    d = p.compute_desired(predicted_load_p50=0, predicted_load_p90=0, current_capacity=500,
                          min_instances=1, max_instances=10, capacity_per_instance=500)
    assert d == 1


def test_reactive_threshold_policy_basics() -> None:
    r = ReactiveThresholdPolicy()
    assert r.compute_desired(current_utilization=0.85, current_instances=2) == 3
    assert r.compute_desired(current_utilization=0.4, current_instances=3) == 2
    assert r.compute_desired(current_utilization=0.65, current_instances=2) == 2


def test_static_policy_fixed() -> None:
    s = StaticPolicy(fixed=3)
    cfg = AutoscalerConfig(min_instances=2, max_instances=5)
    assert s.compute_desired(min_instances=cfg.min_instances, max_instances=cfg.max_instances) == 3
    s2 = StaticPolicy(fixed=10)
    assert s2.compute_desired(min_instances=1, max_instances=3) == 3


def test_actuator_clamps_and_tracks() -> None:
    a = LocalSimActuator(initial=5, min_c=1, max_c=6, delay_s=30)
    assert a.current() == 5
    a.set_desired(10)
    assert a.current() == 6
    a.set_desired(0)
    assert a.current() == 1


def test_control_loop_cooldown_after_scale_up() -> None:
    cfg = AutoscalerConfig(fast_scale_up_cooldown_s=0.5, slow_scale_down_cooldown_s=10.0,
                           capacity_per_instance=100, target_utilization=0.7)
    loop = ControlLoop(cfg)
    loop.reset(current_instances=1)
    d = loop.evaluate(predicted_load_p50=200, predicted_load_p90=200, current_capacity=200)  # needs ~4? 200*1.2/(70)=3.43 -> 4
    assert d.desired == 4 and d.action == "scale_up"
    # immediately again with higher load — should be in cooldown
    d2 = loop.evaluate(predicted_load_p50=400, predicted_load_p90=400, current_capacity=400)
    assert d2.action == "no_change"
    assert d2.desired == 4
    time.sleep(0.6)
    d3 = loop.evaluate(predicted_load_p50=400, predicted_load_p90=400, current_capacity=400)  # 480*? 400*1.2/70=6.86 -> 7
    assert d3.action == "scale_up"


def test_control_loop_slow_scale_down_cooldown() -> None:
    cfg = AutoscalerConfig(fast_scale_up_cooldown_s=0.1, slow_scale_down_cooldown_s=0.5,
                           capacity_per_instance=500, target_utilization=0.7, headroom=0.0)
    loop = ControlLoop(cfg)
    loop.reset(current_instances=5)
    # drop load so desired becomes 1? 100 * 1.0/(350)=0.285 -> 1
    d1 = loop.evaluate(predicted_load_p50=100, predicted_load_p90=100, current_capacity=2500)
    assert d1.action == "scale_down"
    assert d1.desired == 1
    # try to drop again immediately — cooldown blocks
    d2 = loop.evaluate(predicted_load_p50=10, predicted_load_p90=10, current_capacity=2500)
    assert d2.action == "no_change" and d2.desired == 1
    time.sleep(0.6)
    d3 = loop.evaluate(predicted_load_p50=10, predicted_load_p90=10, current_capacity=2500)
    assert d3.action == "no_change"  # still at 1 (min)
    assert d3.desired == 1


def test_hysteresis_prevents_flapping() -> None:
    cfg = AutoscalerConfig(capacity_per_instance=500, target_utilization=0.7, headroom=0.0,
                           hysteresis=0.2, fast_scale_up_cooldown_s=0, slow_scale_down_cooldown_s=0)
    loop = ControlLoop(cfg)
    loop.reset(current_instances=2)
    # 350 per inst * 2 = 700. Need +20% of 500? threshold ~ 100. 2->3 needs increase >= 100?
    # need_increase = p90 - cur*cap*tu = 800 - 700 = 100. threshold 500*0.2=100. < is false (need<100? 100<100 false). So should scale up.
    d = loop.evaluate(predicted_load_p50=800, predicted_load_p90=800, current_capacity=1000)
    assert d.action == "scale_up"
    loop.state.last_scale_ts = 0  # clear cooldown for next eval
    # Now at 3, cur*cap*tu=1050. p90=800 -> excess 250. excess < 50? 250<50 false. No scale down.
    d2 = loop.evaluate(predicted_load_p50=800, predicted_load_p90=800, current_capacity=1500)
    assert d2.desired == 3
    loop.state.last_scale_ts = 0
    # Very close: p90=700 -> excess 350? still >= threshold/2*? down threshold is threshold*0.5=50. 1050-700=350>=50 -> no change.
    d3 = loop.evaluate(predicted_load_p50=1020, predicted_load_p90=1020, current_capacity=1500)
    assert d3.desired == 3


def test_zero_load_min_clamp() -> None:
    p = MLForecastPolicy()
    d = p.compute_desired(0, 0, 500, 0.7, 0.2, 1, 5, 500)
    assert d == 1


def test_controller_respects_capacity_limits() -> None:
    """Test that controller doesn't exceed min/max instances."""
    cfg = AutoscalerConfig(
        min_instances=2,
        max_instances=5,
        capacity_per_instance=100,
        target_utilization=0.7,
        headroom=0.2,
        fast_scale_up_cooldown_s=0,
        slow_scale_down_cooldown_s=0,
    )
    loop = ControlLoop(cfg)
    loop.reset(current_instances=2)
    
    # Very high load - should cap at max_instances (5)
    d = loop.evaluate(predicted_load_p50=10000, predicted_load_p90=10000, current_capacity=200)
    assert d.desired == 5
    assert d.action == "scale_up"
    
    # Very low load - should cap at min_instances (2)
    loop.reset(current_instances=5)
    d2 = loop.evaluate(predicted_load_p50=0, predicted_load_p90=0, current_capacity=500)
    assert d2.desired == 2
    assert d2.action == "scale_down"


def test_controller_with_changing_workload() -> None:
    """Test controller responds to changing workload patterns."""
    cfg = AutoscalerConfig(
        min_instances=1,
        max_instances=10,
        capacity_per_instance=100,
        target_utilization=0.7,
        headroom=0.2,
        fast_scale_up_cooldown_s=0,
        slow_scale_down_cooldown_s=0,
    )
    loop = ControlLoop(cfg)
    loop.reset(current_instances=1)
    
    # Low load - should stay at min
    d1 = loop.evaluate(predicted_load_p50=50, predicted_load_p90=60, current_capacity=100)
    assert d1.desired == 1
    assert d1.action == "no_change"
    
    # Medium load - should scale up moderately
    d2 = loop.evaluate(predicted_load_p50=400, predicted_load_p90=500, current_capacity=100)
    assert d2.desired > 1
    assert d2.action == "scale_up"
    
    # Update state
    loop.state.current_instances = d2.desired
    
    # High load - should scale up more
    d3 = loop.evaluate(predicted_load_p50=800, predicted_load_p90=900, current_capacity=d2.desired * 100)
    assert d3.desired > d2.desired
    
    # Load drops - should scale down
    loop.state.current_instances = d3.desired
    d4 = loop.evaluate(predicted_load_p50=100, predicted_load_p90=120, current_capacity=d3.desired * 100)
    assert d4.desired < d3.desired


def test_controller_records_meaningful_reasons() -> None:
    """Test that controller provides descriptive reasons for decisions."""
    cfg = AutoscalerConfig(
        min_instances=1,
        max_instances=10,
        capacity_per_instance=100,
        target_utilization=0.7,
        headroom=0.2,
        fast_scale_up_cooldown_s=0,
        slow_scale_down_cooldown_s=0,
    )
    loop = ControlLoop(cfg)
    loop.reset(current_instances=1)
    
    # Scale up decision
    d1 = loop.evaluate(predicted_load_p50=500, predicted_load_p90=600, current_capacity=100)
    assert d1.action == "scale_up"
    assert "scale_up" in d1.reason
    assert "P90" in d1.reason
    
    # No change decision
    d2 = loop.evaluate(predicted_load_p50=500, predicted_load_p90=600, current_capacity=100)
    assert d2.action == "no_change"
    assert "within bounds" in d2.reason
