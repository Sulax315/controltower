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

