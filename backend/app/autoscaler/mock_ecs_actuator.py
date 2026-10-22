"""Mock ECS actuator with fake boto3-style client."""
from __future__ import annotations

import time

from backend.app.autoscaler.actuator import ActuatorState, CapacityActuator, ScalingAction, STARTUP_DELAY_S, DRAIN_DELAY_S


class FakeEcsClient:
    def __init__(self, desired_count: int = 2):
        self._desired = desired_count
        self._running = desired_count

    def update_service(self, cluster: str, service: str, desiredCount: int):
        self._desired = int(desiredCount)
        return {"service": {"desiredCount": self._desired}}

    def describe_services(self, cluster: str, service: str):
        return {"services": [{"desiredCount": self._desired, "runningCount": self._running}]}


class MockEcsActuator(CapacityActuator):
    def __init__(self, client: FakeEcsClient | None = None, initial: int = 2, min_c: int = 1, max_c: int = 10, delay_s: float = STARTUP_DELAY_S):
        self._client = client or FakeEcsClient(desired_count=initial)
        self._min = min_c
        self._max = max_c
        self._delay = delay_s
        self._drain_delay = DRAIN_DELAY_S
        self._desired = initial
        self._running = initial
        self._pending = 0
        self._draining = 0
        self._last_action_ts = None
        self.scale_up_cooldown_s = 30
        self.scale_down_cooldown_s = 120

    def get_state(self, now: float | None = None) -> ActuatorState:
        try:
            resp = self._client.describe_services(cluster="c", service="s")
            svc = resp.get("services", [{}])[0]
            self._desired = int(svc.get("desiredCount", self._desired))
            self._running = int(svc.get("runningCount", self._running))
        except Exception:
            pass
        return ActuatorState(desired=self._desired, running=self._running, pending_start=self._pending, draining=self._draining)

    def desired(self) -> int:
        return self._desired

    def current(self) -> int:
        return self._running

    def apply_delay(self, action: ScalingAction) -> float:
        return self._delay

    def set_desired(self, desired: int, now: float | None = None) -> ScalingAction:
        now = now if now is not None else time.time()
        target = max(self._min, min(self._max, int(desired)))
        cur = self._running
        if self._last_action_ts is not None:
            cd = self.scale_up_cooldown_s if target > cur else self.scale_down_cooldown_s
            if now - self._last_action_ts < cd and target != cur:
                return ScalingAction(desired=self._desired, current=cur, reason="cooldown", ts=now)
        try:
            self._client.update_service(cluster="c", service="s", desiredCount=target)
        except Exception:
            pass
        if target >= cur:
            self._pending = max(0, target - cur)
            self._running = target  # simplified for mock parity with tests
        else:
            self._draining = cur - target
            self._running = target
        self._desired = target
        self._last_action_ts = now
        return ScalingAction(desired=target, current=cur, reason=f"ecs_set {cur}->{target}", ts=now)