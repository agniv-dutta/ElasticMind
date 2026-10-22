"""Simulation harness: replay workload trace with provisioning delay.

All computed outputs are **simulated** values. Latency uses a simple queueing
approximation (M/M/c style) to avoid heavy external libraries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from backend.app.core.config import Settings
from backend.app.metrics.calculator import calculate_metrics


@dataclass
class SimConfig:
    provisioning_delay_s: float = field(default_factory=lambda: Settings().scaled_delay(Settings().STARTUP_DELAY_S))
    service_rate: float = field(default_factory=lambda: Settings().CAPACITY_PER_REPLICA_RPM)
    cost_per_instance_hour: float = field(default_factory=lambda: Settings().PRICE_PER_REPLICA_HOUR)
    power_idle_w: float = field(default_factory=lambda: Settings().IDLE_WATTS)
    power_max_w: float = field(default_factory=lambda: Settings().PEAK_WATTS)
    co2_kg_per_kwh: float = 0.417  # carbon intensity (simulated)
    sla_latency_ms: float = field(default_factory=lambda: Settings().SLA_LATENCY_MS)

    @classmethod
    def from_settings(cls, settings: Settings) -> SimConfig:
        return cls(
            provisioning_delay_s=settings.scaled_delay(settings.STARTUP_DELAY_S),
            service_rate=settings.CAPACITY_PER_REPLICA_RPM,
            cost_per_instance_hour=settings.PRICE_PER_REPLICA_HOUR,
            power_idle_w=settings.IDLE_WATTS,
            power_max_w=settings.PEAK_WATTS,
            sla_latency_ms=settings.SLA_LATENCY_MS,
        )


class WorkloadReplaySimulator:
    """Replay 1-minute workload trace against a policy-driven capacity plan."""

    def __init__(self, cfg: SimConfig | None = None) -> None:
        self.cfg = cfg or SimConfig()

    def simulate(
        self,
        trace: pd.DataFrame,
        get_desired_for_row,
        start_capacity: int = 2,
    ) -> pd.DataFrame:
        """Replay ``trace`` (cols: timestamp, requests).

        ``get_desired_for_row(row) -> int`` returns the policy's desired
        instances at that time step (1-min).
        """
        if not {"timestamp", "requests"} <= set(trace.columns):
            raise ValueError("trace must have timestamp and requests")
        d = trace.copy().reset_index(drop=True)
        d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)

        # Capacity lags: effective capacity becomes active after provision delay.
        # Approximate as a delay of 1–2 steps in 1-min simulation by delaying
        # application by ``delay_steps = ceil(provision_delay_s / 60)``.
        delay_steps = int(np.ceil(getattr(self.cfg, "provisioning_delay_s", Settings().scaled_delay(Settings().STARTUP_DELAY_S)) / 60.0))
        desired_hist = []
        for i, row in d.iterrows():
            try:
                desired_hist.append(int(get_desired_for_row(row, i)))
            except Exception:
                desired_hist.append(start_capacity)

        desired = np.array(desired_hist, dtype=float)
        if delay_steps > 0:
            effective = np.roll(desired, delay_steps)
            effective[:delay_steps] = start_capacity
        else:
            effective = desired

        effective = np.clip(effective, 1.0, None).astype(float)
        demand = d["requests"].astype(float).to_numpy()

        # Metrics (simulated)
        total_capacity = effective * self.cfg.service_rate  # req/min total
        rows = [calculate_metrics(
            demand=float(load), served_load=float(load), running_replicas=float(replicas),
            capacity_per_replica=self.cfg.service_rate, service_rate=self.cfg.service_rate,
            latency_sla_ms=self.cfg.sla_latency_ms,
            billed_replica_seconds=max(float(replicas), float(desired_count)) * 60.0,
            billed_replica_count=max(float(replicas), float(desired_count)),
            price_per_second=self.cfg.cost_per_instance_hour / 3600.0,
            dt_seconds=60.0, idle_w=self.cfg.power_idle_w, peak_w=self.cfg.power_max_w,
        ) for load, replicas, desired_count in zip(demand, effective, desired)]
        util = np.array([m.utilization for m in rows])
        sim_latency = np.array([m.latency_ms for m in rows])
        sla_violations = np.array([m.sla_violations for m in rows])
        instance_hours = np.maximum(effective, desired) / 60.0
        cost = np.array([m.cost_usd for m in rows])
        energy_kwh = np.array([m.energy_kwh_estimated for m in rows])
        co2_kg = energy_kwh * self.cfg.co2_kg_per_kwh

        out = d[["timestamp"]].copy()
        out["demand_req_min"] = demand
        out["desired_instances"] = desired
        out["effective_instances"] = effective
        out["total_capacity_req_min"] = total_capacity
        out["utilization"] = util
        out["sla_violation"] = sla_violations
        out["sim_latency_ms"] = np.round(sim_latency, 2)
        out["instance_hours"] = instance_hours
        out["cost_usd"] = cost
        out["energy_kwh"] = energy_kwh
        out["co2_kg"] = co2_kg
        return out


def summarize_simulation(res: pd.DataFrame) -> dict:
    """Aggregate metrics over the simulation horizon."""
    util = res["utilization"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return {
        "total_minutes": len(res),
        "avg_utilization": float(util.mean()),
        "p90_utilization": float(util.quantile(0.90)),
        "sla_violations_total": int(res["sla_violation"].sum()),
        "sla_violation_rate": float(res["sla_violation"].mean() * 100.0),
        "avg_latency_ms": float(res["sim_latency_ms"].mean()),
        "p90_latency_ms": float(res["sim_latency_ms"].quantile(0.90)),
        "total_cost_usd": float(res["cost_usd"].sum()),
        "total_energy_kwh": float(res["energy_kwh"].sum()),
        "total_co2_kg": float(res["co2_kg"].sum()),
        "over_provisioning_waste_%": float(
            max(0.0, (res["effective_instances"].sum() - max(1.0, res["sla_violation"].sum())) / max(1, len(res)) * 0.0)
        ),  # simple placeholder
    }
