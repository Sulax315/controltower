# Control Tower Configuration

Control Tower loads configuration from a YAML file passed with `--config`, or from the default in-repo paths if no override is supplied.

## Primary Files

- Main config template: [`controltower.example.yaml`](/C:/Dev/ControlTower/controltower.example.yaml)
- Example environment variables: [`controltower.env.example`](/C:/Dev/ControlTower/controltower.env.example)
- Default identity registry: [`config/project_registry.yaml`](/C:/Dev/ControlTower/config/project_registry.yaml)
- Registry example: [`config/project_registry.example.yaml`](/C:/Dev/ControlTower/config/project_registry.example.yaml)

## Required Runtime Expectations

- `sources.schedulelab.published_root` must point at a real ScheduleLab `published/` tree with `portfolio_outputs/portfolio_feed.json` and per-project `runs/<project>/outputs/*.json`.
- `sources.profitintel.database_path` must point at the authoritative ProfitIntel SQLite database used by the live operation lane.
- `identity.registry_path` must exist and be valid YAML. Startup fails fast if the registry is missing or contains ambiguous aliases.
- `obsidian.vault_root` must be writable. Daily and weekly runs write live notes here.
- `runtime.state_root` must be writable. Control Tower stores run manifests, diagnostics snapshots, release artifacts, logs, operation summaries, and the artifact index here.
- `app.public_base_url` should be set to the real public hostname, for example `https://controltower.bratek.io`, so emitted review URLs and operator links resolve correctly outside the loopback listener.
- `execution.provider` controls how approved review runs emit the downstream execution event: `file`, `webhook`, `stub`, or `none`.
- `execution.file_dir` is the durable file-queue target for n8n or watcher-based consumers.
- `execution.dead_letter_dir` stores failed downstream payloads for replay and operator inspection.
- `execution.max_attempts`, `execution.retry_backoff_ms`, and `execution.retry_backoff_multiplier` control bounded dispatch retry posture.
- `execution.guarded_packs` and `execution.allow_guarded_in_prod` control guarded execution policy in production.
- `execution.result_ingest_enabled` controls whether downstream closeout can be POSTed back into Control Tower.
- `execution.event_version` pins the normalized event contract version carried in emitted payloads.
- `review.mode` controls whether approval/rejection endpoints run in local dev mode or production session-authenticated mode.
- `auth.mode` controls whether the main UI/API surface stays open for local development or requires username/password application auth in production.
- `autonomy.*` controls deterministic selective-autonomy classification, low-risk auto-approval, high-risk escalation, policy versioning, and auto-approval notification behavior.
- Application auth uses a signed session backed by `auth.session_secret`, `auth.username`, and `auth.password`.
- Production mutation auth uses a signed review session backed by `review.session_secret`, `review.operator_username`, and `review.operator_password`.
- Markdown templates under `src/controltower/render/templates/` and UI templates under `src/controltower/api/templates/` must exist. Startup and preflight fail immediately if they do not.

## Runtime Retention

`runtime.retention` controls how much timestamped history Control Tower keeps:

- `run_history_limit`: run manifests and matching `runs/<run_id>/` folders
- `release_history_limit`: timestamped `release/release_readiness_*.json|md`
- `operations_history_limit`: machine-readable summaries under `operations/history/`
- `diagnostics_history_limit`: timestamped diagnostics snapshots under `diagnostics/`
- `log_file_limit`: stdout/stderr files under `logs/`

Latest pointer files are never deleted, and pruning also preserves the most recent successful export, the latest successful release artifact, and the latest successful summary per operation type.

## Environment Variables

