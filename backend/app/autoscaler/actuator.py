"""Capacity actuator interface and a local simulator actuator."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from time import time
from backend.app.core.config import Settings


@dataclass
class ScalingAction:
    desired: int
    current: int
    reason: str
    ts: float


class CapacityActuator(abc.ABC):
    @abc.abstractmethod
    def desired(self) -> int: ...

    @abc.abstractmethod
    def set_desired(self, desired: int) -> ScalingAction: ...

    @abc.abstractmethod
    def current(self) -> int: ...

    @abc.abstractmethod
    def apply_delay(self, action: ScalingAction) -> float: ...


class LocalSimActuator(CapacityActuator):
    """In-memory actuator used for local simulation.

    ``provision_delay_s`` is the time until the new capacity becomes effective
    in the simulated environment (measured/handled by the simulator), but the
    actuator itself records the decision timestamp.
    """

    def __init__(self, initial: int | None = None, min_c: int | None = None, max_c: int | None = None,
                 startup_delay_s: float | None = None, drain_delay_s: float | None = None,
                 delay_s: float | None = None) -> None:
        settings = Settings()
        min_c = settings.MIN_REPLICAS if min_c is None else min_c
        max_c = settings.MAX_REPLICAS if max_c is None else max_c
        initial = min_c if initial is None else initial
        self._current = max(min_c, min(max_c, initial))
        self._min = min_c
        self._max = max_c
        self._startup_delay = settings.scaled_delay(settings.STARTUP_DELAY_S) if startup_delay_s is None else startup_delay_s
        self._drain_delay = settings.scaled_delay(settings.DRAIN_DELAY_S) if drain_delay_s is None else drain_delay_s
        if delay_s is not None:
            self._startup_delay = self._drain_delay = delay_s
        self._last_action_ts: float | None = None

    def desired(self) -> int:
        return self._current

    def current(self) -> int:
        return self._current

    def set_desired(self, desired: int, force: bool = False) -> ScalingAction:
        d = max(self._min, min(self._max, int(desired)))
        action = ScalingAction(desired=d, current=self._current, reason="actuator_set", ts=time())
        self._last_action_ts = action.ts
        self._current = d
        return action

    def apply_delay(self, action: ScalingAction) -> float:
        return self._startup_delay if action.desired > action.current else self._drain_delay
