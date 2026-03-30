# Control Tower Weekly Ops

Use this skill when you need to run or verify recurring Control Tower workflows in `C:\Dev\ControlTower`.

## Primary Commands

Validate sources:

```powershell
python .\run_controltower.py validate-sources
```

Preview all notes:

```powershell
python .\run_controltower.py build-all
```

Write all notes to the configured vault:

```powershell
python .\run_controltower.py build-all --write
```

Rebuild one project dossier / brief:

```powershell
python .\run_controltower.py build-project --project <CANONICAL_PROJECT_CODE> --write
```

Smoke the browser/API and export pipeline:

```powershell
python .\run_controltower.py acceptance
```

## Operating Rules

- Treat ScheduleLab published artifacts and ProfitIntel snapshot tables as source of truth
- Do not modify source-system artifacts from this repo
- Prefer preview before write when source trust is partial or low
- If cross-system identity is wrong, update the project registry instead of hardcoding a merge

