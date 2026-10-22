"""AwsEcsActuator (stub with TODOs only per requirement)."""
from __future__ import annotations

from backend.app.autoscaler.actuator import ActuatorState, CapacityActuator, ScalingAction


class AwsEcsActuator(CapacityActuator):
    def __init__(self, *args, **kwargs) -> None:
        # TODO: use real boto3 ECS client
        self._desired = 1
        self._running = 1

    def set_desired(self, desired: int) -> ScalingAction:
        # TODO: call ecs.update_service
        raise NotImplementedError("AwsEcsActuator not implemented; use MockEcsActuator or LocalReplicaPool")

    def get_state(self) -> ActuatorState:
        # TODO: call ecs.describe_services
        return ActuatorState(desired=self._desired, running=self._running)

    def current(self) -> int:
        return self._running

    def desired(self) -> int:
        return self._desired

    def apply_delay(self, action: ScalingAction) -> float:
        return 30.0