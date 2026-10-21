"""Scaling policies for static, reactive threshold, and ML-based prediction."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol
from backend.app.core.config import Settings


@dataclass
class PredictivePolicyInput:
    predicted_load_p50: float
    predicted_load_p90: float
    current_capacity: float
    target_utilization: float = field(default_factory=lambda: Settings().TARGET_UTILIZATION)
    headroom: float = 0.20
    min_instances: int = field(default_factory=lambda: Settings().MIN_REPLICAS)
    max_instances: int = field(default_factory=lambda: Settings().MAX_REPLICAS)
    capacity_per_instance: float = field(default_factory=lambda: Settings().CAPACITY_PER_REPLICA_RPM)


class Policy(Protocol):
    def compute_desired(self, *args: object, **kwargs: object) -> int:
        ...


class MLForecastPolicy:
    """Choose desired instance count based on forecast distribution (P90 by default).

    ``desired = ceil(P90 / (capacity_per_instance * target_utilization) * (1 + headroom))``
    or clamp to [min_instances, max_instances].
    """

    def __init__(self, prefer: str = "p90") -> None:
        self.prefer = prefer  # "p90" or "p50"

    def compute_desired(
        self,
        predicted_load_p50: float,
        predicted_load_p90: float,
        current_capacity: float,
        target_utilization: float | None = None,
        headroom: float = 0.20,
        min_instances: int | None = None,
        max_instances: int | None = None,
        capacity_per_instance: float | None = None,
    ) -> int:
        settings = Settings()
        target_utilization = settings.TARGET_UTILIZATION if target_utilization is None else target_utilization
        min_instances = settings.MIN_REPLICAS if min_instances is None else min_instances
        max_instances = settings.MAX_REPLICAS if max_instances is None else max_instances
        capacity_per_instance = settings.CAPACITY_PER_REPLICA_RPM if capacity_per_instance is None else capacity_per_instance
        load = predicted_load_p90 if self.prefer == "p90" else predicted_load_p50
        load = max(0.0, load)
        effective_cap_per_inst = capacity_per_instance * target_utilization
        if effective_cap_per_inst <= 0:
            raise ValueError("effective capacity per instance must be > 0")
        needed = load * (1.0 + headroom) / effective_cap_per_inst
        inst = math.ceil(needed)
        inst = max(min_instances, min(max_instances, inst))
        # Handle the case where load > 0 but needed rounds to 0 after clamps? e.g. min=1.
        if load > 0.0 and inst < min_instances:
            inst = min_instances
        return int(inst)


class ReactiveThresholdPolicy:
    """A simple reactive policy (baseline for evaluation).

    If current utilization > 0.80 → scale up by 1 (clamped). If < 0.50 →
    scale down by 1. Keeps boundaries tight to avoid flapping; no forecasting.
    """

    def compute_desired(
        self,
        current_utilization: float,
        current_instances: int,
        min_instances: int | None = None,
        max_instances: int | None = None,
    ) -> int:
        settings = Settings()
        min_instances = settings.MIN_REPLICAS if min_instances is None else min_instances
        max_instances = settings.MAX_REPLICAS if max_instances is None else max_instances
        if current_instances < min_instances:
            return min_instances
        if current_utilization > 0.80:
            return min(current_instances + 1, max_instances)
        if current_utilization < 0.50:
            return max(current_instances - 1, min_instances)
        return current_instances


class StaticPolicy:
    """Always return a fixed number of instances."""

    def __init__(self, fixed: int = 2) -> None:
        self.fixed = int(fixed)

    def compute_desired(
        self,
        min_instances: int | None = None,
        max_instances: int | None = None,
        **_: object,
    ) -> int:
        settings = Settings()
        min_instances = settings.MIN_REPLICAS if min_instances is None else min_instances
        max_instances = settings.MAX_REPLICAS if max_instances is None else max_instances
        return max(min_instances, min(max_instances, self.fixed))
