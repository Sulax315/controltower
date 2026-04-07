# Asta Powerproject CSV — Column mapping (authoritative export)

This artifact documents the **current** Asta export shape used for Phase 2 intake. Column titles are exact CSV header strings (case- and space-sensitive).

## Source columns (in logical order)


| CSV header         | Activity field            | Role                                 |
| ------------------ | ------------------------- | ------------------------------------ |
| Task ID            | `task_id`                 | Primary graph key (string)           |
| Task name          | `task_name`               | Display / narrative                  |
| Unique task ID     | `unique_task_id`          | Secondary stable identifier (string) |
| Duration           | `duration_days`           | Planned duration                     |
| Duration remaining | `duration_remaining_days` | Remaining duration                   |
| Start              | `start`                   | Current / scheduled start            |
| Finish             | `finish`                  | Current / scheduled finish           |
| Early start        | `early_start`             | CPM early start                      |
| Early finish       | `early_finish`            | CPM early finish                     |
| Late start         | `late_start`              | CPM late start                       |
| Late finish        | `late_finish`             | CPM late finish                      |
| Total float        | `total_float_days`        | Total float                          |
| Free float         | `free_float_days`         | Free float                           |
| Critical           | `critical`                | Critical flag                        |
| Predecessors       | `predecessors`            | List of predecessor task IDs         |
| Successors         | `successors`              | List of successor task IDs           |
| Critical path drag | `critical_path_drag_days` | Drag in day units                    |
| Phase Exec         | `phase_exec`              | WBS / phase coding                   |
| Control Account    | `control_account`         | Control account coding               |
| Area Zone          | `area_zone`               | Area / zone coding                   |
| Level              | `level`                   | Level coding                         |
| CSI                | `csi`                     | CSI coding                           |
| System             | `system`                  | System coding                        |
| Percent complete   | `percent_complete`        | Physical % complete                  |
| Original start     | `original_start`          | Baseline start                       |
| Original finish    | `original_finish`         | Baseline finish                      |


---

## MVP classification

### Required for MVP parser / graph

These are required to build a coherent activity set and logic edges for the first graph:


| CSV header   | Reason                                                                      |
| ------------ | --------------------------------------------------------------------------- |
| Task ID      | Primary key; predecessors/successors reference this ID                      |
| Predecessors | Logic edges (along with successors, at least one side eventually populated) |
| Successors   | Logic edges                                                                 |


**Note:** Rows with a missing or blank `Task ID` after normalization are **skipped** with a row-level warning; they cannot participate in the graph.

### Strongly recommended for analysis

Needed soon for drivers, risk signals, and PM-grade briefs (float, criticality, timing):


| CSV header         |
| ------------------ |
| Task name          |
| Duration           |
| Duration remaining |
| Start              |
| Finish             |
| Early start        |
| Early finish       |
| Late start         |
| Late finish        |
| Total float        |
| Free float         |
| Critical           |
| Critical path drag |
| Percent complete   |


### Optional contextual fields

Useful for filtering, reporting, and stakeholder context; not required for a minimal logic graph:


| CSV header      |
| --------------- |
| Unique task ID  |
| Phase Exec      |
| Control Account |
| Area Zone       |
| Level           |
| CSI             |
| System          |
| Original start  |
| Original finish |


---

## Parsing assumptions

1. **Dates** use `M/D/YYYY` (month/day/year). The parser may accept a small set of additional common variants for resilience (e.g. ISO dates), but exports should be treated as `M/D/YYYY` by convention.
2. **Duration-like fields** (`Duration`, `Duration remaining`, `Total float`, `Free float`, `Critical path drag`) are strings such as `38d` or `0d`; numeric day values are parsed from the leading number (supports decimals, e.g. `1.5d`).
3. **Critical** is `TRUE` / `FALSE` (case-insensitive); other truthy/falsy tokens may be accepted with warnings.
4. **Predecessors** and **Successors** are comma-separated **Task ID** tokens; whitespace around tokens is trimmed.
5. **IDs** (`Task ID`, `Unique task ID`, and tokens in predecessor/successor lists) remain **strings** (no numeric coercion).
6. **Blank cells** and the literal `**<None>`** (any case) normalize to Python `None` for scalars; for predecessor/successor lists, a blank or `<None>` field becomes `None` (meaning unknown / absent), while an empty list after splitting means no links.

---

## Fallback / header matching

- File is read as **UTF-8** with optional BOM (`utf-8-sig`).
- Headers must match the names above **exactly** after BOM strip. If future exports rename columns, extend this document and the parser’s header map in the same change.

