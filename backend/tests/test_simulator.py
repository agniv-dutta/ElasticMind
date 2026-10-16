"""Tests for simulator and evaluation helpers."""

from __future__ import annotations

import pandas as pd
import pytest
from backend.app.simulator.simulator import (
    SimConfig,
    WorkloadReplaySimulator,
    summarize_simulation,
)
from ml.data.generate import generate_workload


@pytest.fixture
def trace():
    return generate_workload(profile="diurnal", days=1, seed=1)


def test_simulator_replays_minutely(trace: pd.DataFrame) -> None:
    sim = WorkloadReplaySimulator(SimConfig(provisioning_delay_s=90.0))
    res = sim.simulate(trace, lambda row, i: 3, start_capacity=3)
    assert len(res) == len(trace)
    assert {"demand_req_min", "effective_instances", "utilization", "sla_violation", "sim_latency_ms",
            "cost_usd", "energy_kwh", "co2_kg"} <= set(res.columns)
    assert res["timestamp"].is_monotonic_increasing
    assert (res["effective_instances"] >= 1).all()
    assert res["sla_violation"].isin([0, 1]).all()


def test_simulator_handles_overload(trace: pd.DataFrame) -> None:
    sim = WorkloadReplaySimulator(SimConfig(service_rate=10.0))
    res = sim.simulate(trace, lambda row, i: 1, start_capacity=1)
    assert res["utilization"].max() > 1.0
    assert res["sla_violation"].sum() > 0


def test_simulator_delay_applied(trace: pd.DataFrame) -> None:
    # Large delay -> effective lags desired for early steps
    sim = WorkloadReplaySimulator(SimConfig(provisioning_delay_s=120.0))
    res = sim.simulate(trace, lambda row, i: 1 + (i % 5), start_capacity=2)
    # with delay ~2 min, effective[0] should be start_capacity, not desired[0]
    assert res["effective_instances"].iloc[0] == 2


def test_summarize_simulation_keys(trace: pd.DataFrame) -> None:
    sim = WorkloadReplaySimulator()
    res = sim.simulate(trace, lambda row, i: 2, start_capacity=2)
    s = summarize_simulation(res)
    assert {"avg_utilization", "sla_violations_total", "total_cost_usd",
            "total_energy_kwh", "avg_latency_ms", "p90_latency_ms"} <= set(s)
    assert s["total_minutes"] == 1440
