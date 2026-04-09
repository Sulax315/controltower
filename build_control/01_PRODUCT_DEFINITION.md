# Product Definition

## Product Name
Control Tower — Schedule Intelligence Engine

## One-Sentence Definition
A deterministic schedule intelligence and translation system that converts Asta Powerproject CSV exports into PM-grade schedule analysis and deterministic meeting-language outputs with traceable supporting evidence.

Engine status: Core deterministic schedule intelligence engine is complete through Phases 14-18.

---

## Problem
The current schedule analysis workflow is too manual, too variable, and too dependent on repetitive interpretation by the project manager.

The user currently exports schedule data, manually inspects activities, logic, path behavior, and risk signals, then translates that into a meeting narrative for stakeholders.

This process is time-consuming and inconsistent.

---

## User Workflow Being Replaced
Current workflow:

1. Export schedule data from Asta Powerproject
2. Review finish and key milestone implications
3. Identify major driving chains or controlling activities
4. Detect logic issues and risk conditions
5. Compare to prior update mentally or manually
6. Create a stakeholder-facing narrative
7. Present findings in weekly review

The product must compress and automate as much of that workflow as possible without losing rigor.

---

## Value Definition
The product is valuable if it reliably helps the user:

- understand what is driving the finish
- identify the most important schedule risks
- detect meaningful change from the prior update
- prepare a meeting-ready brief faster and more consistently

Post-engine value expansion must come from clearer operator projection, evidence consumption, and delivery surfaces over existing deterministic artifacts, not from replacing or reinventing core engine intelligence.

---

## In Scope for Reset MVP
- Asta CSV ingestion
- activity normalization
- schedule logic modeling
- driver heuristics
- risk heuristics
- comparison against prior export
- command brief generation
- JSON output contract
- minimal CLI/test harness if needed

---

## Out of Scope for Reset MVP
- polished publish UI
- arena redesign
- MCP integration
- approval workflows
- release orchestration
- broad multi-project command center
- deep Obsidian integration
- generic collaboration features

For post-engine execution, new UI-side analysis logic is also out of scope. Operator, export, and visualization layers must project deterministic engine artifacts only.

---

## Required Output Shape

### Command brief
Must include:
- Finish
- Driver
- Risks
- Need
- Doing

### Evidence layer
Must identify the basis for conclusions such as:
- activity IDs
- activity names
- successor/predecessor counts
- float conditions
- logic issues
- comparison deltas

### Structured payload
Must be machine-readable and stable enough to support future UI layers.

Those future layers are delivery/projection layers and must not reinterpret or regenerate the underlying intelligence.

### Deterministic PM translation payload
Must provide a meeting-language layer assembled from existing deterministic intelligence artifacts using reproducible rules.

Requirements:
- no AI-generated narrative
- no heuristic/freeform interpretation
- no statement without deterministic source traceability
- sentence-level linkage to source artifacts, fields, task ids, and rule ids

---

## Product Standard
A result is acceptable only if the user would trust it during a real project schedule review.

That is the governing standard.

---

## Product identity vs optional platform layers (approved target direction)

**Core product identity (unchanged):** Control Tower is the **schedule intelligence and deterministic reasoning product** — Asta CSV through to traceable intelligence, command brief, publish assembly, and operator surfaces that **project** that truth. That identity is **not** shared with generic PM suites, workflow engines, or optimization services.

**Approved future surrounding systems (not implemented until governance authorizes):** The organization may add **optional** platforms that **support** operations and collaboration **around** Control Tower, without becoming the core analytical brain:

- **Workflow / admin (e.g. NocoBase):** tracking and ops surrounding; not schedule determinism.
- **Broad PM / collaboration (e.g. OpenProject):** optional; **never** replaces Control Tower as the deterministic schedule reasoning core.
- **Optimization service (e.g. OR-Tools / PyJobShop):** separate service, **scenario solving only**; **never** supersedes imported schedule truth owned by Control Tower’s pipeline.

**Authoritative architecture reference:** `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md`.

Until those systems exist, all build prompts and acceptance remain **Control Tower–only** unless governance explicitly opens a new phase.