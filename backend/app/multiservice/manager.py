"""Multi-service/shared capacity budget (simulated)."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class ServiceState:
    name: str
    desired: int = 1
    weight: float = 1.0
    memory_mb_per_instance: int = 512
    desired_memory_mb: int = 0


class SharedCapacityManager:
    def __init__(self, total_instances: int = 10) -> None:
        self.total = total_instances
        self.services: list[ServiceState] = []

    def add_service(self, s: ServiceState) -> None:
        self.services.append(s)

    def allocate(self) -> dict:
        if not self.services:
            return {}
        if self.total < len(self.services):
            raise ValueError("total capacity must provide at least one instance per service")
        total_w = sum(max(0.0, x.weight) for x in self.services)
        if total_w <= 0:
            total_w = float(len(self.services))
        remaining = self.total - len(self.services)
        shares = [remaining * max(0.0, s.weight) / total_w for s in self.services]
        allocations = [1 + math.floor(share) for share in shares]
        leftover = self.total - sum(allocations)
        for _, i in sorted(
            ((share - math.floor(share), i) for i, share in enumerate(shares)),
            reverse=True,
        )[:leftover]:
            allocations[i] += 1
        for s, allocation in zip(self.services, allocations, strict=True):
            s.desired = allocation
            s.desired_memory_mb = allocation * s.memory_mb_per_instance
        return {s.name: s.desired for s in self.services}