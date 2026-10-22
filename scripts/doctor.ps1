param()
$ErrorActionPreference = "Continue"
Write-Host "=== ElasticMind doctor ==="
$py = py --version 2>&1; if ($py -match "Python 3\.11") { Write-Host "Python: OK ($py)" } else { Write-Host "Python: WARN ($py)"; python --version }
try {
    python -c "import sys; assert sys.version_info[:2]==(3,11); print('py311:', sys.version)" 2>&1
} catch {
    Write-Host "py311 assert: FAIL"
}
try {
    python -c "import lightgbm; print('lightgbm ok')" 2>&1
    python -c "import ctypes, os; print('ctypes ok')" 2>&1
    python -c "
# try to load libgomp if present
try:
    import ctypes.util
    p = ctypes.util.find_library('gomp')
    print('libgomp:', p)
except Exception as e:
    print('libgomp err', e)
" 2>&1
} catch {
    Write-Host "lightgbm/libgomp: WARN"
}
$art = Test-Path "ml/models/artifacts/lightgbm.joblib"
Write-Host "model artifact exists: $art"
$ports = @('8000','8001','5173')
foreach ($p in $ports) {
    $c = netstat -ano | findstr ":$p " | Measure-Object
    if ($c.Count -gt 0) { Write-Host "port $p: IN USE" } else { Write-Host "port $p: free" }
}
Write-Host "=== done ==="