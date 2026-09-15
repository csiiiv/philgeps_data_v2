[CmdletBinding()]
param(
    [string]$SourceList = "RAW_DATA_DOWNLOADER\references\source_urls_4.txt",
    [switch]$SkipDownload,
    [switch]$ForceDownload,
    [switch]$FullSourceAudit,
    # Resume controls: skip expensive upstream rebuilds when their outputs
    # are already current (e.g. resuming after a failure downstream).
    [switch]$SkipNormalization,
    [switch]$SkipCleaning,
    [switch]$SkipCoreBuild,
    [switch]$ResumeCoreOcds,
    [int]$OcdsThreads = 4,
    [string]$OcdsMemoryLimit = "16GB",
    [string]$OcdsMaxTempSize = "100GB",
    [int]$OcdsProcessPartitions = 8,
    [switch]$SkipViewerBuild,
    [switch]$NoViewerRestart,
    [int]$ViewerPort = 8765
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = $PSScriptRoot
$downloaderDir = Join-Path $root "RAW_DATA_DOWNLOADER"
$normalizationDir = Join-Path $root "DATA_NORMALIZATION"
$ocdsDir = Join-Path $root "OCDS_ETL"
$viewerDir = Join-Path $root "PARQUET_VIEWER"
$sourceListPath = if ([System.IO.Path]::IsPathRooted($SourceList)) {
    $SourceList
} else {
    Join-Path $root $SourceList
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][scriptblock]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    $started = Get-Date
    Push-Location $WorkingDirectory
    try {
        & $Command
        if ($LASTEXITCODE -ne 0) {
            throw "$Name failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
    $elapsed = (Get-Date) - $started
    Write-Host ("Completed in {0:hh\:mm\:ss}" -f $elapsed) -ForegroundColor Green
}

if (-not $ResumeCoreOcds -and -not $SkipDownload) {
    if (-not (Test-Path -LiteralPath $sourceListPath)) {
        throw "Source list not found: $sourceListPath"
    }
    $downloadArgs = @(
        "scripts\download_gdrive_sources.py",
        $sourceListPath,
        "dataset"
    )
    if ($ForceDownload) {
        $downloadArgs += "--force"
    }
    Invoke-NativeStep "Download or resume source files" $downloaderDir {
        python @downloadArgs
    }
}

if (-not $ResumeCoreOcds) {
    Invoke-NativeStep "Rebuild provenance manifest" $downloaderDir {
        python scripts\rebuild_manifest.py dataset\manifest.json
    }

    $catalogArgs = @("scripts\build_source_catalog.py")
    if ($FullSourceAudit) {
        $catalogArgs += @("--verify-hashes", "--count-csv-rows")
    }
    Invoke-NativeStep "Build source catalog" $normalizationDir {
        python @catalogArgs
    }

    Invoke-NativeStep "Verify source schemas" $normalizationDir {
        python scripts\verify_schema.py
    }
}

if (-not $ResumeCoreOcds -and -not $SkipNormalization) {
    Invoke-NativeStep "Build normalized Parquet" $normalizationDir {
        python scripts\build_normalized_parquet.py --force
    }
} elseif ($ResumeCoreOcds) {
    Write-Host "Skipping normalization (-ResumeCoreOcds)" -ForegroundColor DarkGray
} else {
    Write-Host "Skipping normalization (-SkipNormalization)" -ForegroundColor DarkGray
}

if (-not $ResumeCoreOcds -and -not $SkipCleaning) {
    Invoke-NativeStep "Build cleaned Parquet" $normalizationDir {
        python scripts\build_cleaned_parquet.py --force
    }
} elseif ($ResumeCoreOcds) {
    Write-Host "Skipping cleaning (-ResumeCoreOcds)" -ForegroundColor DarkGray
} else {
    Write-Host "Skipping cleaning (-SkipCleaning)" -ForegroundColor DarkGray
}

Invoke-NativeStep "Validate OCDS mapping configuration" $ocdsDir {
    python scripts\validate_mapping_config.py
}

$coreArgs = @(
    "scripts\build_parquet.py",
    "--threads", "$OcdsThreads",
    "--memory-limit", $OcdsMemoryLimit,
    "--max-temp-size", $OcdsMaxTempSize,
    "--process-partitions", "$OcdsProcessPartitions",
    "--replace"
)

if ($ResumeCoreOcds) {
    $requiredResumeFiles = @(
        "outputs\.build\release_index.parquet",
        "outputs\parquet\releases.parquet"
    )
    foreach ($requiredFile in $requiredResumeFiles) {
        $requiredPath = Join-Path $ocdsDir $requiredFile
        if (-not (Test-Path -LiteralPath $requiredPath)) {
            throw "Cannot resume core OCDS build; required file is missing: $requiredPath"
        }
    }
    $coreArgs += @(
        "--tables",
        "contracting_processes", "tenders", "tender_items", "awards",
        "contracts", "parties", "party_roles", "award_items",
        "award_suppliers", "record_sources", "data_quality_issues"
    )
}

if (-not $SkipCoreBuild) {
    Invoke-NativeStep "Build core OCDS Parquet tables" $ocdsDir {
        python @coreArgs
    }
} else {
    Write-Host "Skipping core OCDS build (-SkipCoreBuild)" -ForegroundColor DarkGray
}

Invoke-NativeStep "Build party name forms" $ocdsDir {
    python scripts\build_party_name_forms.py
}

Invoke-NativeStep "Build party resolution candidates" $ocdsDir {
    python scripts\build_party_resolution_candidates.py
}

Invoke-NativeStep "Build canonical parties and aliases" $ocdsDir {
    python scripts\build_canonical_parties.py
}

Invoke-NativeStep "Build compiled process views" $ocdsDir {
    python scripts\build_compiled_processes.py
}

if (-not $SkipViewerBuild) {
    Invoke-NativeStep "Run viewer backend tests" $viewerDir {
        python -m unittest discover -s backend\tests -v
    }

    Invoke-NativeStep "Build viewer frontend" (Join-Path $viewerDir "frontend\app") {
        npm run build
    }
}

if (-not $NoViewerRestart) {
    Write-Host ""
    Write-Host "=== Restart viewer ===" -ForegroundColor Cyan
    & (Join-Path $viewerDir "scripts\stop_viewer.ps1")
    & (Join-Path $viewerDir "scripts\start_viewer.ps1") -Port $ViewerPort

    $healthUrl = "http://127.0.0.1:$ViewerPort/api/health"
    $healthy = $false
    for ($attempt = 1; $attempt -le 15; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
            Write-Host "Viewer health check passed: $healthUrl" -ForegroundColor Green
            $response | ConvertTo-Json -Depth 10
            $healthy = $true
            break
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    if (-not $healthy) {
        throw "Viewer did not become healthy at $healthUrl. Check PARQUET_VIEWER\.cache logs."
    }
}

Write-Host ""
Write-Host "Complete PhilGEPS ETL pipeline finished successfully." -ForegroundColor Green
