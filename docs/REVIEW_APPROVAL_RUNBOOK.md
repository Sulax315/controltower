# Review Approval Runbook

This runbook covers the approval-gated orchestration loop that moves a review run through:

- `pending_review`
- `escalated`
- `approved`
- `triggered`
- `rejected`
- `failed`

Use the file trigger provider for local demos and the webhook trigger provider for n8n or other downstream automation.

## Selective Autonomy

Selective autonomy is a deterministic policy layer that evaluates each completed run before it enters the review plane. It persists:

- `risk_level`: `low`, `medium`, `high`, or `critical`
- `decision_mode`: `auto_approve`, `manual_review`, or `escalate`
- `decision_reasons`: readable deterministic rule hits
- `policy_version`
- `policy_evaluated_at`
- `auto_approved_at`
- `escalated_at`

Risk meanings in this system:

- `low`: documentation, continuity/history, read-only/reporting, or low-risk UI copy with clear positive evidence
- `medium`: ordinary product/code changes that still require review
- `high`: risky technical scope such as migration/config/API/model changes
- `critical`: auth/security/session, control-plane, routing/TLS/domain, destructive, or prod deploy/restart scope

Default rule posture is conservative. False positives are preferred over unsafe autonomy.

## Local Dev Flow

1. Simulate low, medium, and high-risk completed runs.

```powershell
python .\run_controltower.py --config .\controltower.yaml review-simulate --profile low
python .\run_controltower.py --config .\controltower.yaml review-simulate --profile medium
python .\run_controltower.py --config .\controltower.yaml review-simulate --profile high
```

2. List recent review runs and copy the `run_id`.

```powershell
python .\run_controltower.py --config .\controltower.yaml review-list
```

3. Open the review page or inspect the run in CLI.

```powershell
python .\run_controltower.py --config .\controltower.yaml review-show --run-id <RUN_ID>
python .\run_controltower.py --config .\controltower.yaml serve
```

4. Approve or reject the medium/high run when needed. Low-risk runs will auto-approve when selective autonomy is enabled and low-risk auto-approval is allowed.

```powershell
python .\run_controltower.py --config .\controltower.yaml review-approve --run-id <RUN_ID> --provider file
python .\run_controltower.py --config .\controltower.yaml review-reject --run-id <RUN_ID> --note "Hold for another validation pass."
```

5. Inspect the emitted trigger payload and continuity artifact.

```powershell
python .\run_controltower.py --config .\controltower.yaml review-show --run-id <RUN_ID>
```

Expected local file outputs:

- trigger payload queue: `.controltower_runtime/orchestration/trigger_queue/<timestamp>_<run_id>.json`
- approved payload artifact: `.controltower_runtime/orchestration/reviews/<run_id>/decision_artifacts/approved_payload_latest.json`
- continuity runtime artifact: `.controltower_runtime/orchestration/continuity/<run_id>.md`
- continuity vault artifact: `<vault_root>/10 Exports/Control Tower Review History/<run_id>.md`

Expected policy behaviors:

- `low` demo: auto-approved, exactly one trigger emitted, continuity updated, notification suppressed by default
- `medium` demo: remains `pending_review` with normal notification
- `high` demo: marked `escalated` with high-signal notification

## n8n Wiring Flow

1. Codex or another upstream process posts a completed run into Control Tower and a review run is created.
2. Control Tower evaluates deterministic policy, persists risk/decision metadata, and exposes the run in `/runs` and `/reviews/<run_id>`.
3. Low-risk runs may auto-approve through the normal approval path. Medium-risk runs remain review-gated. High/critical runs are marked escalated.
4. Control Tower persists reviewer or policy-actor metadata, writes the durable approved payload artifact when approved, and emits exactly one webhook or file payload.
5. The downstream watcher or n8n workflow consumes the emitted payload and continues the next step.

## Trigger Provider Options

Set these with YAML, environment variables, or both:

- `CODEX_TRIGGER_PROVIDER=file|webhook|none`
- `CODEX_TRIGGER_FILE_DIR=<absolute-or-relative-path>`
- `CODEX_TRIGGER_WEBHOOK_URL=<https-endpoint>`
- `CODEX_TRIGGER_WEBHOOK_TIMEOUT_MS=<milliseconds>`

Behavior:

- `file`: writes one JSON file per trigger event for a local watcher or n8n file poller.
- `webhook`: POSTs the approved payload with an idempotency key derived from the review run.
- `none`: records approval without downstream emission. The run stays `approved`.

Selective autonomy knobs:

- `CODEX_AUTONOMY_ENABLED=true|false`
- `CODEX_AUTO_APPROVE_LOW_RISK=true|false`
- `CODEX_ESCALATE_HIGH_RISK=true|false`
- `CODEX_POLICY_VERSION=v1`
- `CODEX_NOTIFY_ON_AUTO_APPROVE=true|false`

Auto-approval and escalation can always be overridden by an operator through the normal manual review surface when the run remains reviewable.

## Dev vs Prod Review Behavior

Review mutation behavior is controlled by `review.mode` or `CODEX_REVIEW_MODE`.

- `dev`: approve/reject endpoints accept local form posts without a token.
- `prod`: review detail stays readable, but approve/reject require an authenticated operator session plus a valid CSRF token.

Production settings:

- `CODEX_REVIEW_MODE=prod`
- `CODEX_REVIEW_SESSION_SECRET=<long-random-secret>`
- `CODEX_REVIEW_OPERATOR_USERNAME=<operator-username>`
- `CODEX_REVIEW_OPERATOR_PASSWORD=<operator-password>`
- optional: `CODEX_REVIEW_SESSION_COOKIE_NAME=controltower_review_session`

Production behavior:

- anonymous viewers can open `/reviews/<run_id>` and inspect artifacts/history
- approve/reject controls are hidden until sign-in succeeds
- unauthenticated approve/reject attempts return HTTP 401
- authenticated requests without the bound CSRF token return HTTP 403
- production config gaps fail closed with HTTP 503 instead of allowing blind public mutation

Migration note:

- older environments that only set `CODEX_REVIEW_SHARED_TOKEN` must add the new session credentials before switching the browser review plane to production mode
- CLI review commands still work for local operators and now record `auth_mode=cli` in the audit trail

## Continuity / Obsidian Artifacts

Each approval or rejection writes a durable markdown record that includes:

- run id, title, workspace, summary
- final decision and final state
- risk level, decision mode, policy version, and readable decision reasons
- whether a human approval occurred
- whether the run was auto-approved
- whether the run was escalated
- actor identity and auth mode
- approved next prompt or rejection note
- attached artifact references
- timestamps, request/correlation ids, and request metadata when present
- git commit id when available
- generated trigger payload/result paths
- recent audit trail entries

Paths:

- runtime continuity artifact: `.controltower_runtime/orchestration/continuity/<run_id>.md`
- vault continuity artifact: `<vault_root>/10 Exports/Control Tower Review History/<run_id>.md`

## Failure Handling

- Approval is persisted before trigger emission.
- `triggered` is written only after a successful file write or 2xx webhook response.
- Trigger failures move the review run to `failed` and preserve the error in `run.json`, audit trail JSON, and the continuity markdown.
- Re-approving an already `triggered` run is a clear no-op and does not emit a duplicate trigger.
- Auto-approval uses the same `approve_review()` path as human approval, so exactly-once trigger semantics stay centralized.
