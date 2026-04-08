# Decision Log

## 2026-04-06 — Formal reset of Control Tower build
Decision:
The Control Tower build is formally reset from a presentation-first/orchestration-first direction to a schedule-intelligence-first direction.

Reason:
The current implementation drifted away from the original job-to-be-done and produced surfaces that were not helpful to the intended PM workflow.

Impact:
All future work must prioritize the engine that interprets Asta schedule exports and produces PM-grade analysis.

Supersedes:
Any implicit assumption that Arena/Publish/orchestration layers are the primary product.

Status:
Active

---

## 2026-04-06 — Canonical source of truth moved into repo governance layer
Decision:
The canonical source of truth for the build will live inside the repo at build_control/.

Reason:
The build needs a human-readable, machine-readable, auditable governance layer that both Cursor and ChatGPT can use.

Impact:
Prompts, progress, and plan updates must reference build_control files.

Supersedes:
Unstructured thread memory, implicit plans, or Obsidian-only governance.

Status:
Active

---

## 2026-04-06 — Obsidian is mirror/review layer, not canonical source
Decision:
Obsidian may be used as a mirror, dashboard, or note layer, but not as the sole source of truth.

Reason:
Repo-based governance is easier to audit, version, and align with implementation.

Impact:
Any future Obsidian integration must mirror or reference repo governance rather than replace it.

Status:
Active

---

## 2026-04-08 — Engine complete; transition to projection/delivery roadmap
Decision:
Phases 14-18 are accepted as complete for deterministic schedule intelligence engine delivery, and the governed roadmap now transitions to post-engine projection and delivery execution (Phases 19-25).

Reason:
Core deterministic intelligence is complete and trustworthy; next value is delivered through operator projection, evidence surfacing, controlled workflow, and export/visualization delivery.

Impact:
Phase 19 becomes active immediately. Post-engine phases 19-25 are now the governed sequence, with command sheet and evidence surface prioritized before broader visualization work. UI remains projection-only and may not reinterpret engine intelligence.

Status:
Active