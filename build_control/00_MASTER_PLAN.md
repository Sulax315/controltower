# Control Tower Reset Master Plan

## Authority
This document is the governing source of truth for the Control Tower reset build. All implementation, planning, prompting, sequencing, and acceptance decisions must align to this plan unless this plan is explicitly revised.

If code, prompts, UI, or outputs conflict with this plan, this plan wins.

---

## Product Identity

### What this product is
Control Tower is a deterministic schedule intelligence and reporting system for construction project management.

Its purpose is to ingest exported schedule data from Asta Powerproject and convert that data into decision-ready, stakeholder-facing analysis that helps a project manager understand:

- where the finish currently stands
- what is driving the finish
- what changed from the prior update
- what risks are present in the schedule logic
- what action is needed now

The intended product access pattern is direct browser use at `https://controltower.bratek.io` through an authenticated operator workflow, not manual run identifier handling.

Browser access alone is not sufficient. The browser-visible product experience must be polished, production-grade, and operator-serious; the currently visible utility-style shell is not acceptable as end-state product UI.

### What this product is not
Control Tower is not:

- a generic workflow platform
- a broad orchestration product
- a task management suite
- a release management framework
- a presentation shell without real schedule intelligence
- a UI-first dashboard project

The product exists to perform schedule analysis first, and presentation second.

---

## Primary User
Primary user: a construction project manager reviewing and communicating schedule status from Asta Powerproject exports.

The system must support real weekly schedule analysis and real stakeholder update workflows.

---

## Core Job To Be Done
When the user exports schedule data from Asta Powerproject, the system should deterministically analyze that export and produce a concise, accurate, meeting-ready schedule brief and supporting evidence that reduce manual analysis effort and improve consistency.

Core usage flow expectation: open `https://controltower.bratek.io`, authenticate, upload CSV, launch deterministic server-side execution, automatically open resulting operator surface, and reopen latest/recent runs from the browser.

Core usage quality expectation: this flow must execute inside a coherent, desktop-class browser product shell that matches the quality and seriousness of the deterministic intelligence already produced by Layers 1-2.

---

## Primary Input
Primary input is an exported CSV from Asta Powerproject.

The product may later support prior-period comparison inputs and additional schedule artifacts, but the current reset scope begins with CSV export analysis.

---

## Primary Outputs

### Required output 1
A deterministic command brief with these five lines:

1. Finish
2. Driver
3. Risks
4. Need
5. Doing

### Required output 2
A structured evidence layer that shows how each conclusion was derived from the underlying schedule data.

### Required output 3
A machine-readable JSON intelligence payload that can later support UI, PDF, export, and audit surfaces.

---

## Product Principles

### 1. Brain before shell
The schedule intelligence engine is the product. UI, presentation, and workflow layers are secondary.

### 2. Deterministic over impressionistic
Every output must be grounded in identifiable schedule data, logic, or comparison rules. No decorative prose disconnected from the data.

### 3. Traceable conclusions
Every major statement must be explainable through evidence, logic, or comparison.

### 4. PM-grade usefulness
If the output would not help a real project manager run a real meeting, it is not good enough.

### 5. Narrow scope first
The build must focus on the smallest complete version of the real product before expanding.

---

## Reset Decision
This build has been formally reset. Prior work on publish surfaces, arena surfaces, orchestration, approvals, MCP, and related layers is demoted from primary focus.

Those items may be reused later if they support the core engine, but they are not the product and must not drive current work.

---

## Salvageable Existing Assets

### Worth keeping
- existing repo and deployment environment
- domain and hosting setup
- deterministic mindset
- command brief concept
- evidence grid concept
- ability to publish output later

### Not current priorities
- arena/publish shell refinement
- orchestration layers
- approval flows
- MCP integrations
- Obsidian sync behaviors
- presentation-first redesign

---

## System Architecture

### Layer 1 — Schedule Intelligence Engine
This is the primary focus.

Responsibilities:
- parse Asta CSV
- normalize activity data
- build schedule logic model
- detect drivers
- detect risks
- compare current vs prior export
- generate structured intelligence
- generate deterministic command brief

### Layer 2 — Output Contracts
Responsibilities:
- JSON intelligence payload
- markdown brief
- exportable report-ready content

