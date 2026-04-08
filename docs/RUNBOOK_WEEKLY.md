# Weekly Runbook

## Standard Weekly Flow

1. Validate source availability:

```powershell
python .\run_controltower.py validate-sources
```

2. Preview the full note set:

```powershell
python .\run_controltower.py build-all
```

3. Review browser views if needed:

```powershell
python .\run_controltower.py serve
```

4. Export into the real vault:

```powershell
python .\run_controltower.py build-all --write
```

5. Run the acceptance harness after meaningful integration changes:

```powershell
python .\run_controltower.py acceptance
```

## One-Project Refresh

```powershell
python .\run_controltower.py build-project --project SU_WAVERLY --write
```

## Real-Project Validation Loop

After generating a publishable run, execute the governed validation loop defined in:

- `docs/REAL_PROJECT_VALIDATION_RUNBOOK.md`

