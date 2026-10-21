"""Scripted misprediction scenarios (Prompt 9).

For each scenario — over-predict +50%, under-predict -50%, unseen sudden
spike — we replay a workload with and without safeguards and report
SLA violations, cost, recovery time and over-provisioning waste.

All outputs are **simulated**.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.core.config import Settings
from backend.app.robustness.safeguards import SafeguardedController
from backend.app.simulator.simulator import SimConfig, WorkloadReplaySimulator, summarize_simulation
from ml.data.generate import generate_workload

SCENARIOS = ("over_predict_50", "under_predict_50", "sudden_spike")


def _scenario_trace(name: str) -> pd.DataFrame:
    if name == "sudden_spike":
        from ml.data.generate import WorkloadEvent

        return generate_workload(
            profile="diurnal",
            days=2,
            seed=7,
            events=[WorkloadEvent("flash_spike", start_minute=2100, duration_minutes=90, magnitude=3.0)],
        )
    return generate_workload(profile="diurnal", days=2, seed=7)


def _biased_forecast_series(demand: np.ndarray, scenario: str) -> np.ndarray:
    """Return the naive forecast the controller sees for this scenario."""
    if scenario == "over_predict_50":
        return demand * 1.5
    if scenario == "under_predict_50":
        return demand * 0.5
    # sudden_spike: persistence forecast (uses previous value) — blind to the spike
    f = demand.copy()
    f[1:] = demand[:-1]
    return f


def run_scenario(
    scenario: str,
    safeguards: bool,
    trace: pd.DataFrame,
    cfg: AutoscalerConfig | None = None,
) -> dict:
    settings = Settings()
    cfg = cfg or AutoscalerConfig.from_settings(settings)
    sim_cfg = SimConfig.from_settings(settings)

    if safeguards:
        ctl = SafeguardedController(cfg=cfg, base_headroom=cfg.headroom)
    else:
        from backend.app.autoscaler.control import ControlLoop

        class _Plain:
            def __init__(self):
                self.loop = ControlLoop(cfg)
                self.loop.reset(cfg.min_instances)

        plain = _Plain()
    instances = cfg.min_instances
    desired_series: list[int] = []
    demand = trace["requests"].to_numpy(dtype=float)
    forecast_series = _biased_forecast_series(demand, scenario)

    for i in range(len(demand)):
        actual = float(demand[i])
        pred = float(forecast_series[i])
        util_now = actual / max(instances * cfg.capacity_per_instance, 1e-6)
        cap = instances * cfg.capacity_per_instance
        virtual_now = float(i) * 60.0  # virtual clock: one step = 60 s
        if safeguards:
            ctl.observe(pred, actual)
            dec = ctl.step(
                predicted_load_p50=pred,
                predicted_load_p90=pred * 1.1,
                current_capacity=cap,
                current_utilization=util_now,
                current_instances=instances,
                now=virtual_now,
            )
        else:
            dec = plain.loop.evaluate(
                predicted_load_p50=pred,
                predicted_load_p90=pred * 1.1,
                current_capacity=cap,
                current_utilization=util_now,
                now=virtual_now,
            )
        instances = dec.desired
        desired_series.append(instances)

    # Simulate
    sim = WorkloadReplaySimulator(sim_cfg).simulate(
        trace,
        lambda row, i: desired_series[i],
        start_capacity=desired_series[0] if desired_series else cfg.min_instances,
    )
    summary = summarize_simulation(sim)

    # Recovery time: minutes to get within 10% of oracle demand capacity after worst violation
    oracle_need = demand * 1.1 / (cfg.capacity_per_instance * cfg.target_utilization)
    oracle_need = np.clip(oracle_need, cfg.min_instances, cfg.max_instances)
    recovery = 0
    for i in range(len(desired_series) - 1, -1, -1):
        if abs(desired_series[i] - oracle_need[i]) > max(1, 0.1 * oracle_need[i]):
            recovery = len(desired_series) - i
            break

    # Over-provisioning waste: extra instances above need while no SLA violation occurred
    waste = float(np.sum(np.maximum(0, np.array(desired_series) - oracle_need)) / max(len(desired_series), 1))

    out = {
        "scenario": scenario,
        "safeguards": safeguards,
        "sla_violations": summary["sla_violations_total"],
        "sla_rate_%": round(summary["sla_violation_rate"], 2),
        "cost_usd": round(summary["total_cost_usd"], 4),
        "avg_utilization": round(summary["avg_utilization"], 3),
        "recovery_time_min": int(recovery),
        "over_provision_waste_inst_per_min": round(waste, 3),
        "simulated": True,
    }
    return out


def run_all(out_dir: Path = Path("experiments/results")) -> pd.DataFrame:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for sc in SCENARIOS:
        trace = _scenario_trace(sc)
        for sg in (False, True):
            rows.append(run_scenario(sc, safeguards=sg, trace=trace))
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "misprediction_scenarios.csv", index=False)

    # chart: SLA violations by scenario with/without safeguards
    fig, ax = plt.subplots(figsize=(9, 4))
    for sg, color, label in ((False, "#f87171", "no safeguards"), (True, "#5eead4", "with safeguards")):
        sub = df[df["safeguards"] == sg]
        ax.bar(
            [f"{s}\n{'+sg' if sg else '-sg'}" for s in sub["scenario"]],
            sub["sla_violations"],
            color=color,
            label=label,
        )
    ax.set_ylabel("SLA violations (simulated)")
    ax.set_title("Misprediction scenarios — simulated SLA violations")
    ax.legend()
    plt.tight_layout()
    fig.savefig(out_dir / "misprediction_scenarios.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return df


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run misprediction robustness scenarios")
    p.add_argument("--out", default="experiments/results")
    args = p.parse_args(argv)
    df = run_all(Path(args.out))
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
