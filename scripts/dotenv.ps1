# Minimal .env reader shared by start.ps1 and setup.ps1. Windows PowerShell 5.1 compatible.
# Dot-source it, then ask for one value at a time. Nothing is exported and no value is ever printed:
# the Ground Station and the simulator read .env themselves.
#
# Matches the format scripts\migrate_keys.py writes (and python-dotenv reads):
#   NAME=value             unquoted; a " #" starts a trailing comment
#   NAME="va\"l\\ue"       double quotes; \" -> "  and  \\ -> \  (other backslashes stay as they are)
#   NAME='value'           single quotes; taken literally
# A later line for the same name wins. Returns $null when the file or the name is missing.

function ConvertFrom-DotEnvDoubleQuoted([string]$Inner) {
    $sb = New-Object System.Text.StringBuilder
    $i = 0
    while ($i -lt $Inner.Length) {
        $c = $Inner[$i]
        if ($c -eq '\' -and ($i + 1) -lt $Inner.Length) {
            $n = $Inner[$i + 1]
            if ($n -eq '\' -or $n -eq '"') {
                [void]$sb.Append($n)
                $i += 2
                continue
            }
        }
        [void]$sb.Append($c)
        $i += 1
    }
    return $sb.ToString()
}

function Get-DotEnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $found = $null
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        if ($t.StartsWith('export ')) { $t = $t.Substring(7).TrimStart() }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        if ($t.Substring(0, $i).Trim() -cne $Name) { continue }
        $value = $t.Substring($i + 1).Trim()
        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = ConvertFrom-DotEnvDoubleQuoted $value.Substring(1, $value.Length - 2)
        } elseif ($value.Length -ge 2 -and $value.StartsWith("'") -and $value.EndsWith("'")) {
            $value = $value.Substring(1, $value.Length - 2)
        } else {
            $hash = $value.IndexOf(' #')
            if ($hash -ge 0) { $value = $value.Substring(0, $hash).TrimEnd() }
        }
        $found = $value
    }
    return $found
}