### Layer 3 — Operator Surface
Responsibilities:
- browser-based run access from authenticated entry
- browser CSV upload and deterministic analysis launch initiation
- operator-grade browser front door and shell for launch/reopen/review actions
- polished presentation hierarchy for latest/recent deterministic run access
- coherent browser experience for upload, analysis access, operator review, and export handoff
- review output
- inspect evidence
- export/present intelligence
- reopen latest/recent runs from browser entry without manual run_id lookup

Layer 1 is now complete and trustworthy through deterministic engine Phases 14-18.

Layer 3 has progressed through command-sheet delivery, evidence surfacing, export hardening, decision reinforcement, controlled interaction, and readability tuning.

Layer 3 remains projection and delivery execution only. Layer 3 must remain projection-only and may not reinterpret, re-score, or reimplement intelligence already produced by Layer 1.

---

## Non-Negotiable Rules

1. No implementation work may bypass the current phase and track defined in the build manifest.
2. No UI-first work may proceed while core engine functionality remains incomplete.
3. No feature is complete unless acceptance criteria are met and status files are updated.
4. No prompt to Cursor or ChatGPT is valid unless aligned with this build_control governance layer.
5. All major changes must be logged in the decision log.

---

## MVP Definition
The MVP is a working engine that takes an Asta CSV export and produces:

- normalized activity records
- a schedule logic representation
- deterministic driver detection
- deterministic risk detection
- a command brief
- a structured JSON output payload

No polished operator UI is required for MVP completion.

---

## End State Vision
The final product should become a trusted schedule analysis companion for weekly project management work, reducing manual interpretation burden while improving consistency, clarity, and auditability.

The system should eventually support polished review and export surfaces, but only after the schedule intelligence engine is solid.

End-state product access is direct authenticated browser use at `https://controltower.bratek.io`, with upload-to-execution-to-operator review flow as standard operation.

End-state browser experience must read as a serious desktop-class web application for operators, not a leftover utility page, dev console, or thin internal launcher.

---

## Post-Engine Execution Phases
With completion of the deterministic schedule intelligence engine (Phases 14-18), the build now proceeds to projection and delivery layers.

Execution rules for all post-engine phases:
- UI is projection-only
- No logic may be reimplemented in UI
- All outputs must trace to engine artifacts
- No dashboard drift
- No generic PM/workflow platform drift

### Actual Build Status
Completed to date:
- Deterministic schedule intelligence engine complete (Phases 14-18)
- Phase 19 — Operator Command Sheet (COMPLETE)
- Phase 20 — Evidence Grid + Inline Structural Views (COMPLETE)
- Phase 21 — Export Layer (Print/PDF projection hardening) (COMPLETE)
- Phase 22 — Governance Synchronization (COMPLETE)
- Phase 23 — Decision Reinforcement (COMPLETE)
- Phase 24 — Operator Workflow Discipline / Controlled Interaction (COMPLETE)
- Phase 25 — Operator Readability and Density Tuning (COMPLETE)
- Phase 26 — Schedule Visualization Layer (COMPLETE)
- Phase 27 — Interactive Analysis Views (COMPLETE)
- Phase 28 — Exportable Graphics / Stakeholder Packs (COMPLETE)

### Remaining Governed Roadmap
- Phase 29 — Browser Entry, Upload, and Run Access  
  Authenticated root browser entry at `https://controltower.bratek.io` with browser CSV upload, deterministic server-side execution launch, automatic redirect to resulting operator surface, and latest/recent run reopening from browser entry while preserving single-surface discipline and projection-only governance.
- Phase 30 — Browser Product Shell Overhaul  
  Total replacement of browser-visible entry shell and browser-facing UI patterns that do not meet product intent; deliver a polished operator-grade front door, serious desktop-class visual language, coherent hierarchy for launch/reopen flows, and removal of leftover utility-style browser patterns.
- Phase 31 — Browser Surface Polish, Cohesion, and Production Hardening  
  Browser-wide cohesion and production hardening between entry shell and operator surface, including final polish of spacing/hierarchy/readability, consistency of interaction flow, and validation that the browser product experience matches intended product quality without weakening deterministic governance.