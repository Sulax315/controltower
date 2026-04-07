# Phase 2C — Parse validation evidence

## Chronology (factual)

1. **Authoritative column contract** was captured in `build_control/07_ASTA_CSV_COLUMN_MAPPING.md` and implemented in `src/controltower/schedule_intake/asta_csv.py`.
2. **Automated tests** were added (`tests/test_schedule_intake_asta.py`), including integration against a committed **authoritative-shape fixture** (`tests/fixtures/asta_export_authoritative_fixture.csv`) so CI always exercises the parser without requiring a customer file in git.
3. **Harness** (`python -m controltower.schedule_intake.harness <path.csv>`) was used to print parse counts, sample activities, and parser warnings.
4. **Real CSV validation** was executed by the operator against an actual Asta export (path held outside the repo or in a local-only location). The parser **completed without crashing**, produced a **parse summary** (activity count, predecessor/successor/critical counts, sample rows), and emitted **row-level warnings** where fields were malformed or non-numeric duration/date tokens failed to parse.
5. **Duration-format limitation:** mixed literals (`Xd`, `Xd Ys`, `Xs`) are not fully normalized; the parser may log warnings for those cells. This is **documented** and deferred; it did **not** block accepting Phase 2C.

## Harness command

From repository root (package on `PYTHONPATH`):

```text
set PYTHONPATH=src
python -m controltower.schedule_intake.harness tests/fixtures/asta_export_authoritative_fixture.csv
```

(Replace the path with your real export when reproducing operator validation.)

## Captured summary (committed fixture — regression baseline)

This run is reproducible in CI and matches the same column contract as the real export.

- **Parsed activities:** 6 (7 data lines; 1 row skipped — missing `Task ID`)
- **Warnings:** `row 5: cannot parse 'Start' as date ('bad-date')`; `row 6: skipped - missing Task ID`
- **With predecessors:** 5
- **With successors:** 3
- **Critical (True):** 1

Example row (`task_id=100`): dates `M/D/YYYY`, durations as days (`10d` → `10.0`), quoted task name with comma preserved, predecessors `['99']`, successors `['101','102']`, `percent_complete` 45.0.

## Real CSV validation (operator)

- Parser **did not crash** on the real export.
- **Parse summary** was produced via the harness (counts and samples).
- **Warnings** included, among others, cells that expose the **duration-format limitation** below.
- A full copy of the production CSV is **not** committed here; governance (`state.json`, `06_STATUS_BOARD.md`) records Phase 2C as **COMPLETE** on the basis of that successful run.

## Automated tests

- Module: `tests/test_schedule_intake_asta.py`
- Parser: `src/controltower/schedule_intake/asta_csv.py`
- Model: `src/controltower/schedule_intake/models.py`

## Track 2C checklist — final

| Criterion | Result |
|-----------|--------|
| Parser runs on real CSV without crashing | **YES** (operator run) |
| Parse count reasonable vs rows | **YES** |
| Malformed / bad rows handled or reported | **YES** (warnings; bad rows skipped or fields nulled) |
| Parse summary produced | **YES** |
| Duration / edge literals surfaced via warnings | **YES** (known limitation below) |

**Phase 2C status:** **COMPLETE** (accepted).

---

## NOTE — Duration parsing limitation observed

Asta export includes mixed duration formats:

- `Xd`
- `Xd Ys`
- `Xs`

Current parser logs warnings but does not fully normalize these.

This does not block Phase 2 completion but must be addressed in future refinement.
