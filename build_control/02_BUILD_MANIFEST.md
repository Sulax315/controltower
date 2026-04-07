# Build Manifest

## Build Structure
This manifest defines the official phases, tracks, deliverables, dependencies, and completion rules for the Control Tower reset.

Overall completion is weighted by phase and track completion, not by subjective feeling.

---

# Phase 1 — Governance Reset
Weight: 10%

## Goal
Create the authoritative governance layer for the build so that planning, prompting, execution, and progress tracking are controlled and auditable.

### Track 1A — Governance Files
Weight: 4%
Deliverables:
- build_control folder created
- master plan created
- product definition created
- build manifest created
- acceptance criteria created
- decision log created
- continuity protocol created
- status board created
- state.json created

### Track 1B — Progress Model
Weight: 3%
Deliverables:
- weighted phase model defined
- track weights recorded
- current phase/track recorded
- current blocker and next action recorded

### Track 1C — Prompt Discipline
Weight: 3%
Deliverables:
- continuity rules defined
- Cursor prompting rules defined
- governance referenced in active build flow

---

# Phase 2 — Data Intake Foundation
Weight: 20%

## Goal
Create a robust intake layer for Asta CSV exports.

### Track 2A — CSV Column Mapping
Weight: 5%
Deliverables:
- actual CSV columns identified
- mapping strategy defined
- required vs optional fields defined

### Track 2B — Activity Parsing
Weight: 8%
Deliverables:
- Activity dataclass or typed model created
- parser implemented
- missing/null handling implemented
- dates/durations normalized
- predecessor/successor parsing implemented

### Track 2C — Parse Validation
Weight: 7%
Deliverables:
- parser tested against real export
- parse summary output available
- malformed field handling verified

---

# Phase 3 — Schedule Logic Model
Weight: 20%

## Goal
Represent the schedule as a usable logic structure for downstream analysis.

### Track 3A — Graph Construction
Weight: 8%
Deliverables:
- nodes created from activities
- logic edges created
- disconnected/invalid references handled

### Track 3B — Logic Quality Signals
Weight: 6%
Deliverables:
- open ends detection
- orphaned references detection
- cycle detection support

### Track 3C — Graph Summary Layer
Weight: 6%
Deliverables:
- summary metrics available
- chain/path support defined
- graph inspection utilities created

---

# Phase 4 — Schedule Intelligence
Weight: 30%

## Goal
Produce useful, deterministic analysis from the schedule model.

### Track 4A — Driver Detection
Weight: 10%
Deliverables:
- driver scoring method defined
- top drivers identified
- rationale available for each major driver conclusion

### Track 4B — Risk Detection
Weight: 10%
Deliverables:
- open ends surfaced
- cycles surfaced
- fragility signals surfaced
- float/constraint issues surfaced if available

### Track 4C — Delta Analysis
Weight: 10%
Deliverables:
- current vs prior export comparison design
- finish movement detection
- major logic or driver change detection
- narrative-ready delta summary

---

# Phase 5 — Narrative and Output Contracts
Weight: 15%

## Goal
Turn the intelligence into stable consumable outputs.

### Track 5A — Command Brief
Weight: 5%
Deliverables:
- Finish line generated
- Driver line generated
- Risks line generated
- Need line generated
- Doing line generated

### Track 5B — Evidence Payload
Weight: 5%
Deliverables:
- structured evidence model
- links between conclusions and data signals
- machine-readable stable schema

### Track 5C — Markdown/JSON Output
Weight: 5%
Deliverables:
- markdown brief output
- JSON intelligence output
- deterministic output formatting

---

# Phase 6 — Operator Review Surface
Weight: 5%

## Goal
Create the minimum useful review/export surface once the engine is trustworthy.

### Track 6A — Minimal Review UI
Weight: 3%
Deliverables:
- simple review screen or local view
- brief + evidence visible
- no decorative redesign work

### Track 6B — Export Support
Weight: 2%
Deliverables:
- markdown export
- PDF-ready pathway or equivalent export bridge

---

# Build Order Rule
Work must proceed in phase order unless the manifest is formally revised.

No phase may be treated as complete if any required track deliverable is still unmet.

---

# Current Official Direction
Current build direction is reset execution focused on:
- Phase 1 completion
- then Phase 2A and 2B

No work outside that lane should proceed yet.