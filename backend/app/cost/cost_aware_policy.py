"""Cost-aware policy skeleton (simulated)."""
from __future__ import annotations

from dataclasses import dataclass
from backend.app.metrics.calculator import cost_usd, sla_violations


@dataclass
class CostAwareDecision:
    desired: int
    expected_cost_usd: float
    expected_sla_viol: int


@dataclass
class CostAwareParams:
    instance_cost_usd_per_hour: float = 0.096
    sla_penalty_usd_per_violation: float = 5.0
    spot_discount: float = 0.7
    interruption_risk: float = 0.05


def cost_estimate(
    instances: int, params: CostAwareParams, duration_hours: float = 1.0
) -> float:
    replica_seconds = instances * duration_hours * 3600.0
    return cost_usd(replica_seconds, params.instance_cost_usd_per_hour / 3600.0)


def choose_min_cost(
    desired_options: list[int],
    cost_fn,
    penalty_fn,
    penalty_usd: float = 5.0,
) -> CostAwareDecision:
    if not desired_options:
        raise ValueError("desired_options must not be empty")
    best = None
    best_score = float("inf")
    for d in desired_options:
        c = float(cost_fn(d))
        v = int(penalty_fn(d))
        score = c + penalty_usd * v
        if score < best_score:
            best_score = score
            best = CostAwareDecision(desired=d, expected_cost_usd=c, expected_sla_viol=v)
    return best


def choose_from_forecast(
    forecast_p90: float,
    capacity_per_instance: float,
    options: list[int],
    params: CostAwareParams | None = None,
    duration_hours: float = 1 / 60,
) -> CostAwareDecision:
    """Choose capacity using expected cost plus an SLA penalty."""
    params = params or CostAwareParams()

    def cost(instances: int) -> float:
        return cost_estimate(instances, params, duration_hours)

    def violations(instances: int) -> int:
        capacity = instances * capacity_per_instance
        return sla_violations(forecast_p90, capacity, 0.0, float("inf"))

    return choose_min_cost(options, cost, violations, params.sla_penalty_usd_per_violation)
