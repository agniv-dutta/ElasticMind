"""Ramp load against ONE replica to calibrate CAPACITY_PER_REPLICA_RPM."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from loadgen.runner import run_load


def calibrate(
    target_url: str = "http://localhost:8001",
    sla_ms: float = 200.0,
    margin: float = 0.20,
    out_yaml: str = "configs/calibration.yaml",
    out_png: str = "experiments/results/latency_vs_load.png",
) -> dict:
    rates = [10, 25, 50, 75, 100, 125, 150]
    rows = []
    for r in rates:
        try:
            import asyncio
            s = asyncio.run(run_load(target_url=target_url, speed_factor=max(1, r / 50), max_requests=50, concurrency=1))
            rows.append({"rpm": r, "p95_ms": s.get("latency_p95_ms", 0.0), "p50_ms": s.get("latency_p50_ms", 0.0), "ok": s.get("success_rate", 0.0)})
        except Exception as e:
            rows.append({"rpm": r, "p95_ms": 9999.0, "p50_ms": 9999.0, "ok": 0.0, "err": str(e)})
    df = pd.DataFrame(rows)
    cap = 50.0
    for _, row in df.iterrows():
        if row["p95_ms"] >= sla_ms:
            cap = max(10.0, row["rpm"] * (1 - margin))
            break
    else:
        cap = max(10.0, df["rpm"].max() * (1 - margin))
    cap = float(cap)
    result = {"CAPACITY_PER_REPLICA_RPM": round(cap, 2), "sla_ms": sla_ms, "margin": margin, "ramp": rows, "note": "On AWS, re-run against one real Fargate task."}
    Path(out_yaml).parent.mkdir(parents=True, exist_ok=True)
    Path(out_yaml).write_text(yaml.safe_dump(result, sort_keys=False))
    try:
        plt.figure(figsize=(6, 4))
        plt.plot(df["rpm"], df["p95_ms"], marker="o")
        plt.axhline(sla_ms, ls="--", label="SLA")
        plt.xlabel("Request rate (rpm, approx)")
        plt.ylabel("p95 latency (ms)")
        plt.title("Latency vs load (1 replica)")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_png)
        plt.close()
    except Exception:
        pass
    return result


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--target-url", default="http://localhost:8001")
    p.add_argument("--sla-ms", type=float, default=200.0)
    p.add_argument("--margin", type=float, default=0.20)
    args = p.parse_args(argv)
    res = calibrate(args.target_url, args.sla_ms, args.margin)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()