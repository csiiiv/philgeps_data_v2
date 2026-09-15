param(
    [int]$Port = 8765
)

$project = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $project ".cache"
$pidFile = Join-Path $cache "viewer.pid"
$stdoutLog = Join-Path $cache "viewer.stdout.log"
$stderrLog = Join-Path $cache "viewer.stderr.log"

New-Item -ItemType Directory -Path $cache -Force | Out-Null

if (Test-Path -LiteralPath $pidFile) {
    $savedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($savedPid -and (Get-Process -Id $savedPid -ErrorAction SilentlyContinue)) {
        Write-Output "Viewer is already running (PID $savedPid): http://127.0.0.1:$Port"
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force
}

$process = Start-Process `
    -FilePath "pythonw.exe" `
    -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$Port") `
    -WorkingDirectory $project `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru

$process.Id | Set-Content -LiteralPath $pidFile
Start-Sleep -Seconds 2

if ($process.HasExited) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    $details = Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue
    throw "Viewer failed to start. $details"
}

Write-Output "Viewer started (PID $($process.Id)): http://127.0.0.1:$Port"
Write-Output "Logs: $stdoutLog and $stderrLog"
