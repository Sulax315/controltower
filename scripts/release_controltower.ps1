param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassThruArgs
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonWrapper = Join-Path $repoRoot "scripts\release_controltower.py"
$cliEntrypoint = Join-Path $repoRoot "run_controltower.py"
$statusPath = if ($env:CONTROLTOWER_RELEASE_STATUS_PATH) {
    $env:CONTROLTOWER_RELEASE_STATUS_PATH
} else {
    Join-Path $repoRoot ".controltower_runtime\release\latest_release_readiness.json"
}

if (-not (Test-Path $pythonWrapper)) {
    throw "Missing release wrapper: $pythonWrapper"
}

Write-Warning "release_controltower.ps1 is a compatibility wrapper. Use bash .\infra\deploy\controltower\deploy_update.sh as the authoritative release command."
& python $pythonWrapper @PassThruArgs
$releaseExitCode = $LASTEXITCODE

Write-Host "Notification attempt: $statusPath"
$previousPythonPath = $env:PYTHONPATH
$srcRoot = Join-Path $repoRoot "src"
if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH = $srcRoot
} else {
    $env:PYTHONPATH = "$srcRoot;$previousPythonPath"
}

try {
    & python -m controltower.services.notifications --status-path $statusPath
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Notification module returned exit code $LASTEXITCODE"
    }
    if (Test-Path $cliEntrypoint) {
        & python $cliEntrypoint approval-sync-release --status-path $statusPath
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Approval sync returned exit code $LASTEXITCODE"
        }
    }
} catch {
    Write-Warning "Notification attempt failed: $($_.Exception.Message)"
} finally {
    $env:PYTHONPATH = $previousPythonPath
}

exit $releaseExitCode
