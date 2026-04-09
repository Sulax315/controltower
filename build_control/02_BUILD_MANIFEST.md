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

# Phase 7 — Operator Command Surface
Weight: 10%

## Goal
Project deterministic engine artifacts into a single operator command surface without introducing new engine logic.

### Track 7A — Command Sheet
Deliverables:
- single-surface operator command sheet
- finish/driver/risk/need/doing projection from engine artifacts
- deterministic artifact references visible to operator

### Track 7B — Evidence Grid
Deliverables:
- evidence grid projection over deterministic output
- conclusion-to-evidence trace visibility
- no UI-side reinterpretation of risk/driver outcomes

### Track 7C — Inline Structural Visuals
Deliverables:
- inline structural views tied to existing engine artifacts
- structural context projection for operator review
- projection-only rendering of underlying intelligence

---

# Phase 8 — Export and Delivery
Weight: 10%

## Goal
Deliver print/PDF and consistency pathways over deterministic artifacts.

### Track 8A — Print View
Deliverables:
- print-friendly projection of command and evidence content
- stable formatting for operator review

### Track 8B — PDF Export
Deliverables:
- deterministic PDF export pathway
- command + evidence parity with operator surface

### Track 8C — Export Consistency
Deliverables:
- cross-surface consistency checks for projected artifacts
- no divergence between operator, print, and PDF outputs

---

# Phase 9 — Operator Workflow
Weight: 5%

## Goal
Add controlled interaction over existing outputs without changing intelligence generation.

### Track 9A — Run Selection
Deliverables:
- operator run selection over existing artifacts
- deterministic run context in command surface

### Track 9B — Review/Approval State
Deliverables:
- explicit operator review state handling
- controlled approval/review markers over projected outputs

### Track 9C — Export Controls
Deliverables:
- governed export controls aligned to approved artifacts
- no logic mutation through workflow controls

---

# Phase 10 — Schedule Visualization
Weight: 10%

## Goal
Provide visualization views that project deterministic schedule intelligence.

### Track 10A — Gantt Projection
Deliverables:
- Gantt-style projection from existing engine artifacts
- timeline view without logic reinterpretation

### Track 10B — PERT / Network View
Deliverables:
- network/PERT projection from logic artifacts
- deterministic structure representation

### Track 10C — Driver Path Visualization
Deliverables:
- visual projection of computed driver paths
- driver evidence continuity across surfaces

### Track 10D — Risk Visualization
Deliverables:
- visual projection of computed risk signals
- risk-to-evidence trace continuity

---

# Phase 11 — Interactive Analysis
Weight: 5%

## Goal
Support deterministic interaction patterns across projection layers.

### Track 11A — View Switching
Deliverables:
- controlled switching across command/evidence/visual views
- continuity of selected run context

### Track 11B — Filtering / Highlighting
Deliverables:
- deterministic filtering/highlighting over projected artifacts
- no derived logic beyond existing intelligence outputs

### Track 11C — Evidence-to-Visualization Linking
Deliverables:
- bidirectional linking between evidence and visualization surfaces
- trace-preserving interactions only

---

# Phase 12 — Stakeholder Outputs
Weight: 5%

## Goal
Package deterministic artifacts into stakeholder-ready outputs.

### Track 12A — PDF with Graphics
Deliverables:
- graphics-enabled PDF outputs grounded in engine artifacts
- command/evidence consistency maintained

### Track 12B — Image Export
Deliverables:
- deterministic image export for key views
- format-stable render outputs

### Track 12C — Stakeholder Pack Formatting
Deliverables:
- stakeholder pack layout and formatting standards
- projection-only assembly from deterministic artifacts

---

# Phase 13 — Deterministic PM Translation Layer
Weight: 8%

## Goal
Deterministically translate existing schedule intelligence into PM-grade meeting language in output-contract assembly without changing engine findings.

### Track 13A — Finish/Delta/Driver Translation
Deliverables:
- deterministic translation rules for finish position, period delta, and driver outputs
- output contract additions for finish/delta/driver meeting-language statements
- statement-level traceability to source artifacts, fields, task ids, and rule ids
- suppression behavior for unsupported statements
- explicit no-UI-side interpretation and no AI/heuristic narration constraints

Completion logic:
- translation rules and contract fields are implemented in assembly layer
- unsupported finish/delta/driver claims are suppressed
- every emitted statement resolves to deterministic sources and rule ids

