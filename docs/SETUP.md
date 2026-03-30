# Setup Guide

## Prerequisites

- Windows machine
- Python 3.12+
- Access to neighboring repos:
  - `C:\Dev\ScheduleLab\schedule_validator`
  - `C:\Dev\ProfitIntel`

## Install

```powershell
cd C:\Dev\ControlTower
py -3 -m pip install -e .[dev]
```

## Initial Validation

```powershell
python .\run_controltower.py validate-sources
python .\run_controltower.py build-all
python .\run_controltower.py acceptance
```

## Optional Project Identity Registry

If ScheduleLab and ProfitIntel refer to the same project with different keys, create a registry file and point config at it:

```yaml
projects:
  - canonical_project_code: AURORA_HILLS
    project_name: Aurora Hills
    aliases:
      schedulelab: AURORA_HILLS
      profitintel: 219128
```

