# ElasticMind

[![CI](https://github.com/agniv-dutta/ElasticMind/actions/workflows/ci.yml/badge.svg)](https://github.com/agniv-dutta/ElasticMind/actions/workflows/ci.yml)

An ML-driven cloud resource manager that forecasts workload and auto-allocates
capacity using a predictive controller with a reactive fallback. It evaluates
accuracy, utilization, latency, cost and energy in a fully local, reproducible
lab, then ships the same controller to AWS ECS Fargate via Terraform.

> **All numeric results in the local lab are simulated.** The simulator, power
> model and cost figures are labelled `[simulated]` in code and in the
> dashboard. See [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md).

## Highlights

- **ML forecaster**: LightGBM multi-horizon (5/15/30 min) with **P50/P90**
  quantile outputs; Holt-Winters and a persistence baseline for comparison.
- **Autoscaler**: `desired = ceil(P90 / (capacity_per_instance × target_util))`
  with headroom, min/max, fast scale-up / slow scale-down, cooldowns and
  hysteresis.
- **Simulator**: replays a 1-min trace with a provisioning delay and reports
  utilization, SLA violations, latency (M/M/c-style), cost and energy.
- **Robustness**: reactive safety net, rolling-MAPE drift alarm,
  confidence-aware headroom, automatic fallback to reactive on drift.
- **Dashboard**: React + Vite + TypeScript + Tailwind + Recharts, polling the
  backend every 5 s (replaces Grafana).
- **AWS**: ECS Fargate + ALB + S3 + CloudWatch + Terraform (Phase 2).

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the Mermaid diagram.

```
loadgen → target_app → metrics collector → SQLite → predictor → autoscaler
        → capacity actuator → target_app
React dashboard ← backend JSON API
```

## Repository layout

```
elasticmind/
├── ml/           # data, features, models, training, evaluation
├── backend/      # FastAPI, autoscaler, simulator, robustness, SQLite
├── frontend/     # React dashboard
├── loadgen/      # async Python traffic generator
├── target_app/   # tiny FastAPI app being scaled
├── infra/        # docker-compose, dockerfiles, terraform
├── experiments/  # scripted runs + results
└── docs/         # architecture, assumptions, report, demo script
```

## Quickstart

### 1. Python environment

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -e ./ml -e ./backend -e ./loadgen -e ./target_app
pip install pytest ruff black
```

### 2. Generate data and train

```bash
python -m ml.data.generate --profile diurnal --days 14 --out ml/data/generated/diurnal.parquet
python -m ml.train --data ml/data/generated/diurnal.parquet --stride 30 --max-points 25
# -> experiments/results/model_comparison.csv + ml/models/artifacts/*.joblib
```

### 3. Run the evaluation experiments

```bash
python -m experiments.run_eval --trace ml/data/generated/diurnal.parquet
python -m experiments.run_misprediction
# -> experiments/results/{policy_comparison,misprediction_scenarios}.csv (+ PNGs)
```

### 4. Run everything with Docker

```bash
make up      # backend + frontend + target_app
make demo     # train if needed, start stack, loadgen, misprediction scenario
make down
```

On Windows use the PowerShell scripts instead of `make`:

```powershell
./scripts/demo.ps1
./scripts/smoke_test.ps1
```

- Dashboard: <http://localhost:5173>
- API docs:  <http://localhost:8000/docs>
- Target app: <http://localhost:8001/health>

## Tests & lint

```bash
make test    # pytest across ml/ backend/ loadgen/ target_app/
make lint    # ruff + black --check + tsc
```

## Screenshots

> Replace these placeholders with your own captures.

| Dashboard | Compare experiments |
|---|---|
| ![dashboard](docs/img/dashboard.png) | ![experiments](docs/img/experiments.png) |

## AWS (Phase 2)

```bash
cd infra/terraform
terraform init && terraform apply     # plan/apply; then record the demo
terraform destroy                     # keep costs low
```

See [`infra/terraform/README.md`](infra/terraform/README.md).

## Assignment stages

Problem → Identify → Choose → Design → Evaluate → Discuss. See
[`docs/REPORT_TEMPLATE.md`](docs/REPORT_TEMPLATE.md).
