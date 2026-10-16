"""Robustness safeguards for misprediction handling (Prompt 9).

Implements:
1. Reactive safety net (override when live utilization exceeds a threshold)
2. Rolling MAPE forecast-error tracking with a drift alarm
3. Confidence-aware headroom (wider P90 margin when recent error is high)
4. Automatic fallback to the reactive policy on drift + recovery back to ML
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop, ScalingDecision
from backend.app.autoscaler.policy import ReactiveThresholdPolicy


@dataclass
class SafeguardState:
    active_mode: str = "ml"  # ml | reactive_fallback
    drift_alarm: bool = False
    rolling_mape: float = 0.0
    headroom_mult: float = 1.0
    safety_net_triggered: bool = False
    fallback_since: float | None = None
    recoveries: int = 0


class ForecastErrorTracker:
    """Rolling MAPE tracker over recent forecast errors."""

    def __init__(self, window: int = 30) -> None:
        self.window = window
        self._errors: deque[float] = deque(maxlen=window)

    def update(self, predicted: float, actual: float) -> float:
        denom = max(abs(actual), 1e-6)
        self._errors.append(abs(predicted - actual) / denom)
        return self.mape()

    def mape(self) -> float:
        if not self._errors:
            return 0.0
        return float(sum(self._errors) / len(self._errors))

    def reset(self) -> None:
        self._errors.clear()


class SafeguardedController:
    """Wraps a ControlLoop with safety net + drift detection + confidence headroom.

    Parameters
    ----------
    trigger_utilization:
        Live utilization above this → reactive safety net overrides ML.
    drift_mape_threshold:
        Rolling MAPE above this → drift alarm + fallback to reactive policy.
    recover_mape_threshold:
        Rolling MAPE below this → recover from fallback back to ML.
    base_headroom:
        Headroom used when forecast error is low; widened by ``headroom_mult``.
    """

    def __init__(
        self,
        cfg: AutoscalerConfig | None = None,
        trigger_utilization: float = 0.90,
        drift_mape_threshold: float = 0.30,
        recover_mape_threshold: float = 0.15,
        base_headroom: float = 0.20,
        confidence_gain: float = 1.5,
        window: int = 30,
    ) -> None:
        self.cfg = cfg or AutoscalerConfig()
        self.trigger_utilization = trigger_utilization
        self.drift_mape_threshold = drift_mape_threshold
        self.recover_mape_threshold = recover_mape_threshold
        self.base_headroom = base_headroom
        self.confidence_gain = confidence_gain
        self.tracker = ForecastErrorTracker(window=window)
        self.reactive = ReactiveThresholdPolicy()
        self.state = SafeguardState(headroom_mult=1.0)
        self._loop = ControlLoop(
            AutoscalerConfig(
                min_instances=self.cfg.min_instances,
                max_instances=self.cfg.max_instances,
                capacity_per_instance=self.cfg.capacity_per_instance,
                target_utilization=self.cfg.target_utilization,
                headroom=self.cfg.headroom,
                fast_scale_up_cooldown_s=self.cfg.fast_scale_up_cooldown_s,
                slow_scale_down_cooldown_s=self.cfg.slow_scale_down_cooldown_s,
                hysteresis=self.cfg.hysteresis,
            )
        )

    # ------------------------------------------------------------------ errors
    def observe(self, predicted: float, actual: float) -> float:
        mape = self.tracker.update(predicted, actual)
        self.state.rolling_mape = mape
        # confidence-aware headroom: widen margin when error is high
        self.state.headroom_mult = 1.0 + self.confidence_gain * mape
        # drift alarm + fallback
        if mape > self.drift_mape_threshold:
            if self.state.active_mode == "ml":
                self.state.active_mode = "reactive_fallback"
                self.state.drift_alarm = True
                self.state.fallback_since = self.tracker.mape()
        elif mape < self.recover_mape_threshold and self.state.active_mode == "reactive_fallback":
            self.state.active_mode = "ml"
            self.state.drift_alarm = False
            self.state.recoveries += 1
        return mape

    # --------------------------------------------------------------- decision
    def step(
        self,
        predicted_load_p50: float,
        predicted_load_p90: float,
        current_capacity: float,
        current_utilization: float | None = None,
        current_instances: int | None = None,
        now: float | None = None,
    ) -> ScalingDecision:
        """Compute next desired instances, applying safeguards."""
        cur = current_instances if current_instances is not None else self._loop.state.current_instances
        self._loop.state.current_instances = cur
        ts = now if now is not None else 0.0

        # 1. Reactive safety net: if live utilization is critical, right-size
        #    immediately for the *observed* load rather than nudging by one.
        if current_utilization is not None and current_utilization >= self.trigger_utilization:
            self.state.safety_net_triggered = True
            observed_load = current_utilization * max(current_capacity, 1.0)
            eff = self.cfg.capacity_per_instance * self.cfg.target_utilization
            needed = math.ceil(observed_load * (1.0 + self.base_headroom) / eff) if eff > 0 else cur
            d = max(self.cfg.min_instances, min(self.cfg.max_instances, max(cur, needed)))
            return ScalingDecision(
                desired=d,
                current=cur,
                action="scale_up" if d > cur else "no_change",
                reason=f"safety_net (util={current_utilization:.2f} → {d} inst)",
                ts=ts,
                p50=predicted_load_p50,
                p90=predicted_load_p90,
            )
        self.state.safety_net_triggered = False

        # 2. Confidence-aware headroom: widen the P90 margin
        eff_headroom = min(self.base_headroom * self.state.headroom_mult, 3.0)

        # 3. Fallback mode: use reactive policy instead of ML forecast
        if self.state.active_mode == "reactive_fallback" and current_utilization is not None:
            d = self.reactive.compute_desired(
                current_utilization=current_utilization,
                current_instances=cur,
                min_instances=self.cfg.min_instances,
                max_instances=self.cfg.max_instances,
            )
            return ScalingDecision(
                desired=d,
                current=cur,
                action="scale_up" if d > cur else ("scale_down" if d < cur else "no_change"),
                reason=f"reactive_fallback (mape={self.state.rolling_mape:.2f})",
                ts=ts,
                p50=predicted_load_p50,
                p90=predicted_load_p90,
            )

        # Default: ML predictive with widened headroom
        # Temporarily adjust loop headroom for this step
        orig = self._loop.cfg.headroom
        self._loop.cfg.headroom = eff_headroom
        dec = self._loop.evaluate(
            predicted_load_p50=predicted_load_p50,
            predicted_load_p90=predicted_load_p90,
            current_capacity=current_capacity,
            current_utilization=current_utilization,
            now=now,
        )
        self._loop.cfg.headroom = orig
        return dec
