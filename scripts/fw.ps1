# Firmware helper (addendum A7). Builds through a junction without spaces: C:\bcs-fw -> firmware\sentinelcam.
# Usage: scripts\fw.ps1 test|build|upload|upload-ota|monitor
# build/upload/upload-ota read BCS_CAMERA_TOKEN and BCS_CAMERA_OTA_PASSWORD from the environment or .env
# into this process only; values are never printed.
param([Parameter(Mandatory = $true, Position = 0)][ValidateSet('test', 'build', 'upload', 'upload-ota', 'monitor')][string]$Command)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'firmware\sentinelcam'
$link = 'C:\bcs-fw'
if (-not (Test-Path -LiteralPath $link)) {
    New-Item -ItemType Junction -Path $link -Target $src | Out-Null
}
if ($Command -in 'build', 'upload', 'upload-ota') {
    . (Join-Path $PSScriptRoot 'dotenv.ps1')
    foreach ($name in 'BCS_CAMERA_TOKEN', 'BCS_CAMERA_OTA_PASSWORD') {
        if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
            $v = Get-DotEnvValue (Join-Path $root '.env') $name
            if ($v) { [Environment]::SetEnvironmentVariable($name, $v, 'Process') }
        }
        if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) { throw "$name is missing from the environment and .env" }
    }
}
Push-Location $link
try {
    switch ($Command) {
        'test'       { & pio test -e native }
        'build'      { & pio run -e sentinelcam }
        'upload'     { & pio run -e sentinelcam -t upload }
        'upload-ota' { & pio run -e sentinelcam-ota -t upload }
        'monitor'    { & pio device monitor }
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
