"""Single source of truth for utilization, SLA, latency, cost, and energy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricValues:
    utilization: float
    sla_violations: int
    latency_ms: float
    cost_usd: float
    energy_kwh_estimated: float


def utilization(served_load: float, running_replicas: float, capacity_per_replica: float) -> float:
    """Return served load divided by running replica capacity; may exceed 1 under overload."""
    capacity = running_replicas * capacity_per_replica
    return max(0.0, served_load) / capacity if capacity > 0 else 0.0


def latency_ms(demand: float, running_replicas: float, service_rate: float) -> float:
    """Simulated M/M/c-style latency approximation used by workload replay."""
    if service_rate <= 0 or running_replicas <= 0:
        return 0.0
    rho = min(max(demand / (running_replicas * service_rate), 0.0), 0.999)
    waiting_factor = rho / (1.0 - rho)
    return max((1.0 / service_rate) * (1.0 + waiting_factor / (running_replicas + 1e-6)), 1.0)


def sla_violations(demand: float, total_capacity: float, latency: float, latency_sla_ms: float) -> int:
    """One binary violation per interval when demand exceeds capacity or latency SLO."""
    return int(demand > total_capacity or latency > latency_sla_ms)


def cost_usd(replica_seconds: float, price_per_second: float) -> float:
    """Cost for all billed replica-seconds, including starting and draining replicas."""
    return max(0.0, replica_seconds) * max(0.0, price_per_second)


def energy_kwh_estimated(
    utilization_value: float,
    replica_count: float,
    dt_seconds: float,
    idle_w: float,
    peak_w: float,
) -> float:
    """Estimated energy, with linear power interpolation and watts converted to kWh."""
    util = min(max(utilization_value, 0.0), 1.0)
    watts = max(0.0, idle_w) + (max(0.0, peak_w) - max(0.0, idle_w)) * util
    return max(0.0, replica_count) * watts * max(0.0, dt_seconds) / 3_600_000.0


def calculate_metrics(
    *, demand: float, served_load: float, running_replicas: float,
    capacity_per_replica: float, service_rate: float, latency_sla_ms: float,
    billed_replica_seconds: float, price_per_second: float, dt_seconds: float,
    idle_w: float, peak_w: float, measured_latency_ms: float | None = None,
    billed_replica_count: float | None = None,
) -> MetricValues:
    util = utilization(served_load, running_replicas, capacity_per_replica)
    latency = measured_latency_ms if measured_latency_ms is not None else latency_ms(demand, running_replicas, service_rate)
    capacity = running_replicas * capacity_per_replica
    return MetricValues(
        utilization=util,
        sla_violations=sla_violations(demand, capacity, latency, latency_sla_ms),
        latency_ms=float(latency),
        cost_usd=cost_usd(billed_replica_seconds, price_per_second),
        energy_kwh_estimated=energy_kwh_estimated(
            util, running_replicas if billed_replica_count is None else billed_replica_count,
            dt_seconds, idle_w, peak_w,
        ),
    )
