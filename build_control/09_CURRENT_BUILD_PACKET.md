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

Phase 32 — Translation + Assembly + Publish

Status:

32A — COMPLETE (Finish / Delta / Driver translation)
32B — COMPLETE (Fragility / Risk / Pressure)
32C — COMPLETE (PM meeting-language assembly)
Upload → Run → Publish wiring — COMPLETE (in-repo)
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

Live Truth (CRITICAL)

⚠️ NOT VERIFIED from governed automation path

As of latest check, HTTP(S) requests to `https://controltower.bratek.io/` from the verification environment may be **intercepted by FortiGuard / corporate web filtering** (“Web Page Blocked”, category Unrated) before the request reaches the application. That blocks **content inspection** of the live Control Tower surface from that path and is **not** by itself proof the deployed app is stale or broken.

Remaining risks until live origin is confirmed:

- Live stack not redeployed to commit that includes wiring
- Wrong process or stale checkout on server
- `state_root`/runtime path mismatch on server
- Auth or CSRF/session differences vs local
- DNS or TLS trust differences per client
4. Last Completed Work

End-to-end wiring implemented:

Upload → execute_run → publish_packet.json persisted → operator render

Key additions:

publish_packet.json written during export
pm_translation_v1 fully assembled and included
operator surface loads persisted publish artifact
validation updated for backward compatibility

Tests:

focused tests passing
full suite: 340 passed, 5 unrelated failures
5. Current Blocker

LIVE DOMAIN VERIFICATION PENDING

Local answers are known PASS. Open questions are **only** for production:

- Does live `/` serve the same entry upload surface (not a legacy shell)?
- Does live `POST /entry/upload` complete and redirect?
- Does live server runtime contain `publish_packet.json` for new runs?
- Does live operator render `publish-pm-translation-payload`?

If verification runs from a filtered network, confirm whether **FortiGuard / proxy policy** is blocking the URL before concluding the app is wrong.

6. Next Required Action

**Canonical step-by-step:** `build_control/11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md` (prerequisite network gate, URLs, markers, upload, artifacts, PASS/FAIL, drift triage).

Perform LIVE FLOW VERIFICATION from a **trusted egress** (operator workstation on allowlisted network, VPN to prod, or monitoring host):

Browser:
Load `https://controltower.bratek.io/`
Confirm correct upload UI (`runs-home-upload`, action `/entry/upload`)
Execution (only if safe for production):
Upload valid CSV with CSRF
Confirm 303 → `/publish/operator/{run_id}`
Runtime (server filesystem or governed diagnostics):
Confirm `publish_packet.json` under configured `state_root`
Operator:
Confirm `publish-pm-translation-payload` in HTML

If automation is blocked: **allowlist** `controltower.bratek.io` / fix FortiGuard categorization, or run manual browser verification.
7. Known Risks
Repo vs live drift
Deployment not updated
Environment path/state_root mismatch
CSRF/auth interfering with upload
Silent execution failure on server
8. Definition of Done (Phase 32)

System is complete ONLY when:

Upload works from browser
Run executes on server
publish_packet.json exists
pm_translation_v1 is present
Operator surface renders full meeting summary
Verified on live domain
9. Next Phase (Not Yet Authorized)

Post-verification:

Phase 33 — Operator usability + polish (presentation only)
Phase 34 — Deployment hardening / monitoring

DO NOT START until live verification passes

10. Approved target production architecture (future — not current lane)

**Document:** `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md` (summary in `build_control/00_MASTER_PLAN.md`).

Control Tower remains the **core brain**; optional future layers (NocoBase at `ops.bratek.io`, solver service internal/private, OpenProject at `pm.bratek.io` / `openproject.bratek.io`) are **support-only** and **not implemented** until after live verification and governed hardening per that document’s rollout sequence. **Decision:** `build_control/04_DECISION_LOG.md` (2026-04-10).