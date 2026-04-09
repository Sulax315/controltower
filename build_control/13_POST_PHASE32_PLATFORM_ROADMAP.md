# Post–Phase 32 platform roadmap (proposed — planning only)

## Authority and status

This document is a **governed planning artifact** for the **next architecture era** after the approved target production map in `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md`.

- **It does not authorize implementation.** No NocoBase, OpenProject, solver services, new VMs, Postgres wiring, or multi-domain deployment work is opened by this file alone.
- **It does not change deterministic schedule truth, translation logic, or engine behavior.** Any future storage or integration work must preserve the non-negotiables in `build_control/00_MASTER_PLAN.md` and `build_control/01_PRODUCT_DEFINITION.md`.
- **Current governed lane** remains Phase 32 **live domain verification** and closeout per `build_control/state.json`, `build_control/06_STATUS_BOARD.md`, `build_control/09_CURRENT_BUILD_PACKET.md`, and `build_control/11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md`.

When governance **authorizes** a future track, record it in `build_control/04_DECISION_LOG.md` and update `state.json` / `06_STATUS_BOARD.md` per `build_control/05_CONTINUITY_PROTOCOL.md`.

---

## 1. Phase framing (eras and tracks)

Work is grouped into **eras** (sequential gates) and **tracks** (parallelizable sub-efforts within an era). Names are **proposal labels** until manifest or decision-log adoption.

### Era 0 — Phase 32 closeout (current)

- **Gate:** `PASS_LOCAL_AND_LIVE` per runbook `11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md`; `publish_packet.json` and operator markers confirmed on `https://controltower.bratek.io`.
- **Outcome:** Product definition of done for Phase 32; permission to plan/authorize post-closeout lanes.

### Era 1 — Optional in-product polish (existing packet pointer)

- **Reference:** `build_control/09_CURRENT_BUILD_PACKET.md` §9 — **Phase 33 — Operator usability + polish (presentation only)**.
- **Role:** Thin, projection-only UX cohesion **without** new intelligence, translation rules, or multi-system platform work.
- **Authorization:** Explicit governance only, and **after** Phase 32 live verification unless decision log states otherwise.

### Era 2 — Control Tower production hardening (brain + operator on `controltower.bratek.io`)

- **Goal:** Production-grade **reliability, security posture, deploy discipline, and operability** for Control Tower **only**.
- **Suggested tracks:**
  - **2A — Deploy and runtime discipline:** reproducible release, config/secrets hygiene, documented rollback, drift detection (aligned to existing ops docs referenced in the runbook).
  - **2B — Monitoring and alerting:** health endpoints, structured logs, actionable alerts on failure modes that affect operators (not generic dashboard sprawl).
  - **2C — Backup and recovery:** evidence-backed restore of `state_root`/artifacts and configuration; RPO/RTO targets recorded in governance or ops docs.
  - **2D — Performance and capacity baselines:** defined SLOs for upload→run→publish path under expected CSV sizes; documented limits.

### Era 3 — Postgres + artifact-store formalization (Control Tower scope)

- **Goal:** **Explicit, documented** data ownership: file/blob **artifacts remain first-class** for deterministic outputs unless a future decision migrates a contract; **Postgres (if introduced)** holds **metadata, indexes, registry, or auxiliary state** that **references** artifacts — not a silent replacement of traceability.
- **Suggested tracks:**
  - **3A — Artifact contract registry:** canonical list of artifacts (`intelligence_bundle.json`, `manifest.json`, `publish_packet.json`, etc.), retention, and integrity expectations.
  - **3B — Storage boundary document:** what lives on disk/blob vs what may live in Postgres; migration rules; no change to deterministic translation assembly semantics without a governed Phase 13-class change.
  - **3C — Postgres introduction (if/when authorized):** separate DB for Control Tower **only**; migrations; backups tied to Era 2C.

### Era 4 — NocoBase introduction (`ops.bratek.io` target)

- **Goal:** Workflow/admin **around** runs and operations — **not** schedule determinism, not replacement of Control Tower artifacts as analytical truth.
- **Suggested tracks:**
  - **4A — Governance and data-flow spec:** which events/IDs are mirrored into ops tooling; no write-back that alters engine inputs without explicit decision.
  - **4B — Deployment and isolation:** own Postgres instance, network boundary, auth model; no shared database with Control Tower brain.
  - **4C — Minimal integrations:** read-only or ticket-style links to Control Tower URLs/run IDs as appropriate.

### Era 5 — Optional solver service introduction (private / `solver.internal.bratek.io` target)

- **Goal:** **Scenario-only** optimization (what-if), **advisory** outputs, **non-authoritative** over imported schedule truth and weekly PM conclusions.
- **Suggested tracks:**
  - **5A — API and trust boundary:** input/output contracts, explicit “scenario” labeling, no automatic promotion into command brief without governed rules.
  - **5B — Service deployment:** isolated runtime, secrets, rate limits; no public exposure unless decision log overrides.
  - **5C — Optional operator handoff:** projection-only surfacing of scenario results **as separate artifacts** from deterministic publish packet truth.

### Era 6 — OpenProject decision gate (`pm.bratek.io` / `openproject.bratek.io` target)

- **Goal:** **Decide** whether broad PM/collaboration adds net value vs cost; **no default implementation**.
- **Suggested tracks:**
  - **6A — Decision packet:** problem statement, integration surface, cost, security, and “what Control Tower still owns.”
  - **6B — Pilot or defer:** time-boxed pilot **or** explicit deferral recorded in decision log.
  - **6C — If implemented:** same isolation rules as NocoBase; **never** the deterministic reasoning core.

---

## 2. Sequencing and dependency logic

Recommended **order** (each step requires **governance authorization** before implementation):

| Order | Era / gate | Depends on |
|------|------------|------------|
| 0 | Era 0 — Phase 32 live verification | Local verification already satisfied; trusted-egress live PASS |
| 1 | Era 1 — Phase 33 polish (optional) | Era 0; explicit authorization; projection-only |
| 2 | Era 2 — Control Tower production hardening | Era 0 (and 1 if executed); **must complete baseline monitoring + backup/restore evidence** before calling “ready for adjacent platforms” |
| 3 | Era 3 — Postgres + artifact formalization | Era 2 **baseline** (operable CT, backups); **3A/3B should precede or gate 4** so storage semantics are clear before another Postgres-backed service |
| 4 | Era 4 — NocoBase | Eras 2–3 **documented boundaries**; isolated service + DB |
| 5 | Era 5 — Solver service | Era 4 per **approved rollout** in `12_TARGET_PRODUCTION_ARCHITECTURE.md` (NocoBase before solver); **never** before Control Tower hardening baseline |
| 6 | Era 6 — OpenProject decision | Any time **after** Era 0; implementation only if decision positive — typically **after** solver introduction **or** explicitly parallel **only** if decision log allows |

**What must happen before support systems are added**

1. **Live-verified** Control Tower on production domain with persisted publish path proven.
2. **Hardening baseline:** monitoring that detects failure + **restorable** backups of runtime evidence paths (Era 2).
3. **Written artifact/Postgres boundaries** for Control Tower (Era 3A–3B minimum) so “where truth lives” is not ambiguous when NocoBase appears.

**Parallelism**

- Within Era 2, tracks 2B (monitoring) and 2C (backup/recovery) should **start early** and **complete together** for a credible production gate.
- Era 3A (artifact registry) can **overlap** Era 2 if staffing allows; **3C (Postgres)** should not proceed without **2C** readiness.

---

## 3. Boundary rules (in / out / never)

### Control Tower (`controltower.bratek.io`)

**Belongs in Control Tower**

- Asta CSV intake, normalization, schedule logic model, drivers, risks, deltas, command brief, JSON intelligence, **deterministic PM translation assembly**, publish packet assembly, authenticated operator projection **of those artifacts**.

**Belongs outside Control Tower**

- Generic issue tracking, broad PM collaboration, org-wide workflow engines, **scenario optimization engines**, centralized log analytics for non-CT fleets (unless later scoped as CT-only ops).

**Must never replace deterministic schedule truth**

- Imported schedule **as analyzed by the engine**, published **deterministic** conclusions, and **traceable** translation statements. External systems may **reference** run IDs and URLs; they must not **re-score** or **overwrite** engine outputs without a new governed product decision.

### Postgres + artifact store (Control Tower)

**Belongs**

- Metadata, run registry, indexes, optional job state **pointing to** immutable or versioned artifacts.

**Outside / shared**

- No **shared logical database** with NocoBase/OpenProject/solver unless decision log documents a **read-only** exception and threat model.

**Never**

- Storing “the brief” or evidence **only** in Postgres **without** artifact-level traceability **unless** a future governance decision explicitly migrates the output contract with acceptance criteria.

### Backup / recovery / monitoring

**Belongs**

- Platform ops for Control Tower: backup/restore of configured `state_root`, configs, secrets management policy, alerts on health/run failures.

**Outside**

- Full enterprise SIEM strategy (unless org mandates); product feature work unrelated to operability.

**Never**

- Using monitoring hooks to **change** deterministic outputs or to bypass publish assembly.

### NocoBase (`ops.bratek.io`)

**Belongs**

- Operational tracking, approvals **of human process**, ticketing, checklists **around** delivery of CT value.

**Outside**

- Parsing Asta CSV, computing drivers/risks, assembling `pm_translation_v1`.

**Never**

- Becoming the **system of record** for schedule intelligence or meeting-language truth.

### Solver service

**Belongs**

- Optimization/scenario runs, **separate** API, **advisory** artifacts.

**Outside**

- Weekly “official” finish/driver/risk truth for PM review (remains Control Tower unless explicitly re-governed).

**Never**

- Silent replacement of imported schedule truth in operator-facing command surfaces without labeling and governance.

### OpenProject (optional)

**Belongs**

- Collaboration, work packages, cross-functional PM communication.

**Outside**

- Deterministic engine and publish assembly.

**Never**

- Authoritative schedule intelligence brain or translation source.

---

## 4. Acceptance structure (deterministic, evidence-based)

Each era/track is **complete** only with **recorded evidence** (logs, screenshots, command output, server paths, decision-log entry). Vague completion claims fail.

### Era 0 — Phase 32 closeout

- **PASS:** All rows in `11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md` §6 **PASS_LOCAL_AND_LIVE** satisfied; first failing step documented if FAIL.
- **Evidence:** Stored proof of healthz, authenticated upload markers, server-side `publish_packet.json` keys, operator HTML marker `publish-pm-translation-payload`.

### Era 1 — Phase 33 polish (if authorized)

- **PASS:** Stated UX goals met **without** new engine/translation logic; no new nondeterminism; regression tests pass.
- **Evidence:** Before/after capture or checklist; test run output; explicit “projection-only” review sign-off in decision log or status board.

### Era 2 — Control Tower production hardening

- **2A Deploy discipline:** **PASS:** Documented release path used at least once successfully; rollback or forward-fix path documented; known drift checks referenced.
- **2B Monitoring:** **PASS:** Alert or dashboard proof for **uptime/failed runs**; on-call/runbook link from `docs/` or ops.
- **2C Backup/recovery:** **PASS:** **Restore exercise** completed from backup to clean path; RPO/RTO numbers recorded; evidence of restored run artifacts or equivalent approved proof.
- **2D Performance baselines:** **PASS:** Documented max CSV size / timing for upload→publish path; failures documented as limits not silent breakage.

### Era 3 — Postgres + artifact formalization

- **3A Artifact registry:** **PASS:** Single doc/table in repo or governed doc listing required artifacts and lifecycle; linked from ops runbook or release doc.
- **3B Storage boundary:** **PASS:** Written boundary signed off in decision log; engineers can answer “where is SoR for X artifact?” without ambiguity.
- **3C Postgres (if done):** **PASS:** Migrations applied; backups tested; **no** regression in deterministic output parity tests vs artifact-only mode.

### Era 4 — NocoBase

- **PASS:** Service reachable at planned hostname; **separate** DB; **no** CT intelligence regression; integration spec implemented as approved (e.g. links/IDs only).
- **Evidence:** Deployment checklist, DNS/TLS proof, screenshot or API check, security review note if required by org.

### Era 5 — Solver

- **PASS:** Scenario outputs **labeled** and **not** merged into command brief unless explicit governed promotion rules exist (default: **no merge**).
- **Evidence:** API contract doc, sample scenario response, threat model for abuse, private network proof.

### Era 6 — OpenProject

- **Decision gate PASS:** Decision log entry **Implement / Defer / Reject** with rationale; if Implement, **Era 4-class** isolation acceptance reused.

---

## 5. Governance recommendation

### Where to record future phases

- **Primary recommendation:** Keep **`build_control/02_BUILD_MANIFEST.md` Phases 1–13** as the **closed book** for the reset product through Manifest Phase 13 / Phase 32. Do **not** add weighted Phases 14+ **until** governance authorizes the **first** post-closeout **implementation** sprint.
- **Use this file (`13_POST_PHASE32_PLATFORM_ROADMAP.md`)** as the **appendix / future roadmap** for the **platform era**: eras, tracks, boundaries, and acceptance patterns.
- **Optional packet pointer:** `09_CURRENT_BUILD_PACKET.md` should continue to name the **immediate** next action; it may reference this doc as **planning context** (see status board).

### When manifest revision **is** justified

- **Revise the manifest** (add **Phase 14+** with weights, tracks, completion rules) when:
  - Era 0 is **complete** and
  - A **specific** implementation phase (e.g. “Phase 34 — Production hardening” or “Phase 35 — NocoBase introduction”) is **authorized** in the decision log.

**Why wait:** Premature manifest phases create false “build order” authority and can violate the rule that work must align to **current** `state.json` / status board. The manifest’s **Build Order Rule** should only list phases that are **actually** in or entering the weighted model.

### Decision log discipline

- Each **authorization** to start Era 1–6 implementation gets a **dated** `04_DECISION_LOG.md` entry: scope, non-goals, rollback, and explicit reaffirmation that Control Tower remains the **authoritative brain**.

---

## 6. Related documents

- `build_control/12_TARGET_PRODUCTION_ARCHITECTURE.md` — approved target topology and rollout **order**.
- `build_control/00_MASTER_PLAN.md` — product identity and target architecture summary.
- `build_control/09_CURRENT_BUILD_PACKET.md` — immediate closeout and Phase 33/34 **pointers** (execution not authorized until gates pass).
- `build_control/11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md` — Era 0 verification steps.
