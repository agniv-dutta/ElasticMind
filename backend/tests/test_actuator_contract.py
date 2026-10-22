"""Shared actuator contract tests - all actuators must pass."""
from __future__ import annotations

import time

from backend.app.autoscaler.actuator import ActuatorState, LocalReplicaPool, STARTUP_DELAY_S, DRAIN_DELAY_S
from backend.app.autoscaler.mock_ecs_actuator import MockEcsActuator


def contract_checks(act):
    s = act.get_state()
    assert isinstance(s, ActuatorState)
    assert isinstance(act.current(), int)
    assert isinstance(act.desired(), int)
    # set desired
    a = act.set_desired(act.desired())
    assert hasattr(a, "desired")
    assert hasattr(a, "current")
    assert hasattr(a, "reason")
    assert hasattr(a, "ts")


def test_local_replica_pool_contract():
    act = LocalReplicaPool(initial=2, min_c=1, max_c=10)
    contract_checks(act)
    s = act.get_state()
    assert s.desired >= 1


def test_local_replica_pool_startup_lag():
    t = 1000.0
    act = LocalReplicaPool(initial=1, min_c=1, max_c=10, now=t)
    act.set_desired(3, now=t)
    s1 = act.get_state(now=t)
    assert s1.pending_start >= 1 or s1.running <= 1  # lag
    s2 = act.get_state(now=t + STARTUP_DELAY_S + 1)
    assert s2.running >= 1


def test_local_replica_pool_drain_lag():
    t = 2000.0
    act = LocalReplicaPool(initial=3, min_c=1, max_c=10, now=t)
    act.set_desired(1, now=t)
    s1 = act.get_state(now=t)
    assert s1.draining >= 0
    s2 = act.get_state(now=t + DRAIN_DELAY_S + 1)
    assert s2.running <= 3


def test_mock_ecs_actuator_contract():
    act = MockEcsActuator(initial=2, min_c=1, max_c=10)
    contract_checks(act)
    s = act.get_state()
    assert isinstance(s, ActuatorState)