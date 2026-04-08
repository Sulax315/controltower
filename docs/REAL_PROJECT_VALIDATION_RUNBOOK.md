# Real-Project Validation Runbook (Phase 32)

This runbook defines the deterministic Phase 32 real-project validation and hardening loop for browser entry/upload and the authoritative operator surface:

- `/`
- `/entry/upload`
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

Each category is scored 1..5 with optional friction notes. Operator-facing labels and run-artifact keys:

- `Entry / Upload` -> `entry_upload_flow`
- `Command Brief Clarity` -> `command_brief_clarity`
- `Evidence Trust` -> `evidence_precision`
- `Graph Usability` -> `graph_comprehension`
- `Interaction Flow` -> `interaction_flow`
- `Export Usefulness` -> `export_usefulness`
- `Stakeholder Clarity` -> `stakeholder_readability`

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

For each validation session:

1. Execute the checklist in `docs/REAL_PROJECT_VALIDATION_CHECKLIST.md`.
2. Copy `docs/REAL_PROJECT_VALIDATION_SESSION_TEMPLATE.md`.
3. Fill it with run-specific evidence, friction, and hardening decisions.
4. Store the completed note in your governed notes location with the run_id in the filename.

