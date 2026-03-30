# Control Tower

Control Tower is a production-grade v1 intelligence layer that reads published ScheduleLab artifacts and authoritative ProfitIntel snapshots, normalizes them into one project contract, generates Obsidian-ready markdown, and serves the same intelligence through a lightweight browser UI.

This repo is intentionally additive. It does not replace ScheduleLab or ProfitIntel as systems of record. It consumes their existing outputs, preserves source provenance, and turns those outputs into durable weekly briefing artifacts.

## What Ships In V1

- Typed project snapshot contract with source provenance and trust indicators
- ScheduleLab adapter against published `published/` artifacts
- ProfitIntel adapter against authoritative snapshot/trust tables, with validation-db fallback discovery
- Explainable health/risk scoring across schedule, finance, and source trust
- Markdown generation for:
  - project dossier notes
  - weekly project briefs
  - portfolio weekly summary
- Obsidian export layer with stable dossier notes, rolling weekly notes, and optional date-stamped copies
- FastAPI browser UI for:
  - portfolio overview
  - ranked project list
  - project dossier preview
  - latest export run status
- CLI for build, preview, validate, export, serve, and acceptance
- Approval-gated orchestration loop with exactly-once trigger emission, review audit trail, and continuity writeback
- Deterministic selective-autonomy policy engine with low-risk auto-approval and high-risk escalation
- n8n-ready downstream execution events, deterministic pack selection, result ingest, and closeout visibility
- Operational entrypoints for daily, weekly, preflight, smoke, diagnostics, and release gate runs
- Runtime artifact index, latest pointers, diagnostics snapshots, and safe retention pruning
- Windows Task Scheduler and Linux cron/systemd wrapper packs
- Pytest suite and acceptance harness
- Repo-local operator skill for recurring weekly workflows

## Repo Layout

```text
ControlTower/
|-- src/controltower/
|   |-- adapters/
|   |-- api/
|   |-- domain/
|   |-- obsidian/
|   |-- render/
|   |-- services/
|   `-- acceptance/
|-- config/
|-- docs/
|-- tests/
|-- controltower.example.yaml
|-- run_controltower.py
`-- run_controltower_ui.py
```

## Quick Start

### 1. Install

```powershell
cd C:\Dev\ControlTower
py -3 -m pip install -e .[dev]
```

### 2. Configure

Copy the example config if you want to override defaults:

```powershell
Copy-Item .\controltower.example.yaml .\controltower.yaml
```

By default the app looks for:

- `C:\Dev\ScheduleLab\schedule_validator\published`
- `C:\Dev\ProfitIntel\data\runtime\profitintel.db`
- fallback ProfitIntel validation DBs under `C:\Dev\ProfitIntel\data\runtime` and `C:\Dev\ProfitIntel\artifacts\validation`

### 3. Validate Sources

```powershell
python .\run_controltower.py validate-sources
```

### 4. Preview Or Export Notes

Preview into Control Tower runtime state without touching the vault:

```powershell
python .\run_controltower.py build-all
```

Write into the configured Obsidian vault:

```powershell
python .\run_controltower.py build-all --write
```

Build only one project:

```powershell
python .\run_controltower.py build-project --project SU_WAVERLY --write
```

### 5. Launch Browser UI

```powershell
python .\run_controltower.py serve
```

Or:

```powershell
python .\run_controltower_ui.py
```

## Command Surface

- `python .\run_controltower.py validate-sources`
- `python .\run_controltower.py build-all`
- `python .\run_controltower.py build-all --write`
- `python .\run_controltower.py build-project --project <CANONICAL_CODE>`
- `python .\run_controltower.py build-portfolio --write`
- `python .\run_controltower.py acceptance`
- `python .\run_controltower.py review-simulate --profile low`
- `python .\run_controltower.py review-simulate --profile medium`
- `python .\run_controltower.py review-simulate --profile high`
- `python .\run_controltower.py review-list`
- `python .\run_controltower.py review-show --run-id <REVIEW_RUN_ID>`
- `python .\run_controltower.py review-approve --run-id <REVIEW_RUN_ID> --provider file`
- `python .\run_controltower.py review-reject --run-id <REVIEW_RUN_ID> --note "<reason>"`
- `python .\run_controltower.py review-emit-file --run-id <REVIEW_RUN_ID>`
- `python .\run_controltower.py execution-simulate --profile medium --provider file`
- `python .\run_controltower.py execution-queue-list`
- `python .\run_controltower.py execution-event-show --run-id <REVIEW_RUN_ID>`
- `python .\run_controltower.py execution-closeout-show --run-id <REVIEW_RUN_ID>`
- `python .\run_controltower.py execution-dead-letter-list`
- `python .\run_controltower.py execution-dispatch-retry --run-id <REVIEW_RUN_ID>`
- `python .\run_controltower.py execution-result-ingest --run-id <REVIEW_RUN_ID> --status succeeded --summary "Completed"`
- `python .\scripts\preflight_controltower.py`
- `python .\scripts\run_daily_controltower.py`
- `python .\scripts\run_weekly_controltower.py`
- `python .\scripts\smoke_controltower.py`
- `python .\scripts\diagnostics_snapshot_controltower.py`
- `python .\scripts\release_readiness_controltower.py`
- `python .\run_controltower.py serve`

