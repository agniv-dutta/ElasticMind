"""Capacity actuator interface and implementations (replica-pool model)."""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass


@dataclass
class ScalingAction:
    desired: int
    current: int
    reason: str
    ts: float


@dataclass
class ActuatorState:
    desired: int
    running: int
    pending_start: int = 0
    draining: int = 0


class CapacityActuator(abc.ABC):
    @abc.abstractmethod
    def set_desired(self, desired: int) -> ScalingAction: ...

    @abc.abstractmethod
    def get_state(self) -> ActuatorState: ...

    @abc.abstractmethod
    def current(self) -> int: ...

    @abc.abstractmethod
    def desired(self) -> int: ...

    @abc.abstractmethod
    def apply_delay(self, action: ScalingAction) -> float: ...


STARTUP_DELAY_S = 30.0
DRAIN_DELAY_S = 60.0


class Replica:
    def __init__(self, rid: int, now: float) -> None:
        self.rid = rid
        self.state = "STARTING"
        self.start_ts = now
        self.drain_ts = None


class LocalReplicaPool(CapacityActuator):
    def __init__(self, initial: int = 2, min_c: int = 1, max_c: int = 10, delay_s: float = STARTUP_DELAY_S, now: float | None = None):
        self._min = min_c
        self._max = max_c
        self._delay = delay_s
        self._drain_delay = DRAIN_DELAY_S
        t = now if now is not None else time.time()
        self._desired = max(min_c, min(max_c, initial))
        self._replicas = []
        for i in range(self._desired):
            r = Replica(i, t)
            r.state = "RUNNING"
            self._replicas.append(r)
        self._next_id = len(self._replicas)
        self._last_action_ts = None
        self.scale_up_cooldown_s = 30
        self.scale_down_cooldown_s = 120

    def _tick(self, now: float) -> None:
        for r in self._replicas:
            if r.state == "STARTING" and now - r.start_ts >= self._delay:
                r.state = "RUNNING"
            if r.state == "DRAINING" and r.drain_ts is not None and now - r.drain_ts >= self._drain_delay:
                r.state = "STOPPED"
        self._replicas = [r for r in self._replicas if r.state != "STOPPED"]

    def _count(self, now: float):
        self._tick(now)
        running = sum(1 for r in self._replicas if r.state == "RUNNING")
        pending = sum(1 for r in self._replicas if r.state == "STARTING")
        draining = sum(1 for r in self._replicas if r.state == "DRAINING")
        return running, pending, draining

    def get_state(self, now: float | None = None) -> ActuatorState:
        now = now if now is not None else time.time()
        running, pending, draining = self._count(now)
        return ActuatorState(desired=self._desired, running=running, pending_start=pending, draining=draining)

    def desired(self) -> int:
        return self._desired

    def current(self, now: float | None = None) -> int:
        return self._desired

    def apply_delay(self, action: ScalingAction) -> float:
        return self._delay

    def set_desired(self, desired: int, now: float | None = None, force: bool = False) -> ScalingAction:
        now = now if now is not None else time.time()
        target = max(self._min, min(self._max, int(desired)))
        self._tick(now)
        cur = self.current(now)
        if self._last_action_ts is not None and not force:
            cd = self.scale_up_cooldown_s if target > cur else self.scale_down_cooldown_s
            if now - self._last_action_ts < cd and target != cur:
                return ScalingAction(desired=self._desired, current=cur, reason="cooldown", ts=now)
        if target > cur:
            to_add = target - cur - sum(1 for r in self._replicas if r.state == "STARTING")
            for i in range(max(0, to_add)):
                self._replicas.append(Replica(self._next_id, now))
                self._next_id += 1
            self._last_action_ts = now
            self._desired = target
            return ScalingAction(desired=target, current=cur, reason=f"scale_up {cur}->{target}", ts=now)
        if target < cur:
            need_drain = cur - target
            for r in list(self._replicas):
                if need_drain <= 0:
                    break
                if r.state == "RUNNING":
                    r.state = "DRAINING"
                    r.drain_ts = now
                    need_drain -= 1
            self._last_action_ts = now
            self._desired = target
            return ScalingAction(desired=target, current=cur, reason=f"scale_down {cur}->{target}", ts=now)
        self._desired = target
        return ScalingAction(desired=target, current=cur, reason="no_change", ts=now)


LocalSimActuator = LocalReplicaPool
