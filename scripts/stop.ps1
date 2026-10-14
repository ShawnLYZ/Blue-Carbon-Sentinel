# Stops the processes recorded in var\run\*.pid (addendum D2). Windows PowerShell 5.1 compatible.
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path (Join-Path $Root 'var') 'run'

# A pid file is ours only if the process exists, is one we start, and began before the file was
# written. Anything else (crash, reboot, reused pid, empty file) is stale and is deleted.
function Test-OurPidFile($File) {
    $n = 0
    try {
        $txt = Get-Content -LiteralPath $File.FullName -Raw -ErrorAction Stop
        if (-not [string]::IsNullOrWhiteSpace($txt) -and [int]::TryParse($txt.Trim(), [ref]$n)) {
            $proc = Get-Process -Id $n -ErrorAction Stop
            $okName = @('mosquitto', 'python', 'pythonw', 'uv', 'bcs-gs', 'bcs-sim') -contains $proc.ProcessName.ToLower()
            if ($okName -and ($proc.StartTime -le $File.LastWriteTime.AddSeconds(2))) { return $n }
        }
    } catch { }
    Remove-Item -LiteralPath $File.FullName -Force -ErrorAction SilentlyContinue
    return 0
}

if (-not (Test-Path -LiteralPath $RunDir)) { Write-Host 'Nothing to stop.'; exit 0 }
foreach ($f in Get-ChildItem -LiteralPath $RunDir -Filter '*.pid' -ErrorAction SilentlyContinue) {
    $n = Test-OurPidFile $f
    if ($n -gt 0) {
        # /T also ends children (uv and venv launchers start the real server below them).
        & taskkill.exe /PID $n /T /F | Out-Null
        Write-Host ("Stopped {0} (pid {1})." -f $f.BaseName, $n)
        Remove-Item -LiteralPath $f.FullName -Force -ErrorAction SilentlyContinue
    }
}
exit 0
