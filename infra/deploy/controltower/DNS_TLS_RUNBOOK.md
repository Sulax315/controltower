# Control Tower DNS/TLS Cutover Playbook

Scope: Windows workstation remediation for `controltower.bratek.io`.

Known-good state:

- Live edge IPv4: `161.35.177.158`
- Public resolvers `1.1.1.1` and `8.8.8.8` return `161.35.177.158`
- Current stale workstation answers:
  - `A 208.91.112.55`
  - `AAAA 2620:101:9000:53::55`
- Direct forced-edge HTTPS to `161.35.177.158` is healthy

Treat this as a local DNS problem unless the forced-edge test stops returning HTTP `200`.

## 1. Verify The Diagnosis

Run from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1
```

Expected bad-local-DNS result:

```text
DIAGNOSIS: EDGE HEALTHY / LOCAL DNS BAD
RESULT: FAIL
NEXT COMMAND:
Set-DnsClientServerAddress -InterfaceIndex <N> -ServerAddresses 1.1.1.1,1.0.0.1
```

Only continue with workstation DNS remediation when:

- public resolvers show `161.35.177.158`
- forced `GET` via `--resolve` returns HTTP `200`
- the verifier says `EDGE HEALTHY / LOCAL DNS BAD`

## 2. Preferred Cutover In An Elevated PowerShell Window

Open an elevated PowerShell window in `C:\Dev\ControlTower`, then run this block:

```powershell
$active = Get-NetIPConfiguration |
    Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } |
    Select-Object -First 1 InterfaceAlias, InterfaceIndex, IPv4Address, IPv4DefaultGateway

$active

Set-DnsClientServerAddress -InterfaceIndex $active.InterfaceIndex -ServerAddresses 1.1.1.1,1.0.0.1
ipconfig /flushdns
Resolve-DnsName controltower.bratek.io
powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1 -SkipFlushDns
```

Exact elevated interface-identification command:

```powershell
Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq 'Up' } | Select-Object InterfaceAlias, InterfaceIndex, IPv4Address, IPv4DefaultGateway
```

Exact elevated DNS-switch command:

```powershell
Set-DnsClientServerAddress -InterfaceIndex <INTERFACE_INDEX> -ServerAddresses 1.1.1.1,1.0.0.1
```

Exact flush and retest commands:

```powershell
ipconfig /flushdns
Resolve-DnsName controltower.bratek.io
powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1 -SkipFlushDns
```

Success means the verifier ends with:

```text
DIAGNOSIS: EDGE HEALTHY / LOCAL DNS GOOD
RESULT: PASS
```

## 3. Proof-Only Hosts Override If DNS Change Is Blocked

Use this only to prove browser access. It does not fix workstation DNS, and the verifier should still fail until the resolver is corrected.

Exact elevated proof-only override block:

```powershell
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
Add-Content -Path $hosts -Value "`r`n161.35.177.158 controltower.bratek.io"
ipconfig /flushdns
curl.exe -sS -D - -o NUL https://controltower.bratek.io/
```

Exact cleanup block:

```powershell
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
(Get-Content $hosts) | Where-Object { $_ -notmatch 'controltower\.bratek\.io' } | Set-Content $hosts
ipconfig /flushdns
```

## 4. Reset To DHCP-Provided DNS After The Incident

Run in an elevated PowerShell window:

```powershell
Set-DnsClientServerAddress -InterfaceIndex <INTERFACE_INDEX> -ResetServerAddresses
ipconfig /flushdns
```

## 5. IT Escalation

Escalate to internal IT or the team that owns workstation DNS when the Windows default resolver still returns the stale records below after cutover attempts:

- Stale `A`: `208.91.112.55`
- Stale `AAAA`: `2620:101:9000:53::55`
- Correct `A`: `161.35.177.158`

Escalation note:

```text
Windows workstation DNS for controltower.bratek.io is stale.
Current stale answers:
- A 208.91.112.55
- AAAA 2620:101:9000:53::55

Correct live answer:
- A 161.35.177.158

Public resolvers 1.1.1.1 and 8.8.8.8 already return 161.35.177.158.
Please update or bypass the internal/default DNS path so the workstation stops resolving the parked-domain records.
```

## 6. Stop Conditions

Do not change application code, nginx, or VM settings unless this line stops being true:

```text
GET via --resolve to 161.35.177.158 returns HTTP/1.1 200 OK
```
