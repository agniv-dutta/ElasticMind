#!/usr/bin/env bash
# ElasticMind one-command demo (simulated where noted).
# Trains the model if missing, starts the stack, runs the load generator and
# triggers a misprediction scenario.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_URL="${LOADGEN_BACKEND_URL:-http://localhost:8000}"
TARGET_URL="${TARGET_APP_URL:-http://localhost:8001}"

echo "==> ElasticMind demo (all metrics simulated unless stated)"

if [ ! -f ml/models/artifacts/lightgbm.joblib ]; then
  echo "==> Model missing; generating data + training"
  python -m ml.data.generate --profile diurnal --days 14 --out ml/data/generated/diurnal.parquet
  python -m ml.train --data ml/data/generated/diurnal.parquet --stride 30 --max-points 25
fi

echo "==> Starting stack (backend, frontend, target_app)"
docker compose up --build -d backend frontend target_app

echo "==> Waiting for backend health..."
for i in $(seq 1 30); do
  if curl -fsS "$BACKEND_URL/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "==> Running load generator against target app"
python -m loadgen.runner --target-url "$TARGET_URL" --backend-url "$BACKEND_URL" \
  --profile diurnal --days 1 --speed-factor 20 --max-requests 300 || true

echo "==> Triggering misprediction scenarios"
python -m experiments.run_misprediction || true

curl -fsS -X POST "$BACKEND_URL/faults/bias" -H 'Content-Type: application/json' -d '{"bias_percent": 40}' || true
echo ""
curl -fsS -X POST "$BACKEND_URL/faults/spike" -H 'Content-Type: application/json' -d '{"magnitude": 3.0, "duration_minutes": 5}' || true

echo ""
echo "==> Dashboard: http://localhost:5173  API docs: $BACKEND_URL/docs"
echo "==> Stop with: make down"
