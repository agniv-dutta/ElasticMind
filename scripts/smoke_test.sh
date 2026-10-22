#!/usr/bin/env bash
# ElasticMind end-to-end smoke test (no Docker required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> 1/5 python test suite"
python -m pytest ml backend loadgen target_app gateway -q

echo "==> 2/5 generate data + train (fast settings)"
python -m ml.data.generate --profile diurnal --days 7 --out ml/data/generated/smoke.parquet
python -m ml.train --data ml/data/generated/smoke.parquet --models lightgbm reactive_baseline \
  --stride 60 --max-points 8

echo "==> 3/5 run policy evaluation"
python -m experiments.run_eval --trace ml/data/generated/smoke.parquet

echo "==> 4/5 run misprediction scenarios"
python -m experiments.run_misprediction

echo "==> 5/5 verify artifacts"
test -f experiments/results/model_comparison.csv
test -f experiments/results/policy_comparison.csv
test -f experiments/results/misprediction_scenarios.csv

echo "==> smoke test OK"
