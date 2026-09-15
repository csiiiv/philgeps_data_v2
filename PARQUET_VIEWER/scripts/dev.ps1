# Development launcher: runs FastAPI (API host) and Vite (UI dev server) together.
# Vite serves http://127.0.0.1:5173 and proxies /api to FastAPI on 8765.
param(
    [int]$ApiPort = 8765,
    [int]$UiPort = 5173
)

$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project

$api = Start-Process `
    -FilePath "python" `
    -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--reload") `
    -WorkingDirectory $project `
    -PassThru

Set-Location -LiteralPath (Join-Path $project "frontend\app")
$ui = Start-Process `
    -FilePath "npm" `
    -ArgumentList @("run", "dev", "--", "--port", "$UiPort") `
    -WorkingDirectory (Join-Path $project "frontend\app") `
    -PassThru

Write-Output "FastAPI: http://127.0.0.1:$ApiPort (API only)"
Write-Output "Vite UI: http://127.0.0.1:$UiPort (open this one)"
Write-Output "API PID $($api.Id), UI PID $($ui.Id). Ctrl+C here does not stop them;"
Write-Output "stop with: Stop-Process -Id $($api.Id),$($ui.Id)"
