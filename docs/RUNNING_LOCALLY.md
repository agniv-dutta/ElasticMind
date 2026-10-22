# Running ElasticMind locally (PowerShell)

Run these commands from the repository root. The shared `.venv` must contain
the project packages; create it once with:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .\ml -e .\backend -e .\gateway -e .\loadgen -e .\target_app
```

Install the frontend dependencies once with `npm --prefix frontend install`.

## Services

| Service | PowerShell command | Port | Required environment variables | Depends on |
|---|---|---:|---|---|
| Backend | `.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000` | 8000 | None for local defaults. `ELASTICMIND_DB_URL`, `ELASTICMIND_ACTUATOR`, `ELASTICMIND_TIME_SCALE`, and other `ELASTICMIND_*` settings are optional overrides. `ELASTICMIND_ACTUATOR=aws` additionally needs AWS credentials, `AWS_REGION`, `ELASTICMIND_ECS_CLUSTER`, and `ELASTICMIND_ECS_SERVICE`. | Gateway for live replica synchronization and telemetry; starts and serves without it. |
| Gateway | `$env:GATEWAY_BACKEND_URL='http://localhost:8000'; .\.venv\Scripts\python.exe -m uvicorn gateway.app:app --host 127.0.0.1 --port 8001` | 8001 | None required. `GATEWAY_BACKEND_URL` enables periodic metrics delivery. Optional tuning: `GATEWAY_INITIAL_REPLICAS`, `GATEWAY_CONCURRENCY_PER_REPLICA`, `GATEWAY_QUEUE_LIMIT`, `GATEWAY_CPU_BURN_MS`, `GATEWAY_CAPACITY_PER_REPLICA_RPM`, `GATEWAY_METRICS_INTERVAL_S`. | Backend for metrics reporting; can serve without it. |
| `target_app` (optional) | `$env:TARGET_APP_PORT='8002'; .\.venv\Scripts\python.exe -m uvicorn target_app.app:app --host 127.0.0.1 --port 8002` | 8002 in this command (`TARGET_APP_PORT`, default 8001) | `TARGET_APP_PORT` and `TARGET_APP_CPU_BURN_MS` are optional; defaults are 8001 and 40 ms. | None. The standalone app is only needed when directly testing that implementation. |
| Frontend | `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173` | 5173 | None for local defaults. `VITE_API_BASE` is optional; Vite proxies `/api` to `http://localhost:8000`. | Backend API; page itself can start without it. Requires `npm --prefix frontend install` once. |
| Loadgen | `$env:LOADGEN_TARGET_URL='http://localhost:8001'; $env:LOADGEN_BACKEND_URL='http://localhost:8000'; .\.venv\Scripts\python.exe -m loadgen.runner --profile steady` | No listening port | `LOADGEN_TARGET_URL` (default `http://localhost:8001`), `LOADGEN_BACKEND_URL` (optional), `LOADGEN_PROFILE` (default `steady`), `LOADGEN_SPEED_FACTOR` (default 1; optional speed multiplier; `--speed-factor` overrides it). Runs continuously unless `--once` is specified. | The selected target URL, normally the gateway; backend URL is used for compatibility/configuration and the gateway sends live telemetry itself. |

Every HTTP service above exposes `GET /health`, except the Vite frontend,
which serves the dashboard at `/` and does not define a health endpoint.

## Replicas and request path

The standard local path is `loadgen â†’ gateway:8001 â†’ gateway ReplicaPool`.
Gateway replicas are **logical workers created and scaled inside the gateway
process** by `ReplicaPool`; they are not separate `target_app` processes.
The backend sends desired counts to the gateway's `PUT /replicas` endpoint.
The separate `target_app` process is not used by this path and can be omitted.
If started independently, use another port (as in the command above) so it
does not conflict with the gateway on port 8001.

## Run and stop the live stack

The script starts backend, gateway, frontend, waits for each readiness URL,
then launches continuous loadgen. It uses `.venv\Scripts\python.exe`, writes
service logs to `.live-logs`, and defaults to steady traffic. The 15-second
startup check confirms the processes remain alive; it does not stop them.
Choose a profile with `./scripts/run_live.ps1 -Profile steady|ramp|spike`.
Steady sends 60 rpm continuously. Ramp rises from 60 to 600 rpm over five
minutes. Spike runs steady for one minute, sends 480 rpm (8x) for two minutes,
then continues steady. Every ten seconds loadgen logs target rpm, sent count,
success rate, and p95 latency.

```powershell
./scripts/run_live.ps1
./scripts/stop_live.ps1
```

Once loadgen sends traffic and the gateway's telemetry interval reaches the
backend, the dashboard System status strip reports **gateway connected**.
It may initially display â€œgateway not connectedâ€ while the first telemetry
interval is pending.

The forecast uses gateway request rate in requests per minute (rpm), matching
the loadgen and the actual-load line. The earlier flat forecast around 15–17
came from the synthetic diurnal sample used by the old forecast path; those
values were not comparable to live RPM. The controller now uses a reactive
fallback with `decision_source=fallback` until it has 60 live telemetry samples
(about five minutes at the default gateway interval). The dashboard shows the
live-history count while this fallback is active.
