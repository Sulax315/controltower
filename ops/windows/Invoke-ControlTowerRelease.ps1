param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassThruArgs
)

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$scriptPath = Join-Path $repoRoot "scripts\release_controltower.ps1"

if (-not (Test-Path $scriptPath)) {
    throw "Missing authoritative release entrypoint: $scriptPath"
}

Write-Warning "Invoke-ControlTowerRelease.ps1 is a compatibility wrapper. Use bash .\infra\deploy\controltower\deploy_update.sh as the authoritative release command."
& $scriptPath @PassThruArgs
exit $LASTEXITCODE
