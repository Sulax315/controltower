# Publish layout specification (authoritative)

This document is the **authoritative UI specification** for the Control Tower **published intelligence packet** operator surface—the HTML layout presented after a packet exists in runtime (including the post-publish view). It defines **what the product must preserve** when evolving templates, CSS, or static assets for that surface.

Treat every other source as subordinate to this spec unless this file is explicitly updated.

## Source precedence

| Source | Role |
|--------|------|
| **This specification** | Authoritative for layout zones, naming intent, and operator UX contracts for the publish-facing packet view. |
| **Figma** | **Reference-only.** May illustrate density, hierarchy, or exploration; it does not override this document or shipped markup. |
| **MCP / automated outputs** | **Non-authoritative.** Suggestions, drafts, and generated snippets are not contracts; they require human review and reconciliation against this spec and the live template/CSS. |

## Major layout zones (top to bottom)

Zones are listed in **canonical reading order** for the packet detail page. Implementations may wrap regions in additional structure for responsiveness, but **semantic zones and operator meaning** must remain recognizable.

### 1. Toolbar (packet header)

- Identity: packet title, project, period, type, packet ID, status.
- Primary actions: export, publish (when applicable), navigation to related flows.
- **Not** a substitute for the command strip or command brief; it carries metadata and actions, not the five-field operator brief.

### 2. Command strip (live signals)

- **Purpose:** Derived, client-enhanced summary of risk posture and movement (e.g. finish, delta, risk level, driver, status), typically hydrated from packet JSON / DOM.
- **Naming convention:** Prefer stable IDs and classes prefixed with `pkt-command-strip` and related `pkt-cmd-*` hooks so scripts and tests can target them without brittle selectors.

### 3. Command brief bar (operator five-liner)

- **Purpose:** Deterministic, server-rendered **Finish | Driver | Risks | Need | Doing** line optimized for fast scanning.
- **Naming convention:** Container `pkt-command-brief-bar`; cells use `pkt-command-brief-bar__cell`, labels `pkt-command-brief-bar__label`, values `pkt-command-brief-bar__value`.
- **Relationship to command strip:** Complementary. The strip emphasizes live/dynamic signals; the brief bar emphasizes the fixed five-field operator frame.

### 4. KPI band

- **Purpose:** Compact numeric / categorical indicators (e.g. finish, delta, risk, cycles, open ends, margin) for at-a-glance posture.
- **Naming convention:** `pkt-kpi-row`, `pkt-kpi-card`, `pkt-kpi-card__label`, `pkt-kpi-card__value`, with stable `id` hooks where JavaScript updates values (`pkt-kpi-*`).

### 5. Section table of contents

- **Purpose:** In-page navigation to major markdown-derived sections.
- **Naming convention:** `pkt-section-toc`; links anchor to section cards below.

### 6. Executive summary

- **Purpose:** First narrative block from the packet’s **executive summary** section—primary prose summary for leadership.
- **Naming convention:** Section card `pkt-section-card` with `id="pkt-sec-summary"` (or equivalent stable anchor); inner block `data-section-key="executive_summary"`.

### 7. Intelligence rail

- **Purpose:** Vault-aligned, read-only surface for **What changed**, **What matters**, **What to do**, fed from deterministic ingestion (not LLM output in layout).
- **Placement:** Immediately **below** the executive summary card in the main column unless this spec is amended.
- **Naming convention:** `pkt-intelligence-rail`, column titles `pkt-intelligence-rail__head`, body `pkt-intelligence-rail__body`.

### 8. Finish outlook, risks, drivers, actions

- **Purpose:** Remaining structured packet sections from persisted markdown (finish / delta, near-term risks, key drivers, required decisions + action register).
- **Naming convention:** Section cards with stable IDs: `pkt-sec-finish`, `pkt-sec-risks`, `pkt-sec-drivers`, `pkt-sec-actions`; subsection keys via `data-section-key` matching packet section keys (`finish_milestone_outlook`, `delta_vs_prior`, `near_term_risks`, `key_drivers`, `required_decisions`, `action_register`).

### 9. Source evidence / appendix

- **Purpose:** Traceability and appendix content (tables, provenance).
- **Naming convention:** `pkt-sec-evidence`, `data-section-key="source_evidence_appendix"`.

### 10. Sidebar rail (optional companion column)

- **Purpose:** Secondary lists (e.g. key risks, next actions, quick stats) when layout uses a two-column intel grid.
- **Naming convention:** `pkt-intel-rail`, `pkt-rail-*` for lists and stats.

### 11. Footer / metadata

- **Purpose:** API hints, timestamps, audit-friendly metadata.
- **Naming convention:** `pkt-form-footer`, `pkt-muted` for de-emphasized copy.

## Packet UI naming conventions (summary)

| Concept | Convention |
|---------|------------|
| Page shell | `pkt-page`, `pkt-page--intel`, `#packet-detail-shell` |
| Section cards | `pkt-section-card`, `pkt-section-card__head`, `pkt-section-card__title`, `pkt-section-card__body` |
| Section identity | Stable `id` on card (`pkt-sec-*`); `data-section-key` matching `IntelligencePacketSection.key` |
| Prose blocks | `pkt-prose`; specialized variants only when behavior differs (e.g. action register) |
| Command / KPI | `pkt-command-strip*`, `pkt-command-brief-bar*`, `pkt-kpi-*` |
| Intelligence rail | `pkt-intelligence-rail*` |

**Do not** rename these hooks for cosmetic reasons without updating this spec, tests, and any dependent scripts.

## Change control

Any material change to zones, order, or naming on the publish-facing packet page **must** be reflected here **before** or **together with** the implementation, and validated against existing acceptance tests and operator runbooks.

**Do not overwrite** `packet_detail.html` or related static assets without validating changes against this document.
