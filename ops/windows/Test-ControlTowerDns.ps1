[CmdletBinding()]
param(
    [string]$Domain = "controltower.bratek.io",
    [string]$ExpectedIPv4 = "161.35.177.158",
    [string]$ParkedIPv4 = "208.91.112.55",
    [string]$ParkedIPv6 = "2620:101:9000:53::55",
    [switch]$SkipFlushDns
)

$ErrorActionPreference = "Stop"
$PublicResolvers = @(
    @{ Label = "Cloudflare"; Server = "1.1.1.1" },
    @{ Label = "Google"; Server = "8.8.8.8" }
)

function Write-Step {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Gray
}

function Get-IpAnswers {
    param(
        [string]$Name,
        [ValidateSet("A", "AAAA")]
        [string]$RecordType,
        [string]$Server
    )

    try {
        $params = @{
            Name        = $Name
            Type        = $RecordType
            ErrorAction = "Stop"
        }

        if ($Server) {
            $params.Server = $Server
        }

        return @(
            Resolve-DnsName @params |
                Where-Object { $_.Type -eq $RecordType } |
                Select-Object -ExpandProperty IPAddress
        )
    }
    catch {
        return @()
    }
}

function Get-ResolverSnapshot {
    param(
        [string]$Name,
        [string]$Label,
        [string]$Server
    )

    [pscustomobject]@{
        Label  = $Label
        Server = if ($Server) { $Server } else { "system default" }
        A      = @(Get-IpAnswers -Name $Name -RecordType A -Server $Server) | Sort-Object -Unique
        AAAA   = @(Get-IpAnswers -Name $Name -RecordType AAAA -Server $Server) | Sort-Object -Unique
    }
}

function Show-ResolverSnapshot {
    param([pscustomobject]$Snapshot)

    Write-Host "$($Snapshot.Label) [$($Snapshot.Server)]" -ForegroundColor White
    Write-Host "  A:    $(if ($Snapshot.A.Count) { $Snapshot.A -join ', ' } else { '(none)' })"
    Write-Host "  AAAA: $(if ($Snapshot.AAAA.Count) { $Snapshot.AAAA -join ', ' } else { '(none)' })"
}

function Invoke-ForcedEdgeRequest {
    param(
        [ValidateSet("HEAD", "GET")]
        [string]$Method,
        [string]$Name,
        [string]$IPAddress
    )

    if ($Method -eq "HEAD") {
        $arguments = @(
            "-sS",
            "-I",
            "--connect-timeout", "10",
            "--max-time", "20",
            "--resolve", "$Name`:443`:$IPAddress",
            "https://$Name/"
        )
    }
    else {
        $arguments = @(
            "-sS",
            "-D", "-",
            "-o", "NUL",
            "--connect-timeout", "10",
            "--max-time", "20",
            "--resolve", "$Name`:443`:$IPAddress",
            "https://$Name/"
        )
    }

    $previousNativeErrorBehavior = $null
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
        $previousNativeErrorBehavior = $global:PSNativeCommandUseErrorActionPreference
        $global:PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        $output = & curl.exe @arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($null -ne $previousNativeErrorBehavior) {
            $global:PSNativeCommandUseErrorActionPreference = $previousNativeErrorBehavior
        }
    }

    $statusLine = @($output | Where-Object { $_ -match '^HTTP/' })[-1]
    $statusCode = $null

    if ($statusLine -match '^HTTP/\S+\s+(\d{3})') {
        $statusCode = [int]$Matches[1]
    }

    [pscustomobject]@{
        Method     = $Method
        ExitCode   = $exitCode
        StatusLine = $statusLine
        StatusCode = $statusCode
        Output     = @($output)
    }
}

function Show-ForcedEdgeResult {
    param([pscustomobject]$Result)

    Write-Host "$($Result.Method) via --resolve to $ExpectedIPv4" -ForegroundColor White
    if ($Result.Output.Count) {
        $Result.Output | Out-Host
    }
    else {
        Write-Host "(no output)"
    }
}

function Get-ActiveInterface {
    $candidates = @(
        Get-NetIPConfiguration |
            Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } |
            Sort-Object InterfaceIndex
    )

    if ($candidates.Count -gt 0) {
        return $candidates[0]
    }

    return $null
}

function Get-NextCommands {
    param(
        [string]$DomainName,
        [string]$ExpectedAddress,
        [string]$Mode
    )

    $activeInterface = Get-ActiveInterface

    switch ($Mode) {
        "SwitchDns" {
            if ($activeInterface) {
                return @(
                    "Set-DnsClientServerAddress -InterfaceIndex $($activeInterface.InterfaceIndex) -ServerAddresses 1.1.1.1,1.0.0.1",
                    "ipconfig /flushdns",
                    "Resolve-DnsName $DomainName",
                    "powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1 -SkipFlushDns"
                )
            }

            return @(
                "Get-NetIPConfiguration | Where-Object { `$_.IPv4DefaultGateway -ne `$null -and `$_.NetAdapter.Status -eq 'Up' } | Select-Object InterfaceAlias, InterfaceIndex, IPv4Address, IPv4DefaultGateway",
                "Set-DnsClientServerAddress -InterfaceIndex <INTERFACE_INDEX> -ServerAddresses 1.1.1.1,1.0.0.1",
                "ipconfig /flushdns",
                "powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1 -SkipFlushDns"
            )
        }
        "Browser" {
            return @(
                "Start-Process https://$DomainName/"
            )
        }
        default {
            return @()
        }
    }
}

function Write-DecisionBlock {
    param(
        [string]$Diagnosis,
        [ValidateSet("PASS", "FAIL")]
        [string]$Result,
        [string[]]$NextCommands,
        [string[]]$Notes
    )

    Write-Host ""
    Write-Host "DIAGNOSIS: $Diagnosis" -ForegroundColor White

    if ($Result -eq "PASS") {
        Write-Host "RESULT: PASS" -ForegroundColor Green
    }
    else {
        Write-Host "RESULT: FAIL" -ForegroundColor Red
    }

    if ($NextCommands.Count -gt 0) {
        Write-Host "NEXT COMMAND:" -ForegroundColor Yellow
        Write-Host $NextCommands[0] -ForegroundColor Yellow

        if ($NextCommands.Count -gt 1) {
            Write-Host "THEN:" -ForegroundColor Yellow
            foreach ($command in $NextCommands | Select-Object -Skip 1) {
                Write-Host $command -ForegroundColor Yellow
            }
        }
    }

    foreach ($note in $Notes) {
        Write-Host $note -ForegroundColor Gray
    }
}

if (-not $SkipFlushDns) {
    Write-Step "Flush Resolver Cache"
    ipconfig /flushdns | Out-Host
}

$localSnapshot = Get-ResolverSnapshot -Name $Domain -Label "Local resolver" -Server ""
$publicSnapshots = foreach ($resolver in $PublicResolvers) {
    Get-ResolverSnapshot -Name $Domain -Label "$($resolver.Label) public resolver" -Server $resolver.Server
}

Write-Step "Resolved Answers"
Show-ResolverSnapshot -Snapshot $localSnapshot
foreach ($snapshot in $publicSnapshots) {
    Show-ResolverSnapshot -Snapshot $snapshot
}

$headResult = Invoke-ForcedEdgeRequest -Method HEAD -Name $Domain -IPAddress $ExpectedIPv4
$getResult = Invoke-ForcedEdgeRequest -Method GET -Name $Domain -IPAddress $ExpectedIPv4

Write-Step "Forced Edge Reachability"
Write-Info "HEAD may return 405 because the app allows GET only. GET must return 200 to prove the live edge."
Show-ForcedEdgeResult -Result $headResult
Show-ForcedEdgeResult -Result $getResult

$localA = @($localSnapshot.A)
$localAAAA = @($localSnapshot.AAAA)
$publicA = @($publicSnapshots | ForEach-Object { $_.A }) | Sort-Object -Unique
$localHasExpected = $localA -contains $ExpectedIPv4
$localHasParkedIPv4 = $localA -contains $ParkedIPv4
$localHasParkedIPv6 = $localAAAA -contains $ParkedIPv6
$publicHasExpected = $publicA -contains $ExpectedIPv4
$edgeHeadLooksHealthy = ($headResult.ExitCode -eq 0) -and ($headResult.StatusCode -eq 405)
$edgeGetLooksHealthy = ($getResult.ExitCode -eq 0) -and ($getResult.StatusCode -eq 200)

Write-Step "Decision"
Write-Info "Expected IPv4: $ExpectedIPv4"
Write-Info "Parked IPv4:   $ParkedIPv4"
Write-Info "Parked IPv6:   $ParkedIPv6"

if (-not $publicHasExpected) {
    Write-DecisionBlock -Diagnosis "PUBLIC DNS BAD" -Result "FAIL" -NextCommands @(
        "nslookup $Domain 1.1.1.1",
        "nslookup $Domain 8.8.8.8"
    ) -Notes @(
        "Public resolvers are not returning $ExpectedIPv4.",
        "Stop workstation-only remediation and inspect authoritative DNS."
    )
    exit 4
}

if (-not $edgeGetLooksHealthy) {
    $notes = @(
        "Direct HTTPS GET to $ExpectedIPv4 via --resolve did not return 200.",
        "Stop DNS remediation and inspect the production edge."
    )

    if ($edgeHeadLooksHealthy) {
        $notes += "HEAD still reached the live edge, but GET did not return 200."
    }

    Write-DecisionBlock -Diagnosis "EDGE UNHEALTHY" -Result "FAIL" -NextCommands @(
        "Get-Content -Raw .\infra\deploy\controltower\DNS_TLS_RUNBOOK.md"
    ) -Notes $notes
    exit 5
}

if ($localHasParkedIPv4 -or $localHasParkedIPv6) {
    Write-DecisionBlock -Diagnosis "EDGE HEALTHY / LOCAL DNS BAD" -Result "FAIL" -NextCommands (
        Get-NextCommands -DomainName $Domain -ExpectedAddress $ExpectedIPv4 -Mode "SwitchDns"
    ) -Notes @(
        "Local DNS is still returning parked records.",
        "Stale IPv4: $ParkedIPv4",
        "Stale IPv6: $ParkedIPv6",
        "Correct IPv4: $ExpectedIPv4",
        "If DNS changes are blocked, use the proof-only hosts override from the runbook."
    )
    exit 2
}

if (-not $localHasExpected) {
    Write-DecisionBlock -Diagnosis "EDGE HEALTHY / LOCAL DNS BAD" -Result "FAIL" -NextCommands (
        Get-NextCommands -DomainName $Domain -ExpectedAddress $ExpectedIPv4 -Mode "SwitchDns"
    ) -Notes @(
        "Local DNS does not include the expected Control Tower IP.",
        "Correct IPv4: $ExpectedIPv4"
    )
    exit 3
}

Write-DecisionBlock -Diagnosis "EDGE HEALTHY / LOCAL DNS GOOD" -Result "PASS" -NextCommands (
    Get-NextCommands -DomainName $Domain -ExpectedAddress $ExpectedIPv4 -Mode "Browser"
) -Notes @(
    "Local DNS resolves to the live Control Tower edge and forced-edge HTTPS returned 200.",
    "If the browser still looks stale, close old tabs and verify the browser is not pinned to a custom DNS-over-HTTPS profile."
)
exit 0
