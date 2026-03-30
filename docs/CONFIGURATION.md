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
- `GIT_COMMIT`: optional build metadata override. If unset, Control Tower attempts `git rev-parse HEAD`; if git metadata is unavailable, diagnostics report `unavailable`.

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
