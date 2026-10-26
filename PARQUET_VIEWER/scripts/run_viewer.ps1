# Local-only viewer (127.0.0.1). For LAN/VPS use run_viewer_network.ps1.
param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "PhilGEPS Parquet Viewer (local)"
Write-Host "  Open: http://127.0.0.1:$Port/"
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port $Port

