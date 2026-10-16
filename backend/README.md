# backend/ — FastAPI, autoscaler, simulator, robustness, SQLite

The ElasticMind control plane. All capacity/cost/energy numbers are
**[simulated]** unless produced by the AWS actuator with real CloudWatch data.

## Contents

```
backend/app/
├── main.py            # FastAPI app + endpoints + background control loop
├── core/config.py     # env-driven Settings
├── db/models.py       # SQLAlchemy: metrics, forecasts, decisions, experiments
├── schemas/schemas.py # pydantic request/response models
├── autoscaler/        # control loop, policies, actuators (local + aws)
├── simulator/         # replay trace + provisioning delay + power/cost model
└── robustness/        # safety net, drift alarm, fallback, confidence headroom
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/predict` | run the forecaster, persist to SQLite |
| GET | `/forecast` | latest forecast |
| GET | `/capacity` | current & desired instances |
| POST | `/autoscaler/start` \| `/stop` \| `/policy` | control the loop |
| POST | `/faults/bias` \| `/faults/spike` | inject misprediction |
| GET | `/metrics` | current util/latency/cost/energy/SLA (simulated) |
| GET | `/metrics/history` | history from SQLite |
| GET | `/decisions` | scaling decision log |
| GET | `/experiments` | evaluation results (from `experiments/results`) |
| GET | `/robustness/status` | drift alarm / fallback mode / rolling MAPE |
| GET | `/health` | liveness |

## Run

```bash
uvicorn backend.app.main:app --reload --port 8000
```

## Test

```bash
python -m pytest backend/tests -q
```

Covers policies (cooldowns, hysteresis, clamps, zero load), the simulator,
safeguards (drift/fallback/safety net) and all HTTP endpoints (TestClient +
httpx ASGI transport).
