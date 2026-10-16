"""Control loop implementing cooldowns, hysteresis, and state tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.policy import MLForecastPolicy, PredictivePolicyInput


@dataclass
class ScalingDecision:
    desired: int
    current: int
    action: str  # "scale_up" | "scale_down" | "no_change"
    reason: str
    ts: float
    p50: float = 0.0
    p90: float = 0.0


@dataclass
class ControlState:
    current_instances: int
    last_scale_ts: float = 0.0
    last_scale_up_ts: float = 0.0
    last_scale_down_ts: float = 0.0
    last_reason: str = "initial"
    in_cooldown: bool = False


class ControlLoop:
    """Stateful control loop that applies cooldowns and hysteresis.

    Cooldown behavior: use ``fast_scale_up_cooldown_s`` after scale-up, and
    ``slow_scale_down_cooldown_s`` after scale-down (as required). The loop also
    avoids flapping via the ``hysteresis`` margin.
    """

    def __init__(self, cfg: AutoscalerConfig | None = None) -> None:
        self.cfg = cfg or AutoscalerConfig()
        self.state = ControlState(current_instances=self.cfg.min_instances)
        self.policy = MLForecastPolicy()

    def reset(self, current_instances: int) -> None:
        self.state = ControlState(
            current_instances=max(self.cfg.min_instances, min(self.cfg.max_instances, current_instances))
        )

    def _now(self) -> float:
        return time.time()

    def evaluate(
        self,
        predicted_load_p50: float,
        predicted_load_p90: float,
        current_capacity: float,
        current_utilization: float | None = None,
        now: float | None = None,
    ) -> ScalingDecision:
        """Compute the next desired count given forecasts.

        ``now`` overrides the wall-clock timestamp — used by offline simulations
        so cooldowns are evaluated against a virtual clock (one step = 60 s).
        """
        inp = PredictivePolicyInput(
            predicted_load_p50=max(predicted_load_p50, 0.0),
            predicted_load_p90=max(predicted_load_p90, 0.0),
            current_capacity=max(current_capacity, 1.0),
            target_utilization=self.cfg.target_utilization,
            headroom=self.cfg.headroom,
            min_instances=self.cfg.min_instances,
            max_instances=self.cfg.max_instances,
            capacity_per_instance=self.cfg.capacity_per_instance,
        )
        desired = self.policy.compute_desired(**inp.__dict__)

        cur = self.state.current_instances
        now = now if now is not None else self._now()
        elapsed = now - self.state.last_scale_ts

        if desired > cur:
            cd = self.cfg.fast_scale_up_cooldown_s
            action = "scale_up"
        elif desired < cur:
            cd = self.cfg.slow_scale_down_cooldown_s
            action = "scale_down"
        else:
            cd = max(self.cfg.slow_scale_down_cooldown_s, self.cfg.fast_scale_up_cooldown_s)

        # Cooldown: prevent another scaling action until cooldown expires.
        in_cd = elapsed < cd and self.state.last_scale_ts > 0.0
        if in_cd and desired != cur:
            return ScalingDecision(
                desired=cur,
                current=cur,
                action="no_change",
                reason=f"cooldown_{action} ({int(cd - elapsed)}s left)",
                ts=now,
                p50=inp.predicted_load_p50,
                p90=inp.predicted_load_p90,
            )

        # Hysteresis: avoid flapping when change is small relative to capacity.
        if desired != cur:
            cap_per_inst = self.cfg.capacity_per_instance
            threshold = cap_per_inst * self.cfg.hysteresis
            if action == "scale_up" and desired - cur == 1:
                need_increase = inp.predicted_load_p90 - (cur * cap_per_inst * self.cfg.target_utilization)
                if need_increase < threshold:
                    return ScalingDecision(
                        desired=cur,
                        current=cur,
                        action="no_change",
                        reason=f"hysteresis_up (need<{threshold:.0f})",
                        ts=now,
                        p50=inp.predicted_load_p50,
                        p90=inp.predicted_load_p90,
                    )
            if action == "scale_down" and cur - desired == 1:
                excess = (cur * cap_per_inst * self.cfg.target_utilization) - inp.predicted_load_p90
                if excess < threshold * 0.5:
                    return ScalingDecision(
                        desired=cur,
                        current=cur,
                        action="no_change",
                        reason=f"hysteresis_down (excess<{threshold*0.5:.0f})",
                        ts=now,
                        p50=inp.predicted_load_p50,
                        p90=inp.predicted_load_p90,
                    )

        if desired == cur:
            reason = "no_change (within bounds)"
        else:
            reason = f"{action} d={desired} c={cur}"

        if desired != cur:
            self.state.current_instances = desired
            self.state.last_scale_ts = now
            if action == "scale_up":
                self.state.last_scale_up_ts = now
            if action == "scale_down":
                self.state.last_scale_down_ts = now
            self.state.last_reason = reason

        return ScalingDecision(
            desired=desired,
            current=cur,
            action=action if desired != cur else "no_change",
            reason=self.state.last_reason,
            ts=now,
            p50=inp.predicted_load_p50,
            p90=inp.predicted_load_p90,
        )
