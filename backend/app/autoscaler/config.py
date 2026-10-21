"""Autoscaler configuration with sensible defaults.

All numeric defaults are documented values used for local simulation; the
project treats outputs derived from them as *simulated*."""
from __future__ import annotations

from dataclasses import dataclass, field
from backend.app.core.config import Settings


@dataclass
class AutoscalerConfig:
    min_instances: int = field(default_factory=lambda: Settings().MIN_REPLICAS)
    max_instances: int = field(default_factory=lambda: Settings().MAX_REPLICAS)
    capacity_per_instance: float = field(default_factory=lambda: Settings().CAPACITY_PER_REPLICA_RPM)
    target_utilization: float = field(default_factory=lambda: Settings().TARGET_UTILIZATION)
    headroom: float = 0.20
    fast_scale_up_cooldown_s: float = field(default_factory=lambda: Settings().scaled_delay(Settings().COOLDOWN_UP_S))
    slow_scale_down_cooldown_s: float = field(default_factory=lambda: Settings().scaled_delay(Settings().COOLDOWN_DOWN_S))
    hysteresis: float = 0.05
    provision_delay_s: float = field(default_factory=lambda: Settings().scaled_delay(Settings().STARTUP_DELAY_S))

    @classmethod
    def from_settings(cls, settings: Settings) -> AutoscalerConfig:
        return cls(
            min_instances=settings.MIN_REPLICAS,
            max_instances=settings.MAX_REPLICAS,
            capacity_per_instance=settings.CAPACITY_PER_REPLICA_RPM,
            target_utilization=settings.TARGET_UTILIZATION,
            headroom=settings.headroom,
            fast_scale_up_cooldown_s=settings.scaled_delay(settings.COOLDOWN_UP_S),
            slow_scale_down_cooldown_s=settings.scaled_delay(settings.COOLDOWN_DOWN_S),
            hysteresis=settings.hysteresis,
            provision_delay_s=settings.scaled_delay(settings.STARTUP_DELAY_S),
        )