- `CONTROLTOWER_CONFIG`: optional alternate path to the YAML config for UI launches or wrappers that rely on environment-based discovery.
- `CONTROLTOWER_PUBLIC_BASE_URL`: optional override for `app.public_base_url`.
- `GIT_COMMIT`: optional build metadata fallback. Control Tower prefers `git rev-parse HEAD` when the workspace is a real git checkout and only falls back to `GIT_COMMIT` when git metadata is unavailable.
- `CODEX_AUTH_MODE`: optional override for `auth.mode`.
- `CODEX_AUTH_SESSION_SECRET`: required in production to sign the public app session.
- `CODEX_AUTH_USERNAME`: required in production for the public login screen.
- `CODEX_AUTH_PASSWORD`: required in production for the public login screen.
- `CODEX_AUTH_SESSION_COOKIE_NAME`: optional override for the app session cookie name.
- `CODEX_EXECUTION_PROVIDER`: optional override for `execution.provider`.
- `CODEX_EXECUTION_FILE_DIR`: optional override for `execution.file_dir`.
- `CODEX_EXECUTION_WEBHOOK_URL`: optional override for `execution.webhook_url`.
- `CODEX_EXECUTION_WEBHOOK_TIMEOUT_MS`: optional override for the webhook timeout in milliseconds.
- `CODEX_EXECUTION_DEAD_LETTER_DIR`: optional override for `execution.dead_letter_dir`.
- `CODEX_EXECUTION_MAX_ATTEMPTS`: optional override for bounded downstream dispatch attempts.
- `CODEX_EXECUTION_RETRY_BACKOFF_MS`: optional override for base retry backoff in milliseconds.
- `CODEX_EXECUTION_RETRY_BACKOFF_MULTIPLIER`: optional override for exponential retry multiplier.
- `CODEX_EXECUTION_GUARDED_PACKS`: comma-separated guarded pack list.
- `CODEX_EXECUTION_ALLOW_GUARDED_IN_PROD`: allow guarded packs to dispatch in prod when explicitly set to `true`.
- `CODEX_RESULT_INGEST_ENABLED`: optional override for `execution.result_ingest_enabled`.
- `CODEX_EVENT_VERSION`: optional override for `execution.event_version`.
- Legacy `CODEX_TRIGGER_*` variables are still accepted as compatibility aliases for the new execution settings.
- `CODEX_REVIEW_MODE`: optional override for `review.mode`.
- `CODEX_REVIEW_SHARED_TOKEN`: legacy override retained for compatibility with pre-hardening configs. Production HTTP mutations no longer rely on the shared token gate.
- `CODEX_REVIEW_SESSION_SECRET`: required in production to sign operator review sessions.
- `CODEX_REVIEW_OPERATOR_USERNAME`: required in production for the interim operator login.
- `CODEX_REVIEW_OPERATOR_PASSWORD`: required in production for the interim operator login.
- `CODEX_REVIEW_SESSION_COOKIE_NAME`: optional override for the review session cookie name.
- `CODEX_AUTONOMY_ENABLED`: global on/off switch for selective autonomy. When `false`, runs are still classified but remain in manual review.
- `CODEX_AUTO_APPROVE_LOW_RISK`: when `true`, low-risk runs may auto-approve through the normal approval/trigger path.
- `CODEX_ESCALATE_HIGH_RISK`: when `true`, high/critical runs are marked escalated and receive high-signal notification handling.
- `CODEX_POLICY_VERSION`: policy label persisted on each review run and continuity artifact.
- `CODEX_NOTIFY_ON_AUTO_APPROVE`: when `true`, auto-approved runs still emit a quiet operator notification instead of suppressing it.

## Review Orchestration Outputs

Approved or rejected review runs write additional orchestration artifacts under `runtime.state_root`:

- `orchestration/reviews/<run_id>/run.json`: persisted review state, reviewer metadata, trigger record, audit trail, and continuity pointers
- `orchestration/reviews/<run_id>/audit/*.json`: append-only audit events
- `orchestration/reviews/<run_id>/decision_artifacts/approved_payload_latest.json`: durable approved payload artifact
- `orchestration/reviews/<run_id>/decision_artifacts/execution_event_latest.json`: normalized execution event contract
- `orchestration/reviews/<run_id>/trigger_results/*.json`: provider response or file emission result
- `orchestration/reviews/<run_id>/execution_results/*.json`: downstream result payloads linked back to the originating run
- `orchestration/reviews/<run_id>/closeout/closeout_latest.json`: current downstream execution closeout snapshot
- `orchestration/reviews/<run_id>/closeout/closeout_latest.md`: operator-readable closeout summary
- `orchestration/continuity/<run_id>.md`: runtime continuity / Obsidian-ready markdown artifact
- `orchestration/dead_letter/*.json`: provider failures ready for replay or operator triage

When `obsidian.vault_root` is configured, Control Tower also mirrors the continuity markdown to:

- `<vault_root>/<exports_folder>/Control Tower Review History/<run_id>.md`

Reviewer metadata now persists:

- actor identity
- auth mode
- reviewed timestamp
- request and correlation ids when supplied
- source IP / forwarded-for / user-agent request context when available

Selective-autonomy metadata now persists per review run:

- `risk_level`: `low | medium | high | critical`
- `decision_mode`: `auto_approve | manual_review | escalate`
- `decision_reasons`: deterministic rule reasons captured as readable strings
- `policy_version`
- `policy_evaluated_at`
- `auto_approved_at`
- `escalated_at`

Execution metadata now persists per review run:

- normalized execution event contract fields including `event_type`, `event_version`, `event_id`, and `trigger_id`
- deterministic execution pack selection (`pack_id`, `pack_type`, reason, matched keywords, target, retry posture)
- emission attempts, delivery status, last provider error, dead-letter path, and exactly-once queue/webhook metadata
- guard posture, validation failures, and closeout artifact paths
- downstream result summary, timestamps, external reference, logs excerpt, and output artifacts

## Startup Validation Behavior

The following conditions are validated before live operations are allowed to proceed:

- Config file exists and parses as a YAML mapping.
- Identity registry exists and validates.
- Markdown/UI templates are present.
- ScheduleLab and ProfitIntel sources resolve cleanly.
- Runtime folders are writable.

Use this command for a full operator handoff check:

```powershell
python .\scripts\preflight_controltower.py --config .\controltower.yaml
```
