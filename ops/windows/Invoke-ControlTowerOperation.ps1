param(
    [Parameter(Mandatory = $true)]
    [string]$OperationName,
    [Parameter(Mandatory = $true)]
    [string]$ScriptName,
    [string]$Python = "python",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path,
    [string]$Config = "",
    [string[]]$ExtraArgs = @()
)

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH-mm-ssZ")
$logRoot = Join-Path $RepoRoot ".controltower_runtime\\logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

$stdoutLog = Join-Path $logRoot "$OperationName`_$timestamp.stdout.log"
$stderrLog = Join-Path $logRoot "$OperationName`_$timestamp.stderr.log"
$env:CONTROLTOWER_STDOUT_LOG = $stdoutLog
$env:CONTROLTOWER_STDERR_LOG = $stderrLog

$arguments = @((Join-Path $RepoRoot "scripts\\$ScriptName"))
if ($Config) {
    $arguments += @("--config", $Config)
}
if ($ExtraArgs) {
    $arguments += $ExtraArgs
}

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList $arguments `
    -WorkingDirectory $RepoRoot `
    -NoNewWindow `
    -Wait `
    -PassThru `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog

Write-Output "Operation: $OperationName"
Write-Output "ExitCode: $($process.ExitCode)"
Write-Output "StdoutLog: $stdoutLog"
Write-Output "StderrLog: $stderrLog"

exit $process.ExitCode
