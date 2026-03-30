# Windows Scheduler Pack

These wrappers execute the real Python operation scripts from the repo root and always redirect stdout/stderr to `.controltower_runtime/logs/`.

## Manual Invocation

```powershell
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerPreflight.ps1 -Config C:\Dev\ControlTower\controltower.yaml
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerDaily.ps1 -Config C:\Dev\ControlTower\controltower.yaml
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerWeekly.ps1 -Config C:\Dev\ControlTower\controltower.yaml
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerSmoke.ps1 -Config C:\Dev\ControlTower\controltower.yaml -RefreshExport
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerDiagnosticsSnapshot.ps1 -Config C:\Dev\ControlTower\controltower.yaml
powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerReleaseReadiness.ps1 -Config C:\Dev\ControlTower\controltower.yaml
```

## Task Scheduler Exact Command Lines

Program/script:

```text
powershell.exe
```

Add arguments for daily:

```text
-ExecutionPolicy Bypass -File C:\Dev\ControlTower\ops\windows\Invoke-ControlTowerDaily.ps1 -Config C:\Dev\ControlTower\controltower.yaml
```

Add arguments for weekly:

```text
-ExecutionPolicy Bypass -File C:\Dev\ControlTower\ops\windows\Invoke-ControlTowerWeekly.ps1 -Config C:\Dev\ControlTower\controltower.yaml
```

Add arguments for preflight:

```text
-ExecutionPolicy Bypass -File C:\Dev\ControlTower\ops\windows\Invoke-ControlTowerPreflight.ps1 -Config C:\Dev\ControlTower\controltower.yaml
```

Start in:

```text
C:\Dev\ControlTower
```

Suggested schedule:

- Daily task: weekdays at the start of the operator morning window.
- Weekly task: once per week after upstream ScheduleLab/ProfitIntel publications are expected to be complete.
- Preflight task: 10-15 minutes before the scheduled daily/weekly task if you want a separate early warning.

Log outputs land at:

- `.controltower_runtime/logs/daily_<timestamp>.stdout.log`
- `.controltower_runtime/logs/daily_<timestamp>.stderr.log`
- `.controltower_runtime/logs/weekly_<timestamp>.stdout.log`
- `.controltower_runtime/logs/weekly_<timestamp>.stderr.log`

Each Python operation also writes a machine-readable summary JSON under `.controltower_runtime/operations/history/`.
