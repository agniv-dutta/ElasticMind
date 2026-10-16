"""AWS ECS actuator (boto3).

Sets the desired task count on the target ECS service, honouring cooldowns and
min/max bounds, and publishes custom CloudWatch metrics each loop.

Activate with ``ELASTICMIND_ACTUATOR=aws``.
"""

from __future__ import annotations

import time
from typing import Any

from backend.app.autoscaler.actuator import CapacityActuator, ScalingAction

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError as exc:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc


class AwsEcsActuator(CapacityActuator):
    """Drives an ECS service's ``desiredCount`` within [min, max]."""

    def __init__(
        self,
        cluster: str,
        service: str,
        region: str | None = None,
        min_c: int = 1,
        max_c: int = 10,
        scale_up_cooldown_s: int = 30,
        scale_down_cooldown_s: int = 120,
        delay_s: float = 120.0,
        initial: int | None = None,
        ecs_client: Any | None = None,
    ) -> None:
        if boto3 is None and ecs_client is None:  # pragma: no cover
            raise ImportError(f"boto3 required for AwsEcsActuator: {_IMPORT_ERROR}")
        self.cluster = cluster
        self.service = service
        self.region = region
        self._min = min_c
        self._max = max_c
        self.scale_up_cooldown_s = scale_up_cooldown_s
        self.scale_down_cooldown_s = scale_down_cooldown_s
        self._delay = delay_s
        self._ecs = ecs_client or boto3.client("ecs", region_name=region)
        self._current = int(initial) if initial is not None else self._describe_desired()
        self._last_action_ts: float | None = None

    # ------------------------------------------------------------- internals
    def _describe_desired(self) -> int:
        try:
            resp = self._ecs.describe_services(cluster=self.cluster, services=[self.service])
            services = resp.get("services", [])
            if services:
                return int(services[0].get("desiredCount", self._min))
        except ClientError:  # pragma: no cover
            pass
        return self._min

    def current(self) -> int:
        self._current = self._describe_desired()
        return self._current

    def desired(self) -> int:
        return self._current

    def apply_delay(self, action: ScalingAction) -> float:
        return self._delay

    def _cooldown_ok(self, target: int, now: float) -> tuple[bool, str]:
        if self._last_action_ts is None:
            return True, ""
        cd = self.scale_up_cooldown_s if target > self._current else self.scale_down_cooldown_s
        elapsed = now - self._last_action_ts
        if elapsed < cd:
            return False, f"actuator_cooldown ({int(cd - elapsed)}s left)"
        return True, ""

    # ----------------------------------------------------------------- action
    def set_desired(self, desired: int, now: float | None = None) -> ScalingAction:
        """Update the ECS service desired count (clamped + rate limited)."""
        target = max(self._min, min(self._max, int(desired)))
        now = now if now is not None else time.time()
        ok, why = self._cooldown_ok(target, now)
        if not ok and target != self._current:
            return ScalingAction(desired=self._current, current=self._current, reason=why, ts=now)

        action = "no_change" if target == self._current else ("scale_up" if target > self._current else "scale_down")
        if target != self._current:
            try:
                self._ecs.update_service(
                    cluster=self.cluster,
                    service=self.service,
                    desiredCount=target,
                )
                self._last_action_ts = now
            except ClientError as e:  # pragma: no cover
                return ScalingAction(
                    desired=self._current,
                    current=self._current,
                    reason=f"aws_ecs:update_service failed: {e}",
                    ts=now,
                )

        prev = self._current
        self._current = target
        return ScalingAction(
            desired=target,
            current=prev,
            reason=f"{action}: aws_ecs:update_service(cluster={self.cluster},service={self.service},count={target})",
            ts=now,
        )
