# ElasticMind — Project Report

> Follow the assignment stages below. Replace every `TODO` with your results.
> **All simulated numbers must be labelled "simulated" in both code and UI.**
> Do not use Prometheus, Grafana, or Locust.

## 1. Problem

TODO: State the problem — cloud capacity is over- or under-provisioned because
reactive autoscaling only responds *after* load changes. ElasticMind predicts
workload and provisions capacity ahead of demand while keeping a reactive
safety net.

- Goal: minimise SLA violations + cost + energy vs a reactive baseline.
- Scope: student lab; local Docker stack first, single-region AWS (Fargate) second.

## 2. Identify (input data & features)

- **Input data**: request rate over time (synthetic profiles `steady`, `diurnal`,
  `spiky` + optional external CSV trace). TODO: describe your dataset and its
  source, and label it simulated if synthetic.
- **Features**: lags (t-1..t-k), rolling means/std, hour-of-day, day-of-week,
  EWMA. See `ml/features/engineering.py`.
- **Prediction horizon**: 5 / 15 / 30 minutes, with P50 (median) and P90
  (conservative) quantiles.

TODO: table of features + justification.

## 3. Choose (algorithm + horizon)

| Model | Type | Notes |
|-------|------|-------|
| Reactive baseline | persistence | last value = forecast |
| Holt-Winters | exponential smoothing | seasonality |
| LightGBM (chosen) | gradient-boosted trees, quantile | best MAPE |
| LSTM | optional | guarded, heavy dep |

- Chosen: **LightGBM multi-horizon quantile regression** (P50/P90).
- Rationale: strong accuracy, fast, interpretable, handles seasonality + holidays.
- TODO: paste accuracy table from `experiments/results/model_comparison.csv`.

## 4. Design (allocation / auto-scaling)

- Capacity per instance: `100.0` req/min (see `backend/app/autoscaler/config.py`).
- Target utilisation: `0.70`, headroom: `0.20`.
- Scale-up cooldown `30 s`, scale-down `120 s`, provisioning delay `90 s`.
- Controller: forecast P90 → desired instances → actuator (local sim or ECS).
- Safeguards: reactive safety net right-sizes observed load; drift alarm →
  reactive fallback (`backend/app/robustness/safeguards.py`).
- TODO: include the control-loop diagram (`docs/img/`).

## 5. Evaluate

Metrics: prediction accuracy (MAPE/RMSE), utilisation, latency, cost, energy.

TODO: fill from `experiments/results/policy_comparison.csv` and
`experiments/results/misprediction.csv`. Example:

| Policy | MAPE | Utilisation | SLA viol. | Cost (sim) | Energy (sim) |
|--------|------|-------------|-----------|------------|--------------|
| Reactive | ... | ... | ... | ... | ... |
| Predictive | ... | ... | ... | ... | ... |
| Predictive + safeguards | ... | ... | ... | ... | ... |

## 6. Discuss (when the prediction is wrong)

TODO: describe behaviour under (a) under-prediction (traffic spike → safety net
+ p90 headroom), (b) over-prediction (wasted capacity → scale-down cooldown).
Reference `experiments/results/misprediction.csv` and the robustness status
endpoint (`/robustness/status`).

## Appendix

- Reproduce: `make test`, `make train`, `make demo`.
- AWS: `infra/terraform` (destroy after demo!).
