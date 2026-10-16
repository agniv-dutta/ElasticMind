"""Capacity actuator interface and a local simulator actuator."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from time import time


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

    def __init__(self, initial: int = 2, min_c: int = 1, max_c: int = 10, delay_s: float = 90.0) -> None:
        self._current = max(min_c, min(max_c, initial))
        self._min = min_c
        self._max = max_c
        self._delay = delay_s
        self._last_action_ts: float | None = None

    def desired(self) -> int:
        return self._current

    def current(self) -> int:
        return self._current

    def set_desired(self, desired: int) -> ScalingAction:
        d = max(self._min, min(self._max, int(desired)))
        action = ScalingAction(desired=d, current=self._current, reason="actuator_set", ts=time())
        self._last_action_ts = action.ts
        self._current = d
        return action

    def apply_delay(self, action: ScalingAction) -> float:
        return self._delay
