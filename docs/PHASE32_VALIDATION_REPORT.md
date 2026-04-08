# Phase 32 Validation Report

## Scope

- Phase: `32 — Real Project Validation + Hardening`
- Surfaces validated:
  - `/`
  - `/entry/upload`
  - `/publish/operator/{run_id}`
  - print/export path (`?print=1`)
- Governance constraints honored:
  - presentation/execution access only
  - no browser-side intelligence
  - no new product surfaces

## Workflow Used

- Runbook: `docs/REAL_PROJECT_VALIDATION_RUNBOOK.md`
- Checklist: `docs/REAL_PROJECT_VALIDATION_CHECKLIST.md`
- Session capture template: `docs/REAL_PROJECT_VALIDATION_SESSION_TEMPLATE.md`

## Run-Linked Validation Evidence

For each validated run, capture:

- `run_id`
- source CSV
- operator
- date/environment
- friction scores and notes
- hardening actions taken

Primary run-linked artifacts:

- `runs/<run_id>/artifacts/operator_validation.json`
- `runs/<run_id>/artifacts/operator_validation.md`

## Thin Hardening Applied In This Phase

- Validation categories now use clearer operator-facing labels:
  - Entry / Upload
  - Command Brief Clarity
  - Evidence Trust
  - Graph Usability
  - Interaction Flow
  - Export Usefulness
  - Stakeholder Clarity
- Graph node interaction usability improved:
  - keyboard focus/select support (`Enter` / `Space`)
  - node tooltip metadata for faster inspection
  - visible focus ring and pointer affordance

## Notes

This report intentionally excludes product expansion. Any future changes must remain deterministic and justified by captured friction.