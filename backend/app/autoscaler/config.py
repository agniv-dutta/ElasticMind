"""Autoscaler configuration."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.core.config import Settings


@dataclass
class AutoscalerConfig:
    min_instances: int = 1
    max_instances: int = 10
    target_utilization: float = 0.70
    headroom: float = 0.20
    capacity_per_instance: float = field(default_factory=lambda: Settings().CAPACITY_PER_REPLICA_RPM)
    fast_scale_up_cooldown_s: int = 30
    slow_scale_down_cooldown_s: int = 120
    hysteresis: float = 0.05
    provisioning_delay_s: float = 90.0

    @classmethod
    def from_settings(cls, s: Settings | None = None) -> "AutoscalerConfig":
        s = s or Settings()
        return cls(
            min_instances=s.min_instances,
            max_instances=s.max_instances,
            target_utilization=s.target_utilization,
            headroom=s.headroom,
            capacity_per_instance=s.CAPACITY_PER_REPLICA_RPM,
            fast_scale_up_cooldown_s=s.fast_scale_up_cooldown_s,
            slow_scale_down_cooldown_s=s.slow_scale_down_cooldown_s,
            hysteresis=s.hysteresis,
            provisioning_delay_s=s.provisioning_delay_s,
        )