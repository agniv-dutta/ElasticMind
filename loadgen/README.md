# loadgen/ — async Python traffic generator (replaces Locust)

Drives real HTTP traffic at a configurable speed-up factor, replaying either a
generated profile or a trace file.

## Usage

```bash
python -m loadgen.runner \
  --target-url http://localhost:8001 \
  --backend-url http://localhost:8000 \
  --profile diurnal --days 1 --speed-factor 20 \
  --max-requests 300 --concurrency 8
```

Environment overrides: `LOADGEN_TARGET_URL`, `LOADGEN_BACKEND_URL`,
`LOADGEN_TRACE`, `LOADGEN_PROFILE`, `LOADGEN_DAYS`, `LOADGEN_SPEED_FACTOR`.

## Output

A JSON summary with `requests_total`, `success_rate`, `latency_p50_ms`,
`latency_p95_ms`, `duration_s` (all **measured** against the target app; the
demand shape itself is **simulated**). Optionally POSTed to the backend so the
dashboard can show measured API latency alongside simulated latency.

## Test

```bash
python -m pytest loadgen/tests -q
```
