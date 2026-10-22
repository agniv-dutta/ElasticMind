"""Explicit per-cycle decision pipeline and immutable control tick record."""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.autoscaler.policy import (
    MLForecastPolicy,
    ReactiveThresholdPolicy,
    StaticPolicy,
)
from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


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
    ml_candidate: int | None
    reactive_candidate: int
    applied: int
    blocked_by: Literal["cooldown", "hysteresis", "bounds", "none"]
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
        self._latency_window: deque[float] = deque(maxlen=settings.SAFETY_LATENCY_WINDOW_SIZE)
        self._latency_breach_ticks = 0
        logger.info(
            "Safety-net thresholds: latency p95 >= %.1f ms for %d consecutive ticks, "
            "window=%d, utilization >= %.2f or error rate > 0; cooldowns up=%ss down=%ss "
            "(TIME_SCALE=%s)",
            settings.SLA_LATENCY_MS, settings.SAFETY_LATENCY_BREACH_TICKS,
            settings.SAFETY_LATENCY_WINDOW_SIZE, settings.SAFETY_MIN_UTILIZATION,
            cfg.fast_scale_up_cooldown_s, cfg.slow_scale_down_cooldown_s, settings.TIME_SCALE,
        )

    def _windowed_p95(self, latency_ms: float) -> float:
        self._latency_window.append(max(0.0, latency_ms))
        ordered = sorted(self._latency_window)
        index = max(0, math.ceil(0.95 * len(ordered)) - 1)
        return ordered[index]

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
        error_rate: float = 0.0,
        fallback_reason: str | None = None,
        timestamp: datetime | None = None,
        now: float | None = None,
    ) -> ControlTick:
        current = self.loop.state.current_instances
        windowed_p95 = self._windowed_p95(latency_ms)
        if windowed_p95 >= self.settings.SLA_LATENCY_MS:
            self._latency_breach_ticks += 1
        else:
            self._latency_breach_ticks = 0
        reactive = self.reactive.compute_desired(
            current_utilization=utilization,
            current_instances=current,
            min_instances=self.cfg.min_instances,
            max_instances=self.cfg.max_instances,
        )
        latency_safety_ready = (
            self._latency_breach_ticks >= self.settings.SAFETY_LATENCY_BREACH_TICKS
            and (
                utilization >= self.settings.SAFETY_MIN_UTILIZATION
                or error_rate > 0.0
            )
        )
        safety_triggered = (
            utilization >= self.settings.SAFETY_UTILIZATION_THRESHOLD
            or latency_safety_ready
            or error_rate > 0.0
        )
        if safety_triggered:
            logger.info(
                "Safety override: windowed_p95=%.1fms, breach_ticks=%d/%d, "
                "utilization=%.3f (minimum=%.2f), error_rate=%.3f, latency_threshold=%.1fms",
                windowed_p95,
                self._latency_breach_ticks,
                self.settings.SAFETY_LATENCY_BREACH_TICKS,
                utilization,
                self.settings.SAFETY_MIN_UTILIZATION,
                error_rate,
                self.settings.SLA_LATENCY_MS,
            )
            effective_capacity = self.cfg.capacity_per_instance * self.cfg.target_utilization
            load_sized = math.ceil(observed_load * (1 + self.cfg.headroom) / max(effective_capacity, 1e-9))
            reactive = max(
                current + (1 if latency_safety_ready or error_rate > 0.0 else 0),
                load_sized,
            )
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
        blocked_by: Literal["cooldown", "hysteresis", "bounds", "none"] = "none"
        applied = current
        if safety_triggered:
            source = "safety_net"
            final = reactive
            reason = (
                f"Safety override: utilization {utilization:.3f} / windowed p95 {windowed_p95:.1f} ms "
                f"({self._latency_breach_ticks}/{self.settings.SAFETY_LATENCY_BREACH_TICKS} ticks) / "
                f"error rate {error_rate:.3f}; thresholds: util >= {self.settings.SAFETY_MIN_UTILIZATION:.2f} "
                f"or error > 0, latency >= {self.settings.SLA_LATENCY_MS:.1f} ms; "
                f"ML candidate {ml_candidate}, reactive candidate {reactive}."
            )
            # Safety action is immediate and starts the appropriate cooldown.
            if final != current:
                self.loop.state.current_instances = final
                self.loop.state.last_scale_ts = now if now is not None else self.loop._now()
                self.loop.state.last_reason = reason
                self.loop.state.in_cooldown = True
                cooldown_state = "active (safety override)"
            applied = final
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
            final, blocked_by, cooldown_state, reason = self._apply_candidate(
                reactive, current, now, reason
            )
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
            blocked_by = self._blocked_by_reason(controlled.reason)
            if blocked_by == "cooldown":
                remaining = max(0, int(round(
                    float(controlled.reason.split("(")[1].split("s")[0])
                )))
                reason = f"hold (cooldown {remaining}s)"
            applied = final
            if self.loop.state.last_scale_ts > 0:
                scale_up = final > current or (final == current and ml_candidate > current)
                duration = (
                    self.cfg.fast_scale_up_cooldown_s
                    if scale_up
                    else self.cfg.slow_scale_down_cooldown_s
                )
                elapsed = (now if now is not None else self.loop._now()) - self.loop.state.last_scale_ts
                if elapsed < duration:
                    cooldown_state = f"active ({max(0.0, duration - elapsed):.1f}s remaining)"
        self.loop.state.in_cooldown = cooldown_state != "inactive"
        if source != "safety_net":
            applied = final
        return ControlTick(
            observed_load=float(observed_load),
            forecast_p50=forecast_p50,
            forecast_p90=forecast_p90,
            horizon=horizon,
            model_version=model_version,
            desired_ml=ml_candidate,
            desired_reactive=reactive,
            final_desired=int(final),
            ml_candidate=ml_candidate,
            reactive_candidate=reactive,
            applied=int(applied),
            blocked_by=blocked_by,
            decision_source=source,
            reason=reason,
            cooldown_state=cooldown_state,
            timestamp=timestamp or datetime.now(UTC),
        )

    def _blocked_by_reason(self, reason: str) -> Literal["cooldown", "hysteresis", "bounds", "none"]:
        if reason.startswith("cooldown_"):
            return "cooldown"
        if reason.startswith("hysteresis_"):
            return "hysteresis"
        return "none"

    def _apply_candidate(
        self, candidate: int, current: int, now: float | None, reason: str
    ) -> tuple[int, Literal["cooldown", "hysteresis", "bounds", "none"], str, str]:
        if candidate == current:
            return current, "none", "inactive", reason
        ts = now if now is not None else self.loop._now()
        elapsed = ts - self.loop.state.last_scale_ts
        cooldown = (
            self.cfg.fast_scale_up_cooldown_s if candidate > current
            else self.cfg.slow_scale_down_cooldown_s
        )
        if self.loop.state.last_scale_ts > 0 and elapsed < cooldown:
            remaining = int(max(0, cooldown - elapsed))
            return current, "cooldown", f"active ({remaining}s remaining)", f"hold (cooldown {remaining}s)"
        self.loop.state.current_instances = candidate
        self.loop.state.last_scale_ts = ts
        return candidate, "none", f"active ({cooldown}s)", reason
