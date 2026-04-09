Control Tower — Current Build Packet
1. System Identity

Control Tower is a deterministic schedule intelligence system.

Pipeline:
CSV → Intake → Graph → Intelligence → Translation (32A/32B) → Assembly (32C) → Publish

Non-negotiables:

No AI narrative generation
No heuristics
No UI intelligence
All outputs must be deterministic and traceable to source artifacts
2. Current Authorized Phase

**Phase 32 — Translation + Assembly + Publish — COMPLETE** (including **live** verification).

**Next governed lane (not started): Phase 33** — Operator usability + polish (**presentation / projection only**). Open **pre-execution gate** before implementation.

Status:

32A — COMPLETE (Finish / Delta / Driver translation)
32B — COMPLETE (Fragility / Risk / Pressure)
32C — COMPLETE (PM meeting-language assembly)
Upload → Run → Publish wiring — COMPLETE (in-repo and **production**)
Live end-to-end — **VERIFIED** (`PASS_LOCAL_AND_LIVE`)
3. Current State of System
Repo Truth
Upload route /entry/upload exists and is functional
execute_run() produces:
deterministic artifact set
publish_packet.json
publish_packet.json includes:
visualization
pm_translation_v1
Registry tracks:
publish_packet_path
publish_packet_exists
Operator surface:
prefers persisted publish_packet.json
falls back to deterministic rebuild if missing
Runtime Truth

For a successful run:

runtime/runs/{run_id}/artifacts/ contains:
intelligence_bundle.json
manifest.json
publish_packet.json (REQUIRED)
publish_packet.json contains:
pm_translation_v1
meeting_summary
visualization

Validation:

fails if publish_packet.json missing (v2 manifest)
legacy runs still supported
Local Runtime Truth (VERIFIED)

Verified on `127.0.0.1:8787` with governed config:

- `GET /` — browser entry upload surface (`runs-home-upload`, form → `/entry/upload`)
- `POST /entry/upload` — 303 → `/publish/operator/{run_id}`
- `run.json` — `status: completed`
- `artifacts/` — `intelligence_bundle.json`, `manifest.json`, `publish_packet.json`
- `publish_packet.json` — `pm_translation_v1`, `meeting_summary`, `visualization`
- Operator page — includes `id="publish-pm-translation-payload"`

Live Truth (VERIFIED)

**Status:** `PASS_LOCAL_AND_LIVE` — production verified on `https://controltower.bratek.io` (trusted egress / operator path).

Confirmed:

- `GET /healthz` → `{"status":"ok"}`
- Login works
- Upload works; run executes
- `publish_packet.json` exists for successful runs
- `pm_translation_v1` present in publish packet
- Operator surface renders correctly (full meeting summary / PM translation payload)

Ongoing operational discipline (deploy freshness, config drift, backups) remains outside this packet’s definition of Phase 32 done but is normal production responsibility.
4. Last Completed Work

**Phase 32 closeout:** End-to-end wiring and live verification complete.

Upload → execute_run → publish_packet.json persisted → operator render — **verified in production**.

Key additions (already delivered):

publish_packet.json written during export
pm_translation_v1 fully assembled and included
operator surface loads persisted publish artifact
validation updated for backward compatibility

Tests:

focused tests passing
full suite: 340 passed, 5 unrelated failures (historical note; re-run as needed)
5. Current Blocker

**None** (Phase 32 definition of done satisfied).
6. Next Required Action

1. **Phase 33 pre-execution gate:** Record scope, acceptance, and explicit **projection-only** boundaries (no new engine logic; no deterministic translation-rule changes unless a new phase is authorized).
2. **Implementation** only under prompts that explicitly authorize **Phase 33**.

Reference: `build_control/06_STATUS_BOARD.md`, `build_control/state.json`, `build_control/11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md` (historical evidence pattern for live checks).
7. Known Risks

Normal production risks only: deploy vs repo drift, `state_root`/config mismatch, auth/CSRF regressions, silent execution failures — to be managed via ops runbooks and monitoring; not open Phase 32 defects once verification record is maintained.
8. Definition of Done (Phase 32)

**ACHIEVED.** All of the following were required and are **satisfied**:

Upload works from browser
Run executes on server
publish_packet.json exists
pm_translation_v1 is present
Operator surface renders full meeting summary
Verified on live domain
9. Next Phase

**Phase 33 — Operator usability + polish (presentation / projection only)**

**Phase 34 — Deployment hardening / monitoring** (build packet pointer; not started)

**Start Phase 33** only after **pre-execution gate** and **explicit** governance authorization in prompts. Phase 33 must remain **projection-only** relative to deterministic artifacts.

10. Approved target production architecture (future — not current lane)

**Document:** `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md` (summary in `build_control/00_MASTER_PLAN.md`).

Control Tower remains the **core brain**; optional future layers (NocoBase at `ops.bratek.io`, solver service internal/private, OpenProject at `pm.bratek.io` / `openproject.bratek.io`) are **support-only** and **not implemented** until **decision log** authorizes each era per `build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md` (Phase 32 closeout is complete; platform rollout sequence still applies). **Decision:** `build_control/04_DECISION_LOG.md` (2026-04-10).

11. Post–Phase 32 platform-era roadmap (proposed — planning only)

**Document:** `build_control/13_POST_PHASE32_PLATFORM_ROADMAP.md`.

Use this for **sequencing, boundaries, and acceptance patterns** for hardening, artifact/Postgres formalization, backup/recovery/monitoring, and deferred optional platforms. It does **not** replace `state.json` for the active lane and does **not** authorize implementation without a new decision-log entry.
