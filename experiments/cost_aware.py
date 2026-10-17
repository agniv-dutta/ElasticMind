"""Cost-aware policy modeling (simulated)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostAwareParams:
    instance_cost_usd_per_hour: float = 0.096
    sla_penalty_usd_per_violation: float = 5.0
    spot_discount: float = 0.7
    interruption_risk: float = 0.05


def cost_estimate(instances: int, params: CostAwareParams, duration_hours: float = 1.0) -> float:
    return instances * params.instance_cost_usd_per_hour * duration_hours


def pareto_frontier() -> list[dict]:
    return [
        {"policy": "reactive", "cost_sim": 1.0, "sla_viol_sim": 10},
        {"policy": "predictive", "cost_sim": 0.8, "sla_viol_sim": 5},
        {"policy": "cost_aware", "cost_sim": 0.7, "sla_viol_sim": 3},
    ]