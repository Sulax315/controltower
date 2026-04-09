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

---

## 2026-04-09 — Governance sync: 32C implementation + local runtime verified; live verification is the remaining gate
Decision:
Phase 32C (Manifest Track 13C) assembly and upload→run→publish→operator wiring are recorded as **complete in-repo**, with **local runtime end-to-end verification PASS** on `127.0.0.1:8787` (entry form, `POST /entry/upload` → 303 → operator, `run.json` completed, `publish_packet.json` present with `pm_translation_v1` / `meeting_summary` / `visualization`, operator includes `publish-pm-translation-payload`). The **current governed blocker** is **live deployment verification** at `https://controltower.bratek.io` only — not further Phase 32 translation rule work.

Reason:
Implementation and deterministic behavior are verified locally; product definition of done in the current build packet still requires confirmation against the production domain. No new phase is authorized; this is the existing closeout lane.

Impact:
`state.json` and `06_STATUS_BOARD.md` advance 32C from “queued / pre-gate” to “implementation + local runtime complete, live verify pending.” Automated checks from some egress paths may hit perimeter filtering (e.g. FortiGuard) and must not be mistaken for application failure without origin-level confirmation.

Status:
Active

---

## 2026-04-10 — Target production architecture adopted (documentation only; implementation deferred)

Decision:
The **target production architecture** and **post-closeout platform direction** described in `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md` are **approved** as the **future** multi-domain, multi-service map surrounding Control Tower. **No implementation** of NocoBase, OpenProject, OR-Tools/PyJobShop services, additional VMs, or Postgres-backed platform wiring is authorized by this decision.

Reason:
The organization needs a single, explicit, governance-controlled statement of how Control Tower remains the **core brain** while optional workflow, collaboration, and scenario-optimization layers may be added later without product-identity drift.

Impact:
- **Control Tower** remains the **authoritative deterministic schedule intelligence** product; surrounding systems are **support-only** and must not replace imported schedule truth or deterministic conclusions.
- **NocoBase** (`ops.bratek.io` target), **OpenProject** (`pm.bratek.io` / `openproject.bratek.io` target), and **solver** (OR-Tools/PyJobShop-class, `solver.internal.bratek.io` or private route) are **optional** and **deferred** until after current governed closeout (Phase 32 live verification and authorized hardening) per the documented rollout sequence.
- **Current active phase/track** and **next required actions** are **unchanged** except for this recorded future direction (`state.json` carries a reference field only).

Status:
Active

---

## 2026-04-09 — Post–Phase 32 platform-era roadmap captured (planning only)

Decision:
Add `build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md` as the **proposed** governed roadmap for eras after Phase 32 closeout: Control Tower production hardening, artifact/Postgres formalization, backup/recovery/monitoring, optional NocoBase, optional solver, and optional OpenProject decision gate — aligned to `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md` sequencing.

Reason:
The approved target architecture needs a bounded planning artifact (eras/tracks, dependencies, boundaries, evidence-style acceptance) without opening implementation or prematurely adding weighted manifest phases.

Impact:
- **No implementation** of surrounding platforms or Postgres/solver/OpenProject deployment is authorized by this entry.
- Continuity, status board, build packet, and manifest reference doc **13** as **planning-only** context; **Manifest Phase 14+** is added when a post-closeout implementation phase is explicitly authorized.

Status:
Active

---

## 2026-04-09 — Phase 32 closeout: local + live verification complete; production operational

Decision:
**Phase 32** (Deterministic PM Translation Layer / Manifest Phase 13, Tracks 13A–13C) is **closed**. **PASS_LOCAL_AND_LIVE** is recorded: production at `https://controltower.bratek.io` matches the governed end-to-end path — `/healthz` returns `{"status":"ok"}`, login works, CSV upload executes a run, `publish_packet.json` exists with **`pm_translation_v1`**, and the operator surface renders correctly. The system is **production-operational** for this governed workflow.

Reason:
Live verification satisfies the Phase 32 definition of done in `build_control/09_CURRENT_BUILD_PACKET.md` and the acceptance pattern in `build_control/11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md`. No further Phase 32 translation or wiring work is required for closeout.

Impact:
- `build_control/state.json`, `06_STATUS_BOARD.md`, `09_CURRENT_BUILD_PACKET.md`, and `02_BUILD_MANIFEST.md` are synchronized to **Phase 32 COMPLETE**; **current blocker: none**.
- **Next governed lane:** **Phase 33** — operator usability + polish (**presentation / projection only**), **not started** until **pre-execution gate** and explicit implementation authorization.
- **Platform-era roadmap** (`build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md`) remains **separately gated**; Phase 32 closeout does **not** authorize NocoBase, solver, OpenProject, or multi-system deployment work.

Status:
Active