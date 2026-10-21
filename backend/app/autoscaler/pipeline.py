"""Explicit per-cycle decision pipeline and immutable control tick record."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.autoscaler.policy import MLForecastPolicy, ReactiveThresholdPolicy, StaticPolicy
from backend.app.core.config import Settings


@dataclass(frozen=True)
class ControlTick:
    observed_load: float
    forecast_p50: float | None
    forecast_p90: float | None
    horizon: int
    model_version: str | None
    desired_ml: int | None
    desired_reactive: int
    final_desired: int
    decision_source: Literal["ml", "safety_net", "fallback", "static"]
    reason: str
    cooldown_state: str
    timestamp: datetime

    def as_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class ControlPipeline:
    """Select ML, safety override, reactive fallback, or explicit static policy."""

    def __init__(self, settings: Settings, cfg: AutoscalerConfig, loop: ControlLoop) -> None:
        self.settings = settings
        self.cfg = cfg
        self.loop = loop
        self.ml = MLForecastPolicy()
        self.reactive = ReactiveThresholdPolicy()
        self.static = StaticPolicy()

    def tick(
        self,
        *,
        observed_load: float,
        utilization: float,
        latency_ms: float,
        forecast_p50: float | None,
        forecast_p90: float | None,
        horizon: int,
        model_version: str | None,
        fallback_reason: str | None = None,
        timestamp: datetime | None = None,
        now: float | None = None,
    ) -> ControlTick:
        current = self.loop.state.current_instances
        reactive = self.reactive.compute_desired(
            current_utilization=utilization,
            current_instances=current,
            min_instances=self.cfg.min_instances,
            max_instances=self.cfg.max_instances,
        )
        safety_triggered = (
            utilization >= self.settings.SAFETY_UTILIZATION_THRESHOLD
            or latency_ms >= self.settings.SLA_LATENCY_MS
        )
        if safety_triggered:
            effective_capacity = self.cfg.capacity_per_instance * self.cfg.target_utilization
            load_sized = math.ceil(observed_load * (1 + self.cfg.headroom) / max(effective_capacity, 1e-9))
            reactive = max(current + (1 if latency_ms >= self.settings.SLA_LATENCY_MS else 0), load_sized)
            reactive = max(self.cfg.min_instances, min(self.cfg.max_instances, reactive))

        ml_candidate: int | None = None
        if forecast_p50 is not None and forecast_p90 is not None and fallback_reason is None:
            ml_candidate = self.ml.compute_desired(
                predicted_load_p50=forecast_p50,
                predicted_load_p90=forecast_p90,
                current_capacity=current * self.cfg.capacity_per_instance,
                target_utilization=self.cfg.target_utilization,
                headroom=self.cfg.headroom,
                min_instances=self.cfg.min_instances,
                max_instances=self.cfg.max_instances,
                capacity_per_instance=self.cfg.capacity_per_instance,
            )

        cooldown_state = "inactive"
        if safety_triggered:
            source = "safety_net"
            final = reactive
            reason = (
                f"Safety override: utilization {utilization:.3f} / latency {latency_ms:.1f} ms; "
                f"ML candidate {ml_candidate}, reactive candidate {reactive}."
            )
            # Safety action is immediate and starts the appropriate cooldown.
            if final != current:
                self.loop.state.current_instances = final
                self.loop.state.last_scale_ts = now if now is not None else self.loop._now()
                self.loop.state.last_reason = reason
                self.loop.state.in_cooldown = True
        elif self.settings.policy == "static":
            source = "static"
            final = self.static.compute_desired(
                min_instances=self.cfg.min_instances, max_instances=self.cfg.max_instances
            )
            reason = f"Static policy selected {final} replicas."
        elif fallback_reason is not None or ml_candidate is None:
            source = "fallback"
            final = reactive
            reason = f"Reactive fallback: {fallback_reason or 'forecast unavailable'}; candidate {reactive}."
        else:
            source = "ml"
            controlled = self.loop.evaluate(
                predicted_load_p50=forecast_p50,
                predicted_load_p90=forecast_p90,
                current_capacity=current * self.cfg.capacity_per_instance,
                current_utilization=utilization,
                now=now,
            )
            final = controlled.desired
            reason = f"ML forecast selected {ml_candidate} replicas. {controlled.reason}"
            if "cooldown" in controlled.reason:
                cooldown_state = controlled.reason
            elif self.loop.state.in_cooldown:
                cooldown_state = "active"
        self.loop.state.in_cooldown = cooldown_state != "inactive"
        return ControlTick(
            observed_load=float(observed_load),
            forecast_p50=forecast_p50,
            forecast_p90=forecast_p90,
            horizon=horizon,
            model_version=model_version,
            desired_ml=ml_candidate,
            desired_reactive=reactive,
            final_desired=int(final),
            decision_source=source,
            reason=reason,
            cooldown_state=cooldown_state,
            timestamp=timestamp or datetime.now(UTC),
        )
