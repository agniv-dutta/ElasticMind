# ElasticMind stack smoke: launch services, run sustained traffic and verify scaling.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

docker compose up --build -d backend gateway
try {
    $backend = "http://localhost:8000"
    $gateway = "http://localhost:8001"
    for ($i=0; $i -lt 60; $i++) {
        try { Invoke-RestMethod "$backend/health" | Out-Null; break } catch { Start-Sleep 2 }
    }
    Invoke-RestMethod -Method Post -Uri "$backend/autoscaler/start" | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        Invoke-RestMethod "$gateway/work" | Out-Null
        Start-Sleep -Milliseconds 100
    }
    Invoke-RestMethod -Method Post -Uri "$backend/faults/spike" -ContentType "application/json" -Body '{"magnitude":2,"duration_minutes":5}' | Out-Null
    $before = (Invoke-RestMethod "$backend/capacity").desired_instances
    $until = (Get-Date).AddSeconds(90)
    do {
        1..100 | ForEach-Object { Invoke-RestMethod "$gateway/work" | Out-Null }
        Start-Sleep 2
        $decisions = Invoke-RestMethod "$backend/decisions"
        $capacity = Invoke-RestMethod "$backend/capacity"
    } while ((Get-Date) -lt $until -and $capacity.desired_instances -le $before)
    if (-not ($decisions | Where-Object { $_.decision_source -and $_.reason })) { throw "No decision with source and reason" }
    if ($capacity.desired_instances -le $before) { throw "Desired replicas did not increase" }
    Write-Host "Smoke passed: desired replicas $before -> $($capacity.desired_instances)"
} finally {
    docker compose down
}
