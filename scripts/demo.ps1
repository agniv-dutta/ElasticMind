# ElasticMind one-command demo (PowerShell). Metrics simulated unless stated.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$BackendUrl = if ($env:LOADGEN_BACKEND_URL) { $env:LOADGEN_BACKEND_URL } else { "http://localhost:8000" }
$TargetUrl  = if ($env:TARGET_APP_URL) { $env:TARGET_APP_URL } else { "http://localhost:8001" }

Write-Host "==> ElasticMind demo (all metrics simulated unless stated)"

if (-not (Test-Path "ml/models/artifacts/lightgbm_local_demo.joblib")) {
    Write-Host "==> Demo model missing; training from local_demo cycles"
    python -m experiments.train_demo
}

Write-Host "==> Starting stack (backend, gateway, frontend)"
docker compose up --build -d backend gateway frontend

Write-Host "==> Waiting for backend health..."
for ($i = 0; $i -lt 30; $i++) {
    try { Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 3 | Out-Null; break }
    catch { Start-Sleep -Seconds 2 }
}

Write-Host "==> Running load generator against gateway"
python -m loadgen.runner --target-url $TargetUrl --backend-url $BackendUrl `
    --profile local_demo --days 1 --speed-factor 20

Write-Host "==> Triggering misprediction scenarios"
python -m experiments.run_misprediction

try {
    Invoke-RestMethod -Method Post -Uri "$BackendUrl/faults/bias" -ContentType 'application/json' -Body '{"bias_percent": 40}'
    Invoke-RestMethod -Method Post -Uri "$BackendUrl/faults/spike" -ContentType 'application/json' -Body '{"magnitude": 3.0, "duration_minutes": 5}'
} catch { Write-Host "fault injection (backend may still be warming up)" }

Write-Host ""
Write-Host "==> Dashboard: http://localhost:5173  API docs: $BackendUrl/docs"
Write-Host "==> Stop with: docker compose --profile demo down"
