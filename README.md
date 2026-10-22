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
loadgen → gateway → replica pool → gateway metrics → backend → predictor
        → autoscaler → capacity actuator → gateway replica pool
React dashboard ← backend JSON API
```

## Repository layout

```
elasticmind/
├── ml/           # data, features, models, training, evaluation
├── backend/      # FastAPI, autoscaler, simulator, robustness, SQLite
├── frontend/     # React dashboard
├── loadgen/      # async Python traffic generator
├── gateway/      # FastAPI round-robin gateway and CPU-burn replica pool
├── target_app/   # standalone target service for local experiments
├── infra/        # docker-compose, dockerfiles, terraform
├── experiments/  # scripted runs + results
└── docs/         # architecture, assumptions, report, demo script
```

## Quickstart

### Shared runtime settings

Backend and experiment scripts use the shared `Settings` model. Loadgen reads
`ELASTICMIND_TIME_SCALE` directly and spaces HTTP requests according to the
profile at that speed-up factor. For example, `ELASTICMIND_TIME_SCALE=10`
replays each simulated minute in six wall-clock seconds.

The settings fields are `PROFILE`, `TIME_SCALE`, `ACTUATOR`,
`CONTROL_INTERVAL_S`, `FORECAST_HORIZON_MIN`, `TARGET_UTILIZATION`,
`CAPACITY_PER_REPLICA_RPM`, `MIN_REPLICAS`, `MAX_REPLICAS`, `STARTUP_DELAY_S`,
`DRAIN_DELAY_S`, `SLA_LATENCY_MS`, `PRICE_PER_REPLICA_HOUR`, `IDLE_WATTS`,
`PEAK_WATTS`, `COOLDOWN_UP_S`, `COOLDOWN_DOWN_S`, and
`SAFETY_UTILIZATION_THRESHOLD`.

### 1. Python environment

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -e ./ml -e ./backend -e ./loadgen -e ./gateway -e ./target_app
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
make up      # backend + gateway + frontend
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
- Gateway: <http://localhost:8001/health>
- Gateway replica pool: <http://localhost:8001/replicas>

The gateway accepts `GET /work`, records request ID, status, replica ID and
latency at `GET /requests`, and publishes interval metrics to the backend.
Scale its local pool with `PUT /replicas` and JSON `{"desired": 4}`. Configure
worker service time and saturation with `GATEWAY_CPU_BURN_MS`,
`GATEWAY_CONCURRENCY_PER_REPLICA`, and `GATEWAY_QUEUE_LIMIT`.

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
