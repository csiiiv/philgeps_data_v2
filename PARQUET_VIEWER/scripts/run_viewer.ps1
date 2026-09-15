param(
    [int]$Port = 8765
)

$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port
