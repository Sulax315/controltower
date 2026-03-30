param(
    [string]$Python = "python",
    [string]$Config = "",
    [switch]$RefreshExport
)

$extraArgs = @()
if ($RefreshExport) {
    $extraArgs += "--refresh-export"
}

& (Join-Path $PSScriptRoot "Invoke-ControlTowerOperation.ps1") `
    -OperationName "smoke" `
    -ScriptName "smoke_controltower.py" `
    -Python $Python `
    -Config $Config `
    -ExtraArgs $extraArgs

exit $LASTEXITCODE
