# First-time setup (task 13). Windows PowerShell 5.1 compatible. Safe to run again.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

# .env is read, never exported wholesale: only the Supabase CLI step gets the two values it needs, and only
# for that step. Values are never printed.
. (Join-Path $PSScriptRoot 'dotenv.ps1')
$EnvFile = Join-Path $Root '.env'
if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host 'Warning: .env not found; copy .env.example to .env and fill it in.'
}

function Invoke-Step([string]$Title, [scriptblock]$Body) {
    Write-Host "== $Title"
    & $Body
    if ($LASTEXITCODE -ne 0) { Write-Host "Step failed: $Title (exit code $LASTEXITCODE)"; exit 1 }
}

Invoke-Step '1/6 uv sync --all-packages' { & uv sync --all-packages }

Invoke-Step '2/6 pnpm install' { & pnpm install }

# The web apps arrive in later milestones; build only when a workspace package defines a build script.
Invoke-Step '3/6 pnpm build' { & pnpm build }

Invoke-Step '4/6 broker-init' { & uv run bcs-gs broker-init }

Write-Host '== 5/6 Supabase'
# The project ref is the subdomain of BCS_SUPABASE_URL (https://<ref>.supabase.co).
$supabaseUrl = Get-DotEnvValue $EnvFile 'BCS_SUPABASE_URL'
if (-not ($supabaseUrl -match '^https://([a-z0-9-]+)\.supabase\.co')) {
    Write-Host 'BCS_SUPABASE_URL is not set in .env (expected https://<project-ref>.supabase.co); cannot link.'
    exit 1
}
$ref = $Matches[1]
$linked = Join-Path $Root 'supabase\.temp\project-ref'
if ((Test-Path -LiteralPath $linked) -and ((Get-Content -LiteralPath $linked -Raw).Trim() -eq $ref)) {
    Write-Host 'Already linked; skipping supabase link and db push.'
} else {
    $dbPassword = Get-DotEnvValue $EnvFile 'SUPABASE_DB_PASSWORD'
    if (-not $dbPassword) { Write-Host 'SUPABASE_DB_PASSWORD is not set in .env; cannot link.'; exit 1 }
    $accessToken = Get-DotEnvValue $EnvFile 'SUPABASE_ACCESS_TOKEN'
    $env:SUPABASE_DB_PASSWORD = $dbPassword
    if ($accessToken) { $env:SUPABASE_ACCESS_TOKEN = $accessToken }
    try {
        Invoke-Step 'supabase link' { & supabase link --project-ref $ref --yes }
        Invoke-Step 'supabase db push' { & supabase db push --yes }
    } finally {
        Remove-Item Env:SUPABASE_DB_PASSWORD -ErrorAction SilentlyContinue
        Remove-Item Env:SUPABASE_ACCESS_TOKEN -ErrorAction SilentlyContinue
        $dbPassword = $null
        $accessToken = $null
    }
}

Invoke-Step '6/6 fetch-models (about 250 MB, once)' { & uv run bcs-gs fetch-models }

Write-Host 'Setup complete. Start the stack with scripts\start.ps1'
exit 0