## Review Auth Modes

- `auth.mode=prod` turns the full browser surface into a public-HTTPS, application-authenticated site. Anonymous users can reach `/login`, but protected UI and API routes require the configured app session credentials.
- App login now uses `app.public_base_url` plus `CODEX_AUTH_SESSION_SECRET`, `CODEX_AUTH_USERNAME`, and `CODEX_AUTH_PASSWORD` for the public session gate.
- `CODEX_REVIEW_MODE=dev` keeps the local review surface friction-light for Cursor demos. Review detail, approve, and reject stay directly usable in the browser UI and CLI.
- `CODEX_REVIEW_MODE=prod` turns the browser review plane into read-mostly mode until an operator signs in with the configured review session credentials.
- Production browser mutation auth now uses a signed session backed by `CODEX_REVIEW_SESSION_SECRET`, `CODEX_REVIEW_OPERATOR_USERNAME`, and `CODEX_REVIEW_OPERATOR_PASSWORD`.
- Legacy `CODEX_REVIEW_SHARED_TOKEN` is still accepted in config for compatibility, but production HTTP approve/reject no longer rely on shared-token-only mutation.

## Selective Autonomy

- Completed review runs are classified deterministically into `low`, `medium`, `high`, or `critical` risk.
- Decision modes are `auto_approve`, `manual_review`, or `escalate`.
- Low-risk runs can auto-approve through the same audited approval path when `CODEX_AUTONOMY_ENABLED=true` and `CODEX_AUTO_APPROVE_LOW_RISK=true`.
- High/critical runs can be marked escalated when `CODEX_ESCALATE_HIGH_RISK=true`.
- Policy metadata is persisted on the review run JSON, exposed in the UI/API/CLI, and mirrored into the continuity markdown artifacts.

## Downstream Execution Packs

- Approved or auto-approved runs emit a normalized `codex_run.approved` event contract with stable `event_id` and `trigger_id`.
- Control Tower selects one of `deploy_pack`, `smoke_pack`, `release_readiness_pack`, `report_pack`, `continuity_pack`, or `noop_pack` using deterministic keyword/rule matching across the run title, summary, prompt, artifacts, and decision reasons.
- File, webhook, and stub providers preserve the explicit contract instead of hiding downstream work behind custom glue.
- Dispatch now persists bounded retry state, pack validation, pack guard posture, dead-letter payloads, and closeout artifacts under the review run.
- Guarded packs are blocked in production unless `CODEX_EXECUTION_ALLOW_GUARDED_IN_PROD=true`.
- Downstream automation can POST closeout data back to `POST /api/execution/results`, which updates the review record, UI, closeout artifacts, and continuity artifacts.

## Core Architecture

- `adapters`: load and validate ScheduleLab and ProfitIntel source artifacts
- `domain`: typed normalized contract for project intelligence
- `services`: project identity resolution, health scoring, merge/orchestration
- `render`: markdown templates and note generation
- `obsidian`: filesystem-safe export and run-state manifests
- `api`: browser and JSON surface
- `acceptance`: smoke harness for end-to-end validation

## Key Design Choices

- Obsidian is the synthesis layer, never the system of record
- ScheduleLab published artifacts stay the schedule source of truth
- ProfitIntel snapshot/trust tables stay the finance source of truth
- Missing or low-trust source data stays visible in the note contract
- Every major conclusion carries source provenance forward
- Project identity merging is config-driven to avoid fake cross-system joins

## Additional Docs

- [Setup Guide](./docs/SETUP.md)
- [Configuration Guide](./docs/CONFIGURATION.md)
- [Config Reference](./docs/CONFIG_REFERENCE.md)
- [Operations Runbook](./docs/OPERATIONS_RUNBOOK.md)
- [Review Approval Runbook](./docs/REVIEW_APPROVAL_RUNBOOK.md)
- [n8n Execution Integration](./docs/N8N_EXECUTION_INTEGRATION.md)
- [Production Deployment Pack](./infra/deploy/controltower/README.md)
- [Vault Structure](./docs/VAULT_STRUCTURE.md)
- [Source Artifact Expectations](./docs/SOURCE_ARTIFACTS.md)
- [Weekly Runbook](./docs/RUNBOOK_WEEKLY.md)
- [Troubleshooting](./docs/TROUBLESHOOTING.md)