### Track 13B — Fragility/Risk/Pressure Translation
Deliverables:
- deterministic translation rules for fragility, risk, and pressure signals
- output contract additions for fragility/risk/pressure meeting-language statements
- statement-level traceability to source artifacts, fields, task ids, and rule ids
- suppression behavior for unsupported statements
- explicit no-UI-side interpretation and no AI/heuristic narration constraints

Completion logic:
- translation rules and contract fields are implemented in assembly layer
- unsupported fragility/risk/pressure claims are suppressed
- every emitted statement resolves to deterministic sources and rule ids

### Track 13C — PM Thinking Encoding and Meeting-Language Assembly
Deliverables:
- reproducible structural/threshold-based encoding of PM meeting compression logic
- governed meeting-language assembly contract over deterministic artifacts
- sentence-level traceability model and rule-id surface in output payload
- cause-diagnosis suppression unless deterministically proven by governed rules
- explicit enforcement that implementation remains assembly-layer only

Completion logic:
- PM encoding rules are deterministic, reproducible, and versioned
- meeting-language assembly emits only supported statements with trace links
- no cause diagnosis appears without deterministic proof path
- no translation logic exists in UI templates/browser/client code

---

# Build Order Rule
Work must proceed in phase order unless the manifest is formally revised.

No phase may be treated as complete if any required track deliverable is still unmet.

---

# Current Official Direction
Engine completion baseline:
- Phases 1-6 COMPLETE
- Deterministic schedule intelligence engine completed through Phases 14-18 execution
- Engine completion: 100%

Post-engine delivery completion:
- Phase 7 (Phase 19-20) COMPLETE
  - Track 7A Command Sheet — COMPLETE
  - Track 7B Evidence Grid — COMPLETE
  - Track 7C Inline Structural Visuals — COMPLETE
- Phase 8 (Phase 21) COMPLETE
  - Track 8A Print View — COMPLETE
  - Track 8B PDF Export — COMPLETE
  - Track 8C Export Consistency — COMPLETE
- Phase 22 Governance Synchronization — COMPLETE
- Phase 9 (Phases 23-25) COMPLETE
  - Track 9A Run Selection — COMPLETE
  - Track 9B Review/Approval State — COMPLETE
  - Track 9C Export Controls — COMPLETE
- Phase 10 (Phase 26) COMPLETE
  - Track 10A Gantt Projection — COMPLETE
  - Track 10B PERT / Network View — COMPLETE
  - Track 10C Driver Path Visualization — COMPLETE
  - Track 10D Risk Visualization — COMPLETE
- Phase 11 (Phase 27) COMPLETE
  - Track 11A View Switching — COMPLETE
  - Track 11B Filtering / Highlighting — COMPLETE
  - Track 11C Evidence-to-Visualization Linking — COMPLETE
- Phase 12 (Phase 28) COMPLETE
  - Track 12A PDF with Graphics — COMPLETE
  - Track 12B Image Export — COMPLETE
  - Track 12C Stakeholder Pack Formatting — COMPLETE
- Phase 13 (Phase 32) COMPLETE — Deterministic PM Translation Layer
  - Track 13A Finish/Delta/Driver Translation — COMPLETE
  - Track 13B Fragility/Risk/Pressure Translation — COMPLETE
  - Track 13C PM Thinking Encoding and Meeting-Language Assembly — COMPLETE
  - **Live verification:** COMPLETE (`PASS_LOCAL_AND_LIVE` per `build_control/09_CURRENT_BUILD_PACKET.md` and `build_control/04_DECISION_LOG.md`)

Current build direction: **Weighted manifest Phases 1–13 are complete.** **Phase 33** (build packet — operator usability + polish, **presentation / projection only**) is the **next** governed product lane; it is **not** yet a weighted manifest phase. Open **pre-execution gate** and obtain **explicit** prompt authorization before Phase 33 implementation.

No work outside the governed phase order should proceed.

---

## Post–Phase 32 platform era (planning reference — not manifest phases yet)

**Proposed** eras, tracks, sequencing, boundaries, and acceptance structure for production hardening, artifact/Postgres formalization, backup/monitoring, and optional surrounding platforms are recorded in:

- `build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md`

**Do not** treat that document as an implementation authorization. When governance authorizes a concrete post-closeout phase (e.g. production hardening or NocoBase introduction), add **Manifest Phase 14+** with weights and tracks at that time per the roadmap’s governance recommendation.