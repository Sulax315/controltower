param(
    [string]$Python = "python",
    [string]$Config = "",
    [switch]$RetentionDryRun
)

$extraArgs = @()
if ($RetentionDryRun) {
    $extraArgs += "--retention-dry-run"
}

& (Join-Path $PSScriptRoot "Invoke-ControlTowerOperation.ps1") `
    -OperationName "daily" `
    -ScriptName "run_daily_controltower.py" `
    -Python $Python `
    -Config $Config `
    -ExtraArgs $extraArgs

exit $LASTEXITCODE
