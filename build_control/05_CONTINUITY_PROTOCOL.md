# Continuity Protocol

## Purpose
This file defines how the Control Tower build is continued across Cursor sessions, ChatGPT threads, and implementation cycles.

---

## Canonical Governance
The authoritative build governance lives in:

- build_control/00_MASTER_PLAN.md
- build_control/01_PRODUCT_DEFINITION.md
- build_control/02_BUILD_MANIFEST.md
- build_control/03_ACCEPTANCE_CRITERIA.md
- build_control/04_DECISION_LOG.md
- build_control/06_STATUS_BOARD.md
- build_control/07_ASTA_CSV_COLUMN_MAPPING.md
- build_control/08_PHASE2C_VALIDATION_EVIDENCE.md
- build_control/state.json
- build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md (approved future platform map; read when scope touches hosting, domains, or non-Control-Tower integrations)
- build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md (proposed post-closeout platform-era phases/tracks; planning only until decision log authorizes implementation)

These files must be read before planning or coding.

---

## Required Context for Any New ChatGPT Thread
Any new thread used for this build must be told:

1. the product is a schedule intelligence engine for Asta CSV exports
2. the repo build_control folder is the source of truth
3. the current phase and track come from state.json and the status board
4. work must remain within the current build lane unless the plan itself is being revised
5. current governed lane follows `state.json` and `06_STATUS_BOARD.md` (Phase 32 / Manifest Phase 13 is **complete**; **Phase 33** is next unless state files are formally updated)

---

## Required Context for Any Cursor Work Session
Any Cursor prompt must instruct Cursor to first read:

- build_control/00_MASTER_PLAN.md
- build_control/02_BUILD_MANIFEST.md
- build_control/03_ACCEPTANCE_CRITERIA.md
- build_control/06_STATUS_BOARD.md
- build_control/state.json

Cursor must not proceed as if prior assumptions outrank those files.
Cursor must verify the active phase, active track, and next required action are synchronized across status board and state.json before implementation work.

---

## Prompting Rule
No build prompt is valid unless it aligns with:
- current phase
- current track
- stated deliverables
- acceptance criteria

When governance is revised, all dependent governance/state artifacts must be synchronized before implementation prompts are considered valid.

---

## Completion Recording Rule
Whenever a track is completed or materially advanced:

1. update 06_STATUS_BOARD.md
2. update state.json
3. add a decision log entry if scope/approach changed
4. only then move to the next track

---

## Thread Handoff Rule
Any continuity message must include:
- product identity
- current phase and track
- current blocker
- last completed item
- next required action
- explicit reminder that build_control governs the build

---

## Drift Prevention Rule
If implementation starts to focus on UI, framework complexity, orchestration, or polish before the engine is trustworthy, the build must be redirected back to the manifest.

Phase 32-specific drift prevention:
- deterministic translation work must remain in output-contract/publish_assembly layers
- translation statements must be traceable to deterministic artifacts, fields, task ids, and rule ids
- no AI-generated narrative, heuristic guessing, or UI-side interpretation is permitted