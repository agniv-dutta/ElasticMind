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
        # prefer calibration if available
        cap = getattr(s, "capacity_per_instance", None)
        if cap is None:
            cap = getattr(s, "CAPACITY_PER_REPLICA_RPM", None)
        if cap is None:
            cap = getattr(s, "capacity_per_replica", None)
        if cap is None:
            cap = 500.0
        try:
            cap = float(cap)
        except Exception:
            cap = 500.0
        return cls(
            min_instances=getattr(s, "MIN_REPLICAS", getattr(s, "min_instances", 1)),
            max_instances=getattr(s, "MAX_REPLICAS", getattr(s, "max_instances", 10)),
            target_utilization=getattr(s, "TARGET_UTILIZATION", getattr(s, "target_utilization", 0.7)),
            headroom=getattr(s, "headroom", 0.2),
            capacity_per_instance=cap,
            fast_scale_up_cooldown_s=int(getattr(s, "COOLDOWN_UP_S", getattr(s, "fast_scale_up_cooldown_s", 30))),
            slow_scale_down_cooldown_s=int(getattr(s, "COOLDOWN_DOWN_S", getattr(s, "slow_scale_down_cooldown_s", 120))),
            hysteresis=getattr(s, "hysteresis", 0.05),
            provisioning_delay_s=getattr(s, "STARTUP_DELAY_S", getattr(s, "provisioning_delay_s", 90.0)),
        )
