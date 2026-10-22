param(
    [ValidateSet('steady', 'ramp', 'spike')]
    [string]$Profile = 'steady'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$StatePath = Join-Path $Root '.live-processes.json'
$LogDir = Join-Path $Root '.live-logs'
if (-not (Test-Path $Python)) { throw "Virtualenv Python not found: $Python" }
if (Test-Path $StatePath) { throw "Live stack state already exists. Run scripts/stop_live.ps1 first." }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Started = [System.Collections.Generic.List[object]]::new()
$FailedService = 'startup'

function Start-LiveProcess([string]$Name, [string]$File, [string]$Arguments, [string]$WorkDir = $Root) {
    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    $proc = Start-Process -FilePath $File -ArgumentList $Arguments -WorkingDirectory $WorkDir `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $Started.Add([pscustomobject]@{ name = $Name; pid = $proc.Id })
    $Started | ConvertTo-Json | Set-Content -Encoding UTF8 $StatePath
    Write-Host "Started $Name (PID $($proc.Id)); logs: $LogDir"
}

function Wait-Http([string]$Name, [string]$Url, [int]$TimeoutSeconds = 90) {
    $startedPid = [int]$Started[$Started.Count - 1].pid
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            Invoke-RestMethod -Uri $Url -TimeoutSec 3 | Out-Null
            if (-not (Get-Process -Id $startedPid -ErrorAction SilentlyContinue)) {
                throw "$Name process exited before becoming ready. Check $LogDir."
            }
            Write-Host "$Name is ready: $Url"
            return
        }
        catch {
            if (-not (Get-Process -Id $startedPid -ErrorAction SilentlyContinue)) {
                throw "$Name process exited before becoming ready. Check $LogDir."
            }
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)
    throw "$Name did not become ready at $Url. Check $LogDir."
}

try {
    # Backend sends replica updates to gateway; gateway can start after backend.
    Start-LiveProcess 'backend' $Python '-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000'
    Wait-Http 'Backend' 'http://127.0.0.1:8000/health'

    $env:GATEWAY_BACKEND_URL = 'http://127.0.0.1:8000'
    Start-LiveProcess 'gateway' $Python '-m uvicorn gateway.app:app --host 127.0.0.1 --port 8001'
    Wait-Http 'Gateway' 'http://127.0.0.1:8001/health'

    # Gateway's ReplicaPool handles requests itself. The standalone target_app
    # is therefore not needed for this stack and would contend for port 8001.
    $env:LOADGEN_TARGET_URL = 'http://127.0.0.1:8001'
    $env:LOADGEN_BACKEND_URL = 'http://127.0.0.1:8000'
    $env:LOADGEN_PROFILE = $Profile
    Start-LiveProcess 'frontend' 'npm.cmd' 'run dev -- --host 127.0.0.1 --port 5173' (Join-Path $Root 'frontend')
    Wait-Http 'Frontend' 'http://127.0.0.1:5173/'

    $profileArgs = $Profile
    Start-LiveProcess 'loadgen' $Python "-m loadgen.runner --target-url http://127.0.0.1:8001 --backend-url http://127.0.0.1:8000 --profile $profileArgs"

    Write-Host 'Verifying all services remain alive for 15 seconds...'
    Start-Sleep -Seconds 15
    foreach ($service in $Started) {
        $FailedService = $service.name
        if (-not (Get-Process -Id ([int]$service.pid) -ErrorAction SilentlyContinue)) {
            throw "$($service.name) process (PID $($service.pid)) exited during the 15-second check."
        }
    }

    $FailedService = 'gateway'
    $replicaState = @(Invoke-RestMethod 'http://127.0.0.1:8001/replicas')
    $runningReplicas = @($replicaState | Where-Object { $_.status -eq 'RUNNING' }).Count
    if ($runningReplicas -lt 1) { throw 'Gateway reports no RUNNING replicas.' }

    $FailedService = 'backend'
    $backendStatus = Invoke-RestMethod 'http://127.0.0.1:8000/status'
    if (-not $backendStatus.gateway_connected) { throw 'Backend /status reports gateway_connected=false.' }

    Write-Host ''
    Write-Host 'Dashboard: http://localhost:5173'
    Write-Host 'Gateway API: http://localhost:8001'
    Write-Host 'To stop: ./scripts/stop_live.ps1'
} catch {
    $logPath = Join-Path $LogDir "$FailedService.out.log"
    $errPath = Join-Path $LogDir "$FailedService.err.log"
    Write-Host "Startup verification failed for $FailedService. Last log lines:"
    foreach ($path in @($logPath, $errPath)) {
        if (Test-Path $path) {
            Write-Host "--- $path (last 20 lines) ---"
            Get-Content -LiteralPath $path -Tail 20
        }
    }
    & (Join-Path $Root 'scripts\stop_live.ps1')
    throw
}
