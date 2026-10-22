$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StatePath = Join-Path $Root '.live-processes.json'
if (-not (Test-Path $StatePath)) {
    Write-Host 'No live stack process list found.'
    exit 0
}

$items = @(Get-Content -Raw $StatePath | ConvertFrom-Json)
$flatItems = @($items | ForEach-Object { $_ })
foreach ($item in $flatItems) {
    foreach ($pidValue in @($item.pid)) {
        $proc = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
        if ($proc) {
            & taskkill.exe /PID $proc.Id /T /F | Out-Null
            Write-Host "Stopped $($item.name) (PID $pidValue)"
        }
    }
}
Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
