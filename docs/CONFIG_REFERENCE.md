# Config Reference

Example file: [`controltower.example.yaml`](../controltower.example.yaml)

## Top-Level Keys

- `app.product_name`: UI and report label
- `app.environment`: descriptive environment label
- `sources.schedulelab.published_root`: published ScheduleLab root
- `sources.profitintel.database_path`: primary ProfitIntel DB
- `sources.profitintel.validation_search_roots`: fallback roots scanned for populated `validation.db` files
- `identity.registry_path`: optional YAML mapping for cross-system project identity resolution
- `obsidian.vault_root`: target vault or local test vault
- `obsidian.projects_folder`: project note root
- `obsidian.exports_folder`: weekly/export note root
- `obsidian.timestamped_weekly_notes`: when `true`, weekly notes also get date-stamped copies under exports
- `obsidian.rolling_portfolio_note_name`: stable portfolio note filename stem
- `obsidian.rolling_project_brief_name`: stable project weekly brief filename stem
- `obsidian.canonical_dossier_suffix`: canonical dossier suffix
- `runtime.state_root`: Control Tower runtime state, previews, and manifests
- `ui.host`: FastAPI bind host
- `ui.port`: FastAPI bind port
- `notifications.provider`: review notification sink, currently `runtime_log`
- `execution.provider`: downstream execution emission mode, `file`, `webhook`, `stub`, or `none`
- `execution.file_dir`: durable file-queue target for exactly-once execution payloads
- `execution.webhook_url`: downstream webhook endpoint for approved execution events
- `execution.webhook_timeout_ms`: bounded downstream webhook timeout
- `execution.dead_letter_dir`: durable failure sink for exhausted provider attempts
- `execution.max_attempts`: total bounded dispatch attempts including the first try
- `execution.retry_backoff_ms`: base retry backoff in milliseconds
- `execution.retry_backoff_multiplier`: exponential retry multiplier
- `execution.guarded_packs`: pack types treated as guarded execution intents
- `execution.allow_guarded_in_prod`: allow guarded packs to dispatch in prod when explicitly set
- `execution.result_ingest_enabled`: allow downstream result POST/CLI ingest
- `execution.event_version`: normalized event contract version, currently `v1`
- `review.mode`: browser review environment mode, `dev` or `prod`
- `review.session_secret`: signing key for operator review sessions in prod
- `review.operator_username`: interim operator username for prod review mutations
- `review.operator_password`: interim operator password for prod review mutations
- `autonomy.enabled`: master switch for selective autonomy
- `autonomy.auto_approve_low_risk`: allow deterministic low-risk auto-approval
- `autonomy.escalate_high_risk`: allow deterministic escalation for high/critical runs
- `autonomy.policy_version`: persisted policy version label
- `autonomy.notify_on_auto_approve`: emit quiet notifications for auto-approved runs instead of suppressing them
