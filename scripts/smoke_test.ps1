# ElasticMind end-to-end smoke test (PowerShell, no Docker required).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "==> 1/5 python test suite"
python -m pytest ml backend loadgen target_app -q

Write-Host "==> 2/5 generate data + train (fast settings)"
python -m ml.data.generate --profile diurnal --days 7 --out ml/data/generated/smoke.parquet
python -m ml.train --data ml/data/generated/smoke.parquet --models lightgbm reactive_baseline --stride 60 --max-points 8

Write-Host "==> 3/5 run policy evaluation"
python -m experiments.run_eval --trace ml/data/generated/smoke.parquet

Write-Host "==> 4/5 run misprediction scenarios"
python -m experiments.run_misprediction

Write-Host "==> 5/5 verify artifacts"
foreach ($f in @(
    "experiments/results/model_comparison.csv",
    "experiments/results/policy_comparison.csv",
    "experiments/results/misprediction_scenarios.csv")) {
    if (-not (Test-Path $f)) { throw "missing artifact: $f" }
}

Write-Host "==> smoke test OK"
