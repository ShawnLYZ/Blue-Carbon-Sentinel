# Performance probe against the design section 33 targets. Windows PowerShell 5.1 compatible.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\perf.ps1 [-Seconds 120]
# Starts the stack (scripts\start.ps1 -NoWindows) if the Ground Station is not already running, runs
# `bcs-gs perf`, then stops what it started. Metrics with no samples (for example the camera is offline)
# are reported as "no samples", not as failures. Output: a table and var\logs\perf-<ts>.json.
param([int]$Seconds = 120)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$GsUrl = 'http://127.0.0.1:8700'

function Test-Gs {
    try { return ((Invoke-WebRequest -Uri "$GsUrl/api/v1/system/status" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) }
    catch { return $false }
}

$started = $false
$ready = $null
$code = 1
Push-Location $Root
try {
    if (-not (Test-Gs)) {
        $sw = [Diagnostics.Stopwatch]::StartNew()
        # Set before start.ps1 runs: a half-started stack must be stopped on every path below.
        $started = $true
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start.ps1') -NoWindows
        if ($LASTEXITCODE -ne 0) { Write-Host 'The stack did not start.'; exit 1 }
        $ready = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    }
    $perfArgs = @('run', 'bcs-gs', 'perf', '--seconds', "$Seconds")
    if ($null -ne $ready) { $perfArgs += @('--start-to-ready', "$ready") }
    & uv @perfArgs
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    if ($started) { & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stop.ps1') | Out-Null }
}
exit $code
