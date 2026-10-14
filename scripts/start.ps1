# Blue Carbon Sentinel launcher (addendum D2). Windows PowerShell 5.1 compatible.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start.ps1 [-NoWindows]
# Steps: port checks, broker, Ground Station, simulator, readiness (60 s), Chrome windows, preflight summary.
param([switch]$NoWindows)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Var = Join-Path $Root 'var'
$RunDir = Join-Path $Var 'run'
$LogDir = Join-Path $Var 'logs'
$GsUrl = 'http://127.0.0.1:8700'
$SimUrl = 'http://127.0.0.1:8701'
$ReadySeconds = 60

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# 0. .env: read only the non-secret values this script needs. Nothing is exported, so no secret is
#    inherited by Mosquitto or Chrome; the Ground Station and the simulator read .env themselves.
. (Join-Path $PSScriptRoot 'dotenv.ps1')
$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host 'Warning: .env not found; copy .env.example to .env and fill it in.'
}

function Get-ListenPids([int]$Port) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($null -eq $conns) { return @() }
    return @($conns | Select-Object -ExpandProperty OwningProcess -Unique)
}

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

function Get-OurPids {
    $ours = @()
    foreach ($f in Get-ChildItem -LiteralPath $RunDir -Filter '*.pid' -ErrorAction SilentlyContinue) {
        $n = Test-OurPidFile $f
        if ($n -gt 0) { $ours += $n }
    }
    return $ours
}

# Returns free, ours or foreign.
function Get-PortOwner([int]$Port) {
    $owners = Get-ListenPids $Port
    if ($owners.Count -eq 0) { return 'free' }
    $ours = Get-OurPids
    foreach ($p in $owners) { if ($ours -notcontains $p) { return 'foreign' } }
    return 'ours'
}

function Find-Mosquitto {
    $cmd = Get-Command mosquitto.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $p = 'C:\Program Files\mosquitto\mosquitto.exe'
    if (Test-Path -LiteralPath $p) { return $p }
    return $null
}

function Find-Chrome {
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe') }
    $pf86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
    if ($pf86) { $candidates += (Join-Path $pf86 'Google\Chrome\Application\chrome.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe') }
    foreach ($c in $candidates) { if ($c -and (Test-Path -LiteralPath $c)) { return $c } }
    return $null
}

function Test-Http([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

# 1. Port checks: free, or already held by our own processes.
$sw = [Diagnostics.Stopwatch]::StartNew()
$brokerPort = 1883
$brokerPortText = $env:BCS_BROKER_PORT
if (-not $brokerPortText) { $brokerPortText = Get-DotEnvValue $EnvFile 'BCS_BROKER_PORT' }
if ($brokerPortText) { $brokerPort = [int]$brokerPortText }
$state = @{}
foreach ($spec in @(@('broker', $brokerPort), @('gs', 8700), @('sim', 8701))) {
    $name = $spec[0]; $port = $spec[1]
    $state[$name] = Get-PortOwner $port
    if ($state[$name] -eq 'foreign') {
        if ($name -eq 'broker') {
            Write-Host "Port $port is held by another program. If the Windows Mosquitto service is running, stop and disable the Mosquitto service (Services -> Mosquitto Broker -> Stop, Startup type Disabled), then run this script again."
        } else {
            Write-Host "Port $port is held by another program. Close it, then run this script again."
        }
        exit 1
    }
}

function Start-Child([string]$Name, [string]$File, [string[]]$ArgList) {
    $out = Join-Path $LogDir "$Name.out.log"
    $err = Join-Path $LogDir "$Name.err.log"
    $p = Start-Process -FilePath $File -ArgumentList $ArgList -WorkingDirectory $Root -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    Set-Content -LiteralPath (Join-Path $RunDir "$Name.pid") -Value $p.Id -Encoding Ascii
}

# Replace a launcher's pid by the pid that actually listens (uv and venv shims sit in between).
function Update-Pid([string]$Name, [int]$Port) {
    $owners = Get-ListenPids $Port
    if ($owners.Count -gt 0) {
        Set-Content -LiteralPath (Join-Path $RunDir "$Name.pid") -Value $owners[0] -Encoding Ascii
    }
}

# 2. Broker.
if ($state['broker'] -eq 'free') {
    $conf = Join-Path $Var 'mosquitto\mosquitto.conf'
    if (-not (Test-Path -LiteralPath $conf)) {
        Write-Host 'The broker is not set up. Run scripts\setup.ps1 first (it runs bcs-gs broker-init).'
        exit 1
    }
    $mosq = Find-Mosquitto
    if (-not $mosq) {
        Write-Host 'mosquitto.exe was not found. Install Mosquitto (C:\Program Files\mosquitto) or add it to PATH.'
        exit 1
    }
    Start-Child 'mosquitto' $mosq @('-c', ('"' + $conf + '"'))
}

# 3. Ground Station (retries until the broker is up).
if ($state['gs'] -eq 'free') {
    Start-Child 'gs' 'uv' @('run', 'bcs-gs', 'run')
}

# 4. Simulator.
if ($state['sim'] -eq 'free') {
    Start-Child 'sim' 'uv' @('run', 'bcs-sim', 'run')
}

# 5. Readiness: up to 60 s for the Ground Station status and the simulator state.
$deadline = (Get-Date).AddSeconds($ReadySeconds)
$ready = $false
while ((Get-Date) -lt $deadline) {
    if ((Test-Http "$GsUrl/api/v1/system/status") -and (Test-Http "$SimUrl/api/v1/state")) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    Write-Host "Not ready after $ReadySeconds s. See the logs in var\logs (gs.err.log, sim.err.log, mosquitto.err.log). Run scripts\stop.ps1 to clean up."
    exit 1
}
Update-Pid 'mosquitto' $brokerPort
Update-Pid 'gs' 8700
Update-Pid 'sim' 8701
Write-Host ("Ready in {0:N1} s." -f $sw.Elapsed.TotalSeconds)

# 6. Chrome app windows.
if (-not $NoWindows) {
    $chrome = Find-Chrome
    if ($chrome) {
        Start-Process -FilePath $chrome -ArgumentList @("--app=$GsUrl/", '--window-size=1920,1080')
        Start-Process -FilePath $chrome -ArgumentList @("--app=$GsUrl/console/", '--window-size=1920,1080')
    } else {
        Write-Host "Chrome was not found. Open $GsUrl/ and $GsUrl/console/ in a browser."
    }
}

# 7. Preflight summary (a fresh run; the first scheduled run may be a few seconds old).
try {
    $report = Invoke-RestMethod -Uri "$GsUrl/api/v1/system/preflight" -Method Post -TimeoutSec 30
    Write-Host 'Preflight:'
    foreach ($c in $report.checks) {
        $line = '  {0,-4}  {1,-14} {2}' -f $c.status, $c.id, $c.detail
        Write-Host $line
        if ($c.status -ne 'pass' -and $c.fix_hint) { Write-Host ('        hint: ' + $c.fix_hint) }
    }
} catch {
    Write-Host 'Preflight summary unavailable.'
}
exit 0
