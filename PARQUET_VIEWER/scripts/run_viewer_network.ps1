# Bind the PhilGEPS Parquet Viewer on all interfaces for LAN / VPS access.
# Default local scripts stay on 127.0.0.1; this is the opt-in network mode.
#
# Usage (from PARQUET_VIEWER, process-scoped Bypass is enough):
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_viewer_network.ps1
#
# Optional:
#   -Port 8765
#   -SettingsPath .\config\settings.vps-small.json

param(
    [int]$Port = 8765,
    [string]$SettingsPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($SettingsPath) {
    $env:PHILGEPS_SETTINGS = (Resolve-Path $SettingsPath).Path
}

$lanIps = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Select-Object -ExpandProperty IPAddress -Unique
)
$primaryLan = if ($lanIps.Count -gt 0) { $lanIps[0] } else { $null }
$hostName = $env:COMPUTERNAME

$extras = @($lanIps + @($hostName) | Where-Object { $_ } | Select-Object -Unique)
$env:PHILGEPS_EXTRA_ALLOWED_HOSTS = ($extras -join ",")

if (-not $env:PHILGEPS_CURSOR_SECRET) {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $env:PHILGEPS_CURSOR_SECRET = -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

Write-Host "PhilGEPS Parquet Viewer (network mode)"
Write-Host "  Bind:     0.0.0.0:$Port"
if ($primaryLan) {
    Write-Host "  Open:     http://${primaryLan}:$Port/"
}
Write-Host "  Hosts+:   $env:PHILGEPS_EXTRA_ALLOWED_HOSTS"
Write-Host "  Warning:  no authentication - anyone who can reach this port can query the data."
Write-Host ""

# Best-effort firewall rule (needs elevation; ignore failure).
try {
    $ruleName = "PhilGEPS Parquet Viewer $Port"
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -LocalPort $Port -Profile Any -ErrorAction Stop | Out-Null
        Write-Host "Firewall: allowed inbound TCP $Port"
    }
} catch {
    Write-Host "Firewall: could not add rule (run elevated once, or allow Python manually when prompted)."
}

python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $Port
