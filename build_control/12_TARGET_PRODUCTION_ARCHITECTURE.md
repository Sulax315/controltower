# Target production architecture (approved — future)

## Authority and scope

This document records the **approved target production architecture** and **post-closeout platform direction** for Bratek Control Tower and its optional surrounding systems.

**This is not the current governed implementation lane.** No component described here as “future” is authorized for implementation until **each** such component is explicitly authorized in the decision log (Phase 32 closeout, including live verification, **is complete** per `build_control/state.json`; **platform-era** tracks remain deferred until separately opened).

**Single source of detailed architecture:** this file. Summary pointers live in `build_control/00_MASTER_PLAN.md` and the executive snapshot in `06_STATUS_BOARD.md`.

---

## Architectural separation principle

1. **Control Tower** remains the **authoritative schedule intelligence brain**: deterministic ingestion of imported schedule truth (e.g. Asta CSV), logic model, drivers, risks, command brief, intelligence artifacts, deterministic PM translation assembly, and operator projection of those artifacts.
2. **Optional support systems** may surround Control Tower for workflow, administration, collaboration, or **scenario optimization** only. They **must not** replace, override, or redefine the deterministic reasoning core or the imported schedule as the system of record for “what the schedule says.”
3. **Generic PM or collaboration platforms** are **not** Control Tower and **must not** become the deterministic reasoning core.

---

## Control Tower (core — non-optional identity)

- **Role:** Deterministic schedule intelligence, evidence, publish assembly, authenticated operator product at the Control Tower domain.
- **Hostname (target):** `controltower.bratek.io` (current production intent; unchanged as the brain’s primary product surface unless governance revises).

---

## Optional optimization service (future)

- **Technology direction:** OR-Tools and/or PyJobShop-style **separate service** (exact stack TBD at implementation time).
- **Role:** **Scenario solving only** (what-if, optimization runs against defined inputs). Outputs are advisory scenarios unless governance explicitly defines promotion rules into any future workflow.
- **Non-negotiable:** Never replaces **imported deterministic schedule truth** produced and owned by Control Tower’s intake and engine. The solver does not become the source of “official” finish/driver/risk conclusions for weekly PM review unless explicitly governed otherwise in a future decision.

**Hostname (target):** `solver.internal.bratek.io` **or** a **private-only** network route with no requirement for public internet exposure.

---

## Optional workflow / admin platform (future)

- **Technology direction:** **NocoBase** (or successor governed equivalent).
- **Role:** Surrounding **operations, workflow, and tracking** — not schedule intelligence, not deterministic engine ownership.

**Hostname (target):** `ops.bratek.io`.

---

## Optional broad PM / collaboration layer (future)

- **Technology direction:** **OpenProject** (or successor governed equivalent).
- **Role:** Optional **PM/collaboration** — issues, broader project communication, work packages as appropriate. **Not** the deterministic schedule reasoning core.

**Hostname (target):** `pm.bratek.io` **or** `openproject.bratek.io` (choose one canonical name at implementation time; both are placeholders until DNS and deployment are fixed).

---

## Domain summary (target)

| Domain (target) | Intended role |
|-----------------|---------------|
| `controltower.bratek.io` | Control Tower product — schedule intelligence brain + operator surface |
| `ops.bratek.io` | NocoBase (or equivalent) — workflow / admin / ops tracking |
| `pm.bratek.io` or `openproject.bratek.io` | OpenProject (or equivalent) — optional collaboration; not core brain |
| `solver.internal.bratek.io` (or private route) | Optimization service — scenario-only |

---

## Preferred hosting topology

- **Preferred:** **two VMs** — separation between Control Tower (and tightly coupled runtime) and surrounding platforms (and/or solver), with clear network boundaries.
- **Acceptable initially:** **one VM** with **strong isolation** (separate processes, separate databases, clear domain/routing separation) until scale or security policy requires split.

---

## Data and storage direction (target)

- **Postgres** for relational state where appropriate **per service**.
- **Separate databases** per major component (no shared DB across Control Tower brain and generic PM/solver unless explicitly governed for narrow integration reads).
- **Artifact-first:** Control Tower (and aligned services) continue to treat **file- or blob-backed artifacts** as first-class evidence (runs, bundles, publish packets, manifests). Postgres complements; it does not replace artifact traceability for deterministic outputs unless a future governance decision explicitly migrates a contract.

---

## Phased rollout sequence (approved order)

1. **Finish current Control Tower gate** — live domain verification and Phase 32 definition-of-done per `build_control/09_CURRENT_BUILD_PACKET.md` and `11_TRUSTED_EGRESS_LIVE_VERIFICATION_RUNBOOK.md`.
2. **Harden Control Tower** — production stability, monitoring, deployment discipline (aligned to governed “hardening” phases such as Phase 34 direction in the build packet; exact tracks TBD when authorized).
3. **Add NocoBase** at `ops.bratek.io` — workflow/admin surrounding layer only.
4. **Add solver service** — private or `solver.internal.bratek.io`, scenario-only, non-authoritative over imported schedule truth.
5. **Decide on OpenProject later** — optional; no commitment to timeline in this architecture document until explicitly authorized.

---

## Implementation status

| Item | Status |
|------|--------|
| Control Tower brain + current operator/upload/publish path | **In repo**; **live verification complete** (`PASS_LOCAL_AND_LIVE`); production operational for governed path per `build_control/04_DECISION_LOG.md` |
| NocoBase, OpenProject, OR-Tools/PyJobShop service | **Not implemented** — **deferred** until closeout + hardening sequence above |

---

## Related governance

- `build_control/04_DECISION_LOG.md` — decision entry adopting this target architecture.
- `build_control/00_MASTER_PLAN.md` — summary “Target production architecture” section.
- `build_control/01_PRODUCT_DEFINITION.md` — product identity vs optional layers.
