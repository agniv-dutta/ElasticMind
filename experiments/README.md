# experiments/ — scripted runs and results

Comparisons are run offline against **simulated** workload traces.

## Scripts

| Script | Output |
|---|---|
| `run_eval.py` | `policy_comparison.csv` + per-policy `*_simulation.csv`/`*.png` |
| `run_misprediction.py` | `misprediction_scenarios.csv` / `.png` |
| `aws_run.py` (Phase 2) | CloudWatch metrics exported to CSV/PNG |

```bash
python -m experiments.run_eval --trace ml/data/generated/diurnal.parquet
python -m experiments.run_misprediction
```

## Results (`experiments/results/`)

- `model_comparison.csv` — MAPE/MAE/RMSE/under-prediction per model & horizon
- `policy_comparison.csv` — Static vs Reactive vs ML-Predictive vs Oracle:
  utilization, SLA violations, latency, cost, energy, CO2 (all simulated)
- `misprediction_scenarios.csv` — over/under-predict & sudden spike, with and
  without safeguards: SLA violations, cost, recovery time, over-provisioning
  waste

All outputs are labelled `simulated`.
