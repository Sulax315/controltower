# Real-Project Validation Runbook

This runbook defines the deterministic Phase 30 validation and hardening loop for the browser product entry and authoritative operator surface:

- `/`
- `/publish/operator/{run_id}`

The goal is to validate real weekly schedule-review utility using the browser-first product flow and capture friction in a structured, run-linked way without introducing a second product surface.

## Preconditions

- Browser product is reachable and authenticated.
- A real or representative Asta CSV is available.
- Validation capture is performed in the **Real-Project Validation** section on `/publish/operator/{run_id}`.

## Validation Sequence (Single Run)

1. Open `/`.
2. Authenticate.
3. Upload the Asta CSV from browser entry.
4. Confirm redirect lands on `/publish/operator/{run_id}`.
5. Perform a realistic meeting rehearsal:
   - Read command brief top-to-bottom once.
   - Explain driver path and finish linkage from the graph.
   - Cross-check risk evidence against highlighted graph nodes.
   - Use focus controls to trace one task to finish.
   - Use print mode (`?print=1`) and assess stakeholder handout readability.
6. Capture structured friction in the in-page validation section.
7. Save the validation note.
8. Open validation markdown for the run and archive findings for hardening review.

## Structured Friction Categories

Each category is scored 1..5 with optional friction notes:

- `command_brief_clarity`
- `evidence_precision`
- `graph_comprehension`
- `interaction_flow`
- `export_usefulness`
- `stakeholder_readability`
- `entry_upload_flow`

Additional bounded text fields:

- Open friction
- High-value hardening candidate

## Validation Artifacts

Saving validation writes deterministic artifacts under the run's existing artifact directory:

- `operator_validation.json`
- `operator_validation.md`

These artifacts are run-linked and can be reviewed during hardening decisions.

A browser download route is also available for validated runs:

- `/publish/operator/{run_id}/validation.md`

## Hardening Decision Rule

Apply hardening only when all conditions hold:

1. Friction is observed during real or realistic run validation.
2. Friction can be addressed by thin projection or presentation changes.
3. No new intelligence is introduced.
4. No new app surface is introduced.

## Durable Session Output

For each validation session, copy `docs/REAL_PROJECT_VALIDATION_SESSION_TEMPLATE.md`,
fill it with the run-specific evidence and decisions, and store it in your governed notes location.

