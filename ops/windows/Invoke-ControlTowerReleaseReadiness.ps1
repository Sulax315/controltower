param(
    [string]$Python = "python",
    [string]$Config = "",
    [switch]$SkipPytest,
    [switch]$SkipAcceptance
)

$extraArgs = @()
if ($SkipPytest) {
    $extraArgs += "--skip-pytest"
}
if ($SkipAcceptance) {
    $extraArgs += "--skip-acceptance"
}

& (Join-Path $PSScriptRoot "Invoke-ControlTowerOperation.ps1") `
    -OperationName "release_readiness" `
    -ScriptName "release_readiness_controltower.py" `
    -Python $Python `
    -Config $Config `
    -ExtraArgs $extraArgs

exit $LASTEXITCODE
