# ElasticMind — Demo Script

A 5–8 minute walkthrough. Run locally first; optionally repeat on AWS (Phase 2).
Every number shown in the dashboard is **simulated** unless labelled otherwise.

## 0. Prerequisites

- Docker Desktop running.
- Run local: `make up` (or `docker compose up --build`).
- Services: backend `http://localhost:8000`, dashboard `http://localhost:5173`,
  target app `http://localhost:8001`.

## 1. Show the data & model (1 min)

1. Open `ml/notebooks/01_eda.ipynb` — workload profiles (`steady`, `diurnal`, `spiky`).
2. Show `experiments/results/model_comparison.csv`:
   - LightGBM ≈ lowest MAPE (e.g. ~8%); Holt-Winters and reactive baseline worse.

## 2. Start the live demo (2 min)

```bash
make demo        # Linux/macOS/WSL
make demo-ps     # Windows PowerShell
```

This starts the load generator (`demo` profile) plus backend + dashboard.

- Dashboard tabs:
  - **Live**: predicted vs actual load, desired vs running capacity.
  - **Decisions**: scale-up/down actions + reasons.
  - **Experiments**: policy comparison table.
- Point out: the controller **scales up before** the diurnal peak (predictive),
  versus the reactive baseline that lags.

## 3. Show a misprediction (1–2 min)

Inject a sudden spike (simulated fault):

```bash
curl -X POST http://localhost:8000/faults/spike -H "Content-Type: application/json" \
     -d '{"magnitude": 3.0, "duration_minutes": 5}'
```

- Watch `GET /robustness/status`: `drift_alarm` flips on, `active_mode` falls
  back to reactive, then recovers.
- Point at SLA-violation counter and rolling MAPE.

## 4. Explain the safeguard (30 s)

- Under-prediction → reactive safety net right-sizes to observed load + P90 headroom.
- Over-prediction → slow scale-down cooldown prevents thrash.

## 5. (Optional) AWS (2 min)

- `cd infra/terraform && terraform apply`.
- Push images, then run the driver:

```bash
python -m experiments.aws_run --alb-dns <alb_dns_name> --duration 120
```

- Open the **CloudWatch dashboard** `elasticmind-overview` — the *only* monitoring
  tool (no Grafana/Prometheus).
- **Finish: `./destroy.sh`** to stop charges.

## Talking points

- Predictive provisioning removes the reactive lag; safeguards cover wrong predictions.
- Cost/energy figures are model estimates (simulated), not AWS billing.
- Everything runs from one repo: ML, backend, dashboard, loadgen, infra.
## Live sampling

- Sample interval: 5 seconds (CONTROL_INTERVAL_S). For profile local_demo, ML needs >= 60 samples (~5 minutes at 5s intervals). With TIME_SCALE>1 this time compresses.
