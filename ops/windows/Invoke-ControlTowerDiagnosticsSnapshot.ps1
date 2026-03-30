param(
    [string]$Python = "python",
    [string]$Config = ""
)

& (Join-Path $PSScriptRoot "Invoke-ControlTowerOperation.ps1") `
    -OperationName "diagnostics_snapshot" `
    -ScriptName "diagnostics_snapshot_controltower.py" `
    -Python $Python `
    -Config $Config

exit $LASTEXITCODE
