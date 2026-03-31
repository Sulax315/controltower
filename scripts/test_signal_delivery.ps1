param(
    [string]$EnvFile,
    [string]$HostMarker
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $repoRoot "scripts\send_test_signal.py"

if (-not (Test-Path $scriptPath)) {
    throw "Missing Signal test entrypoint: $scriptPath"
}

$args = @()
if ($EnvFile) {
    $args += "--env-file"
    $args += $EnvFile
}
if ($HostMarker) {
    $args += "--host-marker"
    $args += $HostMarker
}

& python $scriptPath @args
exit $LASTEXITCODE
