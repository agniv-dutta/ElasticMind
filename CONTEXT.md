# ElasticMind — Project Context

Project: **ElasticMind**, a student project: an ML-based cloud resource manager
that predicts workload and auto-allocates capacity.

Stack: Python 3.11, FastAPI, SQLite, scikit-learn + LightGBM (optional LSTM),
React + Vite + TypeScript + Recharts, Docker Compose locally, later AWS ECS
Fargate + CloudWatch + Terraform.

Do NOT use Prometheus, Grafana, or Locust. All metrics are collected by the
backend, stored in SQLite, exposed as JSON, and visualized in our React
dashboard. Load generation is a Python script.

Assignment stages: Problem, Identify (input data/features), Choose (algorithm
+ prediction horizon), Design (allocation/auto-scaling), Evaluate (prediction
accuracy, utilization, latency, cost, energy), Discuss (what happens when the
prediction is wrong).

Rules: modular, typed, tested (pytest), a README per module, config via
env/YAML, label every simulated number as "simulated" in code and UI, ask
before adding heavy dependencies.

## Naming

Root folder / package namespace: `elasticmind/` modules live under the
monorepo directories (`ml/`, `backend/`, `frontend/`, `loadgen/`,
`target_app/`, `infra/`, `experiments/`, `docs/`). The project name used in
tags, docs, and `Project=` resource tags is `elasticmind`.
