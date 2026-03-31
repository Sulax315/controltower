param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PassThruArgs
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonWrapper = Join-Path $repoRoot "scripts\release_controltower.py"

if (-not (Test-Path $pythonWrapper)) {
    throw "Missing release wrapper: $pythonWrapper"
}

Write-Warning "release_controltower.ps1 is a compatibility wrapper. Use bash .\infra\deploy\controltower\deploy_update.sh as the authoritative release command."
& python $pythonWrapper @PassThruArgs
exit $LASTEXITCODE
