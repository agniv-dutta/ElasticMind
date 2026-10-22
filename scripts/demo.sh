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

if [ ! -f ml/models/artifacts/lightgbm_local_demo.joblib ]; then
  echo "==> Demo model missing; training from local_demo cycles"
  python -m experiments.train_demo
fi

echo "==> Starting stack (backend, gateway, frontend)"
docker compose up --build -d backend gateway frontend

echo "==> Waiting for backend health..."
for i in $(seq 1 30); do
  if curl -fsS "$BACKEND_URL/health" >/dev/null 2>&1; then break; fi
  sleep 2
done

echo "==> Running load generator against gateway"
python -m loadgen.runner --target-url "$TARGET_URL" --backend-url "$BACKEND_URL" \
  --profile local_demo --days 1 --speed-factor 20 || true

echo "==> Triggering misprediction scenarios"
python -m experiments.run_misprediction || true

curl -fsS -X POST "$BACKEND_URL/faults/bias" -H 'Content-Type: application/json' -d '{"bias_percent": 40}' || true
echo ""
curl -fsS -X POST "$BACKEND_URL/faults/spike" -H 'Content-Type: application/json' -d '{"magnitude": 3.0, "duration_minutes": 5}' || true

echo ""
echo "==> Dashboard: http://localhost:5173  API docs: $BACKEND_URL/docs"
echo "==> Stop with: make down"
