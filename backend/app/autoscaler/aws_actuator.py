"""AwsEcsActuator (stub with TODOs only per requirement)."""
from __future__ import annotations

from backend.app.autoscaler.actuator import ActuatorState, CapacityActuator, ScalingAction
import time


class AwsEcsActuator(CapacityActuator):
    def __init__(self, *args, **kwargs) -> None:
        import boto3
        self.cluster = kwargs.get("cluster", "default")
        self.service = kwargs.get("service", "default")
        self._min = int(kwargs.get("min_c", 1))
        self._max = int(kwargs.get("max_c", 10))
        self._up_cd = float(kwargs.get("scale_up_cooldown_s", 30))
        self._down_cd = float(kwargs.get("scale_down_cooldown_s", 120))
        self._last_action_ts = None
        self._ecs = kwargs.get("client") or boto3.client("ecs", region_name=kwargs.get("region", "us-east-1"))
        self._desired = self._running = self._min
        self._refresh()

    def _refresh(self):
        try:
            services = self._ecs.describe_services(cluster=self.cluster, services=[self.service]).get("services", [])
            if services:
                self._desired = int(services[0].get("desiredCount", self._desired))
                self._running = int(services[0].get("runningCount", self._running)) or self._desired
        except Exception:
            pass

    def set_desired(self, desired: int, now: float | None = None, force: bool = False) -> ScalingAction:
        now = time.time() if now is None else now
        self._refresh()
        current = self._running
        target = max(self._min, min(self._max, int(desired)))
        if self._last_action_ts is not None and not force and target != current:
            cooldown = self._up_cd if target > current else self._down_cd
            if now - self._last_action_ts < cooldown:
                return ScalingAction(self._desired, current, "cooldown", now)
        self._ecs.update_service(cluster=self.cluster, service=self.service, desiredCount=target)
        self._desired = target
        self._last_action_ts = now
        return ScalingAction(target, current, f"ecs_set {current}->{target}", now)

    def get_state(self) -> ActuatorState:
        self._refresh()
        return ActuatorState(desired=self._desired, running=self._running)

    def current(self) -> int:
        self._refresh()
        return self._running

    def desired(self) -> int:
        self._refresh()
        return self._desired

    def apply_delay(self, action: ScalingAction) -> float:
        return 30.0
