"""Autoscaler configuration with sensible defaults.

All numeric defaults are documented values used for local simulation; the
project treats outputs derived from them as *simulated*."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutoscalerConfig:
    min_instances: int = 1
    max_instances: int = 10
    capacity_per_instance: float = 100.0
    target_utilization: float = 0.70
    headroom: float = 0.20
    fast_scale_up_cooldown_s: int = 30
    slow_scale_down_cooldown_s: int = 120
    hysteresis: float = 0.05
    provision_delay_s: float = 90.0

    @classmethod
    def from_env(cls) -> AutoscalerConfig:
        import os

        def f(name: str, default: float, t=int) -> int | float:
            v = os.getenv(name)
            if v is None:
                return default
            return t(float(v)) if t is int else float(v)

        return cls(
            min_instances=f("ELASTICMIND_MIN_INSTANCES", 1, int),
            max_instances=f("ELASTICMIND_MAX_INSTANCES", 10, int),
            capacity_per_instance=f("ELASTICMIND_CAPACITY_PER_INSTANCE", 500.0, float),
            target_utilization=f("ELASTICMIND_TARGET_UTILIZATION", 0.70, float),
            headroom=f("ELASTICMIND_HEADROOM", 0.20, float),
            fast_scale_up_cooldown_s=f("ELASTICMIND_SCALE_UP_COOLDOWN_S", 30, int),
            slow_scale_down_cooldown_s=f("ELASTICMIND_SCALE_DOWN_COOLDOWN_S", 120, int),
            hysteresis=f("ELASTICMIND_HYSTERESIS", 0.05, float),
            provision_delay_s=f("ELASTICMIND_PROVISION_DELAY_S", 90.0, float),
        )
