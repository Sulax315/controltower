# Acceptance Criteria

## Acceptance Standard
A track is only complete when its stated deliverables are implemented, reviewed, and recorded in the status board and state.json.

No vague claims of completion are allowed.

---

# Phase 1 — Governance Reset

## Track 1A — Governance Files
Pass criteria:
- build_control folder exists in repo
- all required governance files exist
- files contain meaningful initial content, not placeholders
- files are readable and internally consistent

Evidence required:
- file paths
- brief summary of file purpose
- git status or equivalent local proof

## Track 1B — Progress Model
Pass criteria:
- weighted phase model exists
- overall completion method is defined
- current phase and track are recorded
- current blocker and next action are recorded

Evidence required:
- manifest weights visible
- status board updated
- state.json updated

## Track 1C — Prompt Discipline
Pass criteria:
- continuity protocol exists
- Cursor prompt rules exist
- next build prompt references governance files explicitly

Evidence required:
- continuity file content
- actual Cursor prompt aligned to governance layer

---

# Phase 2 — Data Intake Foundation

## Track 2A — CSV Column Mapping
Pass criteria:
- real CSV inspected
- actual column names documented
- required vs optional columns defined
- fallback mapping logic specified

Evidence required:
- mapping notes in code or docs
- sample column listing from real file

## Track 2B — Activity Parsing
Pass criteria:
- typed activity model exists
- parser function implemented
- dates normalized
- duration normalized
- predecessor/successor parsing implemented
- missing values handled safely

Evidence required:
- parser module path
- model path
- sample parsed output from real CSV
- test or harness output

## Track 2C — Parse Validation
Pass criteria:
- parser runs on real CSV without crashing
- parse count matches expectation within reason
- invalid rows handled or reported
- parse summary produced

Evidence required:
- sample run output
- error handling behavior shown
- summary stats shown

---

# Phase 3 — Schedule Logic Model

## Track 3A — Graph Construction
Pass criteria:
- graph structure exists
- activities become nodes
- predecessor/successor logic becomes edges
- invalid refs handled

## Track 3B — Logic Quality Signals
Pass criteria:
- open ends detectable
- cycles detectable or flagged
- invalid relationship conditions surfaced

## Track 3C — Graph Summary Layer
Pass criteria:
- graph summary metrics exist
- basic inspection routines exist
- output usable by intelligence layer

---

# Phase 4 — Schedule Intelligence

## Track 4A — Driver Detection
Pass criteria:
- scoring method defined
- top driver candidates surfaced
- rationale traceable to data

## Track 4B — Risk Detection
Pass criteria:
- major risk classes surfaced
- evidence available for each risk
- signals are not decorative or invented

## Track 4C — Delta Analysis
Pass criteria:
- prior-vs-current comparison implemented
- finish movement surfaced
- meaningful change narrative supported

---

# Phase 5 — Narrative and Output Contracts

## Track 5A — Command Brief
Pass criteria:
- 5-line brief produced from real analysis
- wording is deterministic and concise
- lines reflect actual signals

## Track 5B — Evidence Payload
Pass criteria:
- output contains structured rationale
- each conclusion can be traced

## Track 5C — Markdown/JSON Output
Pass criteria:
- markdown output generated
- JSON output generated
- repeat runs are stable and consistent

---

# Phase 6 — Operator Review Surface

## Track 6A — Minimal Review UI
Pass criteria:
- output is viewable in a simple surface
- brief and evidence are present
- no UI work outruns engine maturity

## Track 6B — Export Support
Pass criteria:
- export path exists
- exported artifact reflects engine output faithfully

---

# Universal Failure Conditions
A track fails acceptance if:
- it introduces work outside the current phase without approval
- it claims completion without evidence
- it is UI-heavy but intelligence-light
- it produces narrative without data grounding
- it cannot be explained or trusted in a real PM review context