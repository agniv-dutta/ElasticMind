# ElasticMind stack smoke: launch services, run sustained traffic and verify scaling.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

docker compose up --build -d backend gateway
$loadgenContainer = $null
try {
    $backend = "http://localhost:8000"
    $gateway = "http://localhost:8001"
    for ($i=0; $i -lt 60; $i++) {
        try { Invoke-RestMethod "$backend/health" | Out-Null; break } catch { Start-Sleep 2 }
    }
    $before = (Invoke-RestMethod "$backend/capacity").desired_instances
    $loadgenContainer = docker compose --profile demo run -d --rm loadgen --profile spike
    if (-not $loadgenContainer) { throw 'Could not start spike-profile loadgen container.' }
    $scaledAt = $null
    $deadline = (Get-Date).AddMinutes(4)
    do {
        Start-Sleep 5
        $decisions = Invoke-RestMethod "$backend/decisions"
        $capacity = Invoke-RestMethod "$backend/capacity"
        if ($capacity.desired_instances -gt $before -and -not $scaledAt) { $scaledAt = Get-Date }
        if ($scaledAt -and $capacity.current_instances -gt $before) { break }
    } while ((Get-Date) -lt $deadline)
    if (-not ($decisions | Where-Object { $_.decision_source -and $_.reason })) { throw "No decision with source and reason" }
    if ($capacity.desired_instances -le $before) { throw "Spike profile did not raise desired replicas above $before." }
    if ($capacity.current_instances -le $before) { throw "Running replicas did not follow desired within startup delay." }
    Write-Host "Smoke passed: desired replicas $before -> $($capacity.desired_instances); running replicas $($capacity.current_instances) after startup delay"
} finally {
    if ($loadgenContainer) { docker stop $loadgenContainer | Out-Null }
    docker compose down
}
