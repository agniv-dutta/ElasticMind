# target_app/ — the tiny service being scaled

A minimal FastAPI app with a `/work` endpoint that burns configurable CPU
(busy-wait) and reports per-request latency in milliseconds.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/work` | burn `TARGET_APP_CPU_BURN_MS` and return `latency_ms` |

## Run

```bash
uvicorn target_app.app:app --host 0.0.0.0 --port 8001
```

Env: `TARGET_APP_PORT` (default 8001), `TARGET_APP_CPU_BURN_MS` (default 40).

## Test

```bash
python -m pytest target_app/tests -q
```
