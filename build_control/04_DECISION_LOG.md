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