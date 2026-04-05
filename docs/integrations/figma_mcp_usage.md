# Figma and MCP integration — usage guardrails

This document defines how **Figma** and **MCP-assisted tooling** may interact with Control Tower’s **published intelligence packet** UI. It is **documentation only**; it does not load at runtime and imposes no technical coupling.

## Roles

| Artifact | Role |
|----------|------|
| **Figma** | **Reference-only.** Visual exploration, spacing studies, and communication—not a source of truth for markup, CSS selectors, or behavior. |
| **MCP (Figma or design-related servers)** | **Read-only assistive.** May fetch structure, measurements, or assets to inform human decisions. Outputs are **drafts**, not deployments. |
| **Repository (templates + CSS + tests)** | **Authoritative** for what ships, subject to `docs/design/publish_layout_spec.md`. |

## Allowed uses

The following are **in bounds** when a human owner reviews and merges work:

1. **UI refinement suggestions** — Recommend typography, spacing, contrast, or density adjustments grounded in Figma or MCP reads; implement manually in `site.css` / templates after checking `publish_layout_spec.md`.
2. **Isolated component generation** — Produce standalone HTML/CSS snippets or small prototypes for a single component (e.g. a KPI tile variant); integrate by hand into the existing BEM-style classes and stable IDs.
3. **Alternative layout exploration** — Explore column order, rail placement, or dark/light variants in Figma or throwaway branches; only promote changes that are reconciled with the authoritative layout spec and tests.

## Forbidden uses

The following are **out of bounds** for Figma- or MCP-driven automation without a normal product/engineering change process:

1. **Backend modification** — No API, route handler, service, or config changes justified solely by “Figma says so” or MCP output.
2. **Direct template overwrite** — No bulk replacement of `packet_detail.html` (or related templates) from generated output without line-by-line reconciliation to `publish_layout_spec.md` and existing `pkt-*` contracts.
3. **Route creation** — No new HTTP routes introduced to “serve Figma” or MCP experiments inside the production app surface.
4. **Runtime dependency introduction** — No new packages, CDN embeds, or runtime calls to Figma/MCP from Control Tower’s server or client bundles for the packet page.

## Figma → Control Tower mapping (reference)

Use this table when translating frames or components into **discussion** or **manual** implementation work—not as an automated mapping.

| Figma frame / component (example names) | Control Tower publish UI zone | Typical HTML/CSS anchors |
|----------------------------------------|------------------------------|---------------------------|
| Packet header / title bar | Toolbar | `.pkt-toolbar--intel`, `.pkt-toolbar-title` |
| Risk / movement summary row | Command strip | `#pkt-command-strip`, `.pkt-command-strip__inner` |
| Five-field operator brief | Command brief bar | `#pkt-command-brief-bar`, `.pkt-command-brief-bar__*` |
| Metric tiles row | KPI band | `.pkt-kpi-row`, `.pkt-kpi-card` |
| In-page section nav | Section TOC | `.pkt-section-toc` |
| Executive narrative block | Executive summary | `#pkt-sec-summary`, `data-section-key="executive_summary"` |
| “What changed / matters / do” trio | Intelligence rail | `#pkt-intelligence-rail`, `.pkt-intelligence-rail__*` |
| Finish + delta body | Finish outlook | `#pkt-sec-finish` |
| Risk list body | Risks | `#pkt-sec-risks` |
| Driver emphasis + list | Drivers | `#pkt-sec-drivers` |
| Decisions + actions | Actions | `#pkt-sec-actions` |
| Evidence / appendix | Source evidence | `#pkt-sec-evidence` |
| Side lists / quick stats | Sidebar rail | `.pkt-intel-rail`, `.pkt-rail-*` |

Names in Figma may differ; align by **operator intent** and the authoritative spec, not by label string equality.

## Future workflow (optional, manual)

A **non-mandatory** workflow for teams that choose to use Figma + MCP together:

1. **Design in Figma** — Lock intent: zones, hierarchy, and density; avoid inventing new data fields without a product decision.
2. **Read via MCP** — Inspect frames, export specs, or component metadata as **read-only** input.
3. **Generate candidate UI** — Produce **candidates** (snippets, branch diffs, Storybook-like sandboxes) outside the default merge path.
4. **Manually reconcile into Control Tower** — A developer applies changes in-repo: templates, CSS, tests, and **updates** `docs/design/publish_layout_spec.md` when layout contracts change.

Skipping any step—or skipping reconciliation—is acceptable only if no shipping code changes; **generated output never merges itself.**

## Related documents

- `docs/design/publish_layout_spec.md` — Authoritative layout zones and naming for the publish-facing packet UI.
