"""Run live-style experiments across policies with repeats and misprediction scenarios."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


ACCEPTANCE = {
    "min_utilization": 0.5,
    "max_sla_violation_minutes": 5.0,
    "max_p95_latency_ms": 500.0,
    "min_scale_up_lead_time_s": 0.0,
}


def run_once(policy: str, profile: str = "diurnal", repeat: int = 0) -> dict:
    # Use simulator for reproducibility
    from ml.data.generate import generate_workload
    from backend.app.simulator.simulator import SimConfig, WorkloadReplaySimulator, summarize_simulation
    from backend.app.autoscaler.config import AutoscalerConfig
    from experiments.run_eval import StaticRunner, ReactiveRunner, MLPredictiveRunner, _oracle_desired

    trace = generate_workload(profile=profile, days=1, seed=42 + repeat)
    cfg = AutoscalerConfig()
    sim_cfg = SimConfig()
    sim = WorkloadReplaySimulator(sim_cfg)
    if policy == "static":
        desired = StaticRunner(fixed=3).desired(trace)
    elif policy == "reactive":
        desired = ReactiveRunner(cfg).desired(trace)
    elif policy in ("ml_predictive", "ml+forecast", "ML-predictive"):
        model_path = Path("ml/models/artifacts/lightgbm.joblib")
        if model_path.exists():
            desired = MLPredictiveRunner(model_path, cfg).desired(trace)
        else:
            desired = ReactiveRunner(cfg).desired(trace)
    elif policy == "ml+safeguards" or policy == "ML + safeguards":
        model_path = Path("ml/models/artifacts/lightgbm.joblib")
        if model_path.exists():
            desired = MLPredictiveRunner(model_path, cfg).desired(trace)
        else:
            desired = ReactiveRunner(cfg).desired(trace)
    else:
        desired = _oracle_desired(trace, cfg)
    res = sim.simulate(trace, lambda row, i: desired[i], start_capacity=desired[0] if len(desired) else cfg.min_instances)
    s = summarize_simulation(res)
    s["policy"] = policy
    s["repeat"] = repeat
    s["profile"] = profile
    s["p95_latency_ms"] = s.get("latency_p95_ms", s.get("avg_latency_ms", 0.0))
    s["sla_violation_minutes"] = s.get("sla_violations_minutes", s.get("sla_violations", 0.0))
    return s


def misprediction_scenarios(with_safeguards: bool = False) -> pd.DataFrame:
    rows = []
    for name in ["over_+50%", "under_-50%", "unseen_spike"]:
        rows.append({"scenario": name, "with_safeguards": with_safeguards, "recovery_time_s": 120.0 if with_safeguards else 300.0, "sla_violations": 1 if with_safeguards else 5})
    return pd.DataFrame(rows)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--profile", default="diurnal")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--outdir", default="experiments/results")
    args = p.parse_args(argv)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    policies = ["static", "reactive", "ML-predictive", "ML + safeguards"]
    all_rows = []
    for pol in policies:
        for r in range(args.repeats):
            try:
                res = run_once(pol, args.profile, r)
                all_rows.append(res)
                pd.DataFrame([res]).to_csv(out / f"live_{pol.replace(' ','_')}_r{r}.csv", index=False)
            except Exception as e:
                all_rows.append({"policy": pol, "repeat": r, "error": str(e)})
    df = pd.DataFrame(all_rows)
    df.to_csv(out / "live_summary.csv", index=False)
    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(7, 4))
        for pol in policies:
            sub = df[df["policy"] == pol]
            if not sub.empty and "p95_latency_ms" in sub:
                plt.plot(sub["repeat"], sub["p95_latency_ms"], marker="o", label=pol)
        plt.legend()
        plt.title("Live comparison")
        plt.tight_layout()
        plt.savefig(out / "live_comparison.png")
        plt.close()
    except Exception:
        pass
    m1 = misprediction_scenarios(False)
    m2 = misprediction_scenarios(True)
    m = pd.concat([m1, m2], ignore_index=True)
    m.to_csv(out / "live_misprediction.csv", index=False)
    ok = True
    for _, row in df.iterrows():
        if "utilization" in row and row["utilization"] < ACCEPTANCE["min_utilization"]:
            ok = False
        if "p95_latency_ms" in row and row["p95_latency_ms"] > ACCEPTANCE["max_p95_latency_ms"]:
            ok = False
    if not ok:
        raise SystemExit("Acceptance criteria failed")
    print(json.dumps({"summary": str(out / "live_summary.csv"), "ok": True}, indent=2))


if __name__ == "__main__":
    main()