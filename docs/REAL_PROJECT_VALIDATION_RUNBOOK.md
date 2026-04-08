# Real-Project Validation Runbook

This runbook defines the deterministic Phase 29 validation loop for the authoritative operator surface:

- `/publish/operator/{run_id}`

The goal is to validate real weekly schedule-review utility and capture friction in a structured, run-linked way without introducing a second product surface.

## Preconditions

- A publishable run exists with deterministic artifacts.
- Operator can open `/publish/operator/{run_id}`.
- Validation capture is performed in the **Real-Project Validation** section on that page.

## Validation Sequence (Single Run)

1. Generate or select the target run.
2. Open `/publish/operator/{run_id}`.
3. Perform a realistic meeting rehearsal:
   - Read command brief top-to-bottom once.
   - Explain driver path and finish linkage from the graph.
   - Cross-check risk evidence against highlighted graph nodes.
   - Use focus controls to trace one task to finish.
   - Use print mode (`?print=1`) and assess stakeholder handout readability.
4. Capture structured friction in the in-page validation section.
5. Save the validation note.

## Structured Friction Categories

Each category is scored 1..5 with optional friction notes:

- `command_brief_clarity`
- `evidence_precision`
- `graph_comprehension`
- `interaction_flow`
- `export_usefulness`
- `stakeholder_readability`

Additional bounded text fields:

- Open friction
- High-value hardening candidate

## Validation Artifacts

Saving validation writes deterministic artifacts under the run's existing artifact directory:

- `operator_validation.json`
- `operator_validation.md`

These artifacts are run-linked and can be reviewed during hardening decisions.

## Hardening Decision Rule

Apply hardening only when all conditions hold:

1. Friction is observed during real or realistic run validation.
2. Friction can be addressed by thin projection or presentation changes.
3. No new intelligence is introduced.
4. No new app surface is introduced.

