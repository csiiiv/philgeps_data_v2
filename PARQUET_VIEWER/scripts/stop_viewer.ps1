$project = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $project ".cache\viewer.pid"

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Output "No viewer PID file found."
    exit 0
}

$savedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
$process = if ($savedPid) { Get-Process -Id $savedPid -ErrorAction SilentlyContinue }

if ($process) {
    Stop-Process -Id $savedPid -Force
    Write-Output "Viewer stopped (PID $savedPid)."
} else {
    Write-Output "Viewer was not running."
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
