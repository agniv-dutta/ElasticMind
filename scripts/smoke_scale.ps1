param(
    [int]$MaxWaitSeconds = 300
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root ".smoke-scale-logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$state = Join-Path $Root ".smoke-scale-state.json"
$started = @()
try {
    $out = Join-Path $LogDir "backend.out.log"
    $err = Join-Path $LogDir "backend.err.log"
    $p = Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","backend.app.main:app","--host","127.0.0.1","--port","8000" -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    $started += @{name="backend"; pid=$p.Id}
    $started | ConvertTo-Json | Set-Content -Encoding UTF8 $state
    Start-Sleep -Seconds 5
    $env:GATEWAY_BACKEND_URL = "http://127.0.0.1:8000"
    $out2 = Join-Path $LogDir "gateway.out.log"
    $err2 = Join-Path $LogDir "gateway.err.log"
    $p2 = Start-Process -FilePath $Python -ArgumentList "-m","uvicorn","gateway.app:app","--host","127.0.0.1","--port","8001" -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $out2 -RedirectStandardError $err2
    $started += @{name="gateway"; pid=$p2.Id}
    $started | ConvertTo-Json | Set-Content -Encoding UTF8 $state
    Start-Sleep -Seconds 5
    $out3 = Join-Path $LogDir "loadgen.out.log"
    $err3 = Join-Path $LogDir "loadgen.err.log"
    $p3 = Start-Process -FilePath $Python -ArgumentList "-m","loadgen.runner","--target-url","http://127.0.0.1:8001","--backend-url","http://127.0.0.1:8000","--profile","spike" -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $out3 -RedirectStandardError $err3
    $started += @{name="loadgen"; pid=$p3.Id}
    $started | ConvertTo-Json | Set-Content -Encoding UTF8 $state
    Start-Sleep -Seconds 90
    $ok = $false
    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    while((Get-Date) -lt $deadline) {
        try {
            $dec = Invoke-RestMethod -Uri "http://127.0.0.1:8000/decisions" -TimeoutSec 5
            foreach($d in $dec) {
                $ds = $d.desired
                if($null -eq $ds) { $ds = $d.final_desired }
                if($null -eq $ds) { $ds = 0 }
                if([int]$ds -gt 1) { $ok = $true; break }
            }
            if($ok) { break }
        } catch {}
        Start-Sleep -Seconds 10
    }
    if(-not $ok) { throw "No decision with desired > 1 observed" }
    Write-Host "SMOKE_SCALE_OK"
    foreach($s in $started) { try { Stop-Process -Id $s.pid -Force -ErrorAction SilentlyContinue } catch {} }
    exit 0
} catch {
    Write-Host $_
    foreach($s in $started) { try { Stop-Process -Id $s.pid -Force -ErrorAction SilentlyContinue } catch {} }
    exit 1
}