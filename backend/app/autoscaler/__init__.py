"""Autoscaling engine: control loop, policies, actuators."""

from backend.app.autoscaler.actuator import (
    CapacityActuator,
    LocalSimActuator,
    ScalingAction,
)
from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop, ControlState, ScalingDecision
from backend.app.autoscaler.policy import (
    MLForecastPolicy,
    PredictivePolicyInput,
    ReactiveThresholdPolicy,
    StaticPolicy,
)

__all__ = [
    "AutoscalerConfig",
    "CapacityActuator",
    "ControlLoop",
    "ControlState",
    "LocalSimActuator",
    "MLForecastPolicy",
    "PredictivePolicyInput",
    "ReactiveThresholdPolicy",
    "ScalingAction",
    "ScalingDecision",
    "StaticPolicy",
]
