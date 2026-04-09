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

---

## 2026-04-09 — Governance expansion to Phase 32 deterministic PM translation
Decision:
Control Tower governance is expanded to include Phase 32 as the active post-engine lane: deterministic PM translation of existing schedule intelligence into meeting-language output.

Reason:
Deterministic engine signals are present, but weekly PM review workflows require deterministic, traceable meeting-language translation to convert signals into decision-ready statements without interpretation drift.

Impact:
Phase 32 work is now governed as output-contract/publish_assembly ownership only. Translation must not alter engine findings, must not use AI narration or heuristic prose, and must enforce statement-level traceability to deterministic source artifacts, fields, task ids, and rule ids.

Status:
Active

---

## 2026-04-09 — Phase 32A accepted as complete
Decision:
Phase 32A (Finish/Delta/Driver Translation) is recorded as complete based on accepted deterministic implementation and test evidence.

Reason:
Phase 32A rule primitives and contract outputs were implemented in output assembly with deterministic suppression and traceability behavior, and acceptance-aligned tests passed.

Impact:
Governance state advances from Track 13A to Track 13B/13C sequencing, with 32A outputs now treated as stable prerequisite inputs for later PM translation stages.

Status:
Active

---

## 2026-04-09 — Phase 32B accepted as complete; advance to 32C pre-execution gate
Decision:
Phase 32B (Fragility/Risk/Pressure Translation) is recorded as complete based on accepted deterministic implementation and test evidence.

Reason:
Phase 32B introduced deterministic L1/P1/O2 translation primitives with explicit thresholds, suppression rules, and source traceability without UI or engine-scope drift.

Impact:
Phase 32C becomes the next governed lane. Next authorized action is the Phase 32C pre-execution gate for PM thinking encoding and meeting-language assembly.

Status:
Active