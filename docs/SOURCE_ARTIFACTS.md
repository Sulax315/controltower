# Source Artifact Expectations

## ScheduleLab

Control Tower reads directly from published ScheduleLab outputs.

Primary artifacts:

- `portfolio_outputs/portfolio_feed.json`
- `runs/<project_code>/outputs/dashboard_feed.json`
- `runs/<project_code>/outputs/summary.json`
- `runs/<project_code>/outputs/run_manifest.json`
- `runs/<project_code>/outputs/management_actions.json`
- `runs/<project_code>/outputs/management_brief.md`

## ProfitIntel

Control Tower reads authoritative snapshot and trust signals from:

- `report_snapshots`
- `project_financial_snapshots`
- `snapshot_trust`

Primary database selection order:

1. configured `database_path` if populated
2. latest populated `validation.db` under configured validation roots

## Merge Contract

The normalized project contract includes:

- `canonical_project_code`
- `project_name`
- `snapshot_timestamp`
- schedule summary block
- financial summary block
- health tier and score
- top issues and recommended actions
- provenance references
- trust and missing-data flags

