"""Experiments runner: compare policies and export CSV/PNG to experiments/results.

Labels everything as **simulated**.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backend.app.autoscaler.config import AutoscalerConfig
from backend.app.autoscaler.control import ControlLoop
from backend.app.core.config import Settings
from backend.app.simulator.simulator import SimConfig, WorkloadReplaySimulator, summarize_simulation
from ml.models.registry import load_predictor


def _load_trace(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".csv":
        df = pd.read_csv(p)
    else:
        df = pd.read_parquet(p)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def _oracle_desired(trace: pd.DataFrame, cfg: AutoscalerConfig, horizon: int = 0) -> list[int]:
    """Oracle knows the actual demand at each step (upper bound)."""
    d = trace["requests"].astype(float)
    eff = cfg.capacity_per_instance * cfg.target_utilization * (1.0 + cfg.headroom)
    if eff <= 0:
        eff = 1.0
    out = []
    for i in range(len(d)):
        inst = max(cfg.min_instances, min(cfg.max_instances, int(np.ceil(d.iloc[i] * 1.1 / eff))))
        out.append(inst)
    return out


class StaticRunner:
    def __init__(self, fixed: int = 3) -> None:
        self.fixed = fixed

    def desired(self, trace: pd.DataFrame) -> list[int]:
        return [self.fixed] * len(trace)


class ReactiveRunner:
    def __init__(self, cfg: AutoscalerConfig, step_util_window: int = 5) -> None:
        self.cfg = cfg
        self.window = step_util_window

    def desired(self, trace: pd.DataFrame) -> list[int]:
        # Naive reactive using a rolling mean of recent demand as "observed"
        d = trace["requests"].astype(float)
        loop = ControlLoop(self.cfg)
        loop.reset(self.cfg.min_instances)
        res = []
        for i in range(len(d)):
            hist = d.iloc[max(0, i - self.window): i + 1]
            cur_util = float(hist.mean()) / (loop.state.current_instances * self.cfg.capacity_per_instance) if loop.state.current_instances > 0 else 0
            # approximate current capacity level
            dec = loop.evaluate(predicted_load_p50=d.iloc[i], predicted_load_p90=d.iloc[i] * 1.1,
                                current_capacity=loop.state.current_instances * self.cfg.capacity_per_instance,
                                current_utilization=cur_util)
            res.append(dec.desired)
        return res


class MLPredictiveRunner:
    def __init__(self, model_path: str | Path, cfg: AutoscalerConfig) -> None:
        self.model = load_predictor(model_path)
        self.cfg = cfg

    def desired(self, trace: pd.DataFrame) -> list[int]:
        loop = ControlLoop(self.cfg)
        loop.reset(self.cfg.min_instances)
        res = []
        # Forecast using a rolling window: keep last 240 min (or end)
        hist_all = trace[["timestamp", "requests"]].copy()
        for i in range(len(hist_all)):
            hist = hist_all.iloc[: i + 1]
            if len(hist) < 60:
                fc = self.model.predict(hist.tail(120))
            else:
                fc = self.model.predict(hist.tail(480))
            p50, p90 = fc.latest(max(self.model.horizons) if hasattr(self.model, "horizons") else 15)
            dec = loop.evaluate(predicted_load_p50=p50, predicted_load_p90=p90,
                                current_capacity=loop.state.current_instances * self.cfg.capacity_per_instance)
            res.append(dec.desired)
        return res


def plot_comparison(results_dir: Path, policy: str, sim: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    ax[0].plot(sim["timestamp"], sim["demand_req_min"], label="demand (simulated)")
    ax[0].plot(sim["timestamp"], sim["total_capacity_req_min"], label="capacity (simulated)")
    ax[0].set_ylabel("req/min")
    ax[0].legend(loc="best")
    ax[0].set_title(f"{policy} — simulated demand vs capacity")
    ax[1].plot(sim["timestamp"], sim["utilization"], color="tab:orange")
    ax[1].axhline(0.7, ls="--", color="gray", label="target 70%")
    ax[1].set_ylabel("utilization (sim)")
    ax[1].legend(loc="best")
    ax[2].plot(sim["timestamp"], sim["sla_violation"].cumsum(), color="tab:red")
    ax[2].set_ylabel("cum SLA violations (sim)")
    ax[2].set_xlabel("time")
    plt.tight_layout()
    out = results_dir / f"{policy}_simulated.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def run_all(trace_path: str | Path, out_dir: Path = Path("experiments/results")) -> pd.DataFrame:
    settings = Settings()
    trace = _load_trace(trace_path)
    cfg = AutoscalerConfig.from_settings(settings)
    sim_cfg = SimConfig.from_settings(settings)
    out_dir.mkdir(parents=True, exist_ok=True)

    policies: list[tuple[str, list[int]]] = []
    # Static
    policies.append(("static", StaticRunner(fixed=3).desired(trace)))
    policies.append(("reactive", ReactiveRunner(cfg).desired(trace)))
    # ML (try to load lightgbm if exists)
    model_path = Path("ml/models/artifacts/lightgbm.joblib")
    if model_path.exists():
        policies.append(("ml_predictive", MLPredictiveRunner(model_path, cfg).desired(trace)))
    policies.append(("oracle", _oracle_desired(trace, cfg)))

    summary_rows = []
    for name, desired in policies:
        sim = WorkloadReplaySimulator(sim_cfg).simulate(trace, lambda row, i, desired=desired: desired[i], start_capacity=desired[0] if desired else cfg.min_instances)
        summary = summarize_simulation(sim)
        summary["policy"] = name
        summary["trace"] = Path(trace_path).name
        summary["provisioning_delay_s"] = sim_cfg.provisioning_delay_s
        summary_rows.append(summary)
        sim.to_csv(out_dir / f"{name}_simulation.csv", index=False)
        plot_comparison(out_dir, name, sim)

    pd.DataFrame(summary_rows).to_csv(out_dir / "policy_comparison.csv", index=False)
    return pd.DataFrame(summary_rows)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run ElasticMind policy evaluation")
    p.add_argument("--trace", default="ml/data/generated/diurnal.parquet")
    p.add_argument("--out", default="experiments/results")
    args = p.parse_args(argv)
    run_all(args.trace, Path(args.out))


if __name__ == "__main__":
    main()
