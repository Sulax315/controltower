# Control Tower Operations Runbook

This runbook covers the validated live-operations lane and the finished Linux production deployment. The recommended droplet layout is:

- app root: `/srv/controltower/app`
- virtualenv: `/srv/controltower/venv`
- production env file: `/etc/controltower/controltower.env`
- production config: `/etc/controltower/controltower.yaml`
- runtime evidence root: `/srv/controltower/shared/.controltower_runtime`
- public domain: `https://controltower.bratek.io`

Control Tower stays a single FastAPI process behind host nginx. The same Python process serves `/`, `/diagnostics`, and `/api/diagnostics`.

## Production Topology

- Web process: `controltower-web.service` running `python /srv/controltower/app/run_controltower.py --config /etc/controltower/controltower.yaml serve --host 127.0.0.1 --port 8787`
- Reverse proxy: nginx terminates TLS for `controltower.bratek.io` and proxies to `127.0.0.1:8787`
- Scheduler: cron runs the canonical `daily` and `weekly` jobs through the Linux wrappers
- Runtime persistence: the YAML config sets `runtime.state_root` to `/srv/controltower/shared/.controltower_runtime`, so restarts and code deploys do not discard logs, latest pointers, release evidence, or history

## Production Install And Update

Create the production env and config files:

```bash
sudo install -d /etc/controltower
sudo cp /srv/controltower/app/infra/deploy/controltower/controltower.production.env.example /etc/controltower/controltower.env
sudo cp /srv/controltower/app/infra/deploy/controltower/controltower.production.yaml.example /etc/controltower/controltower.yaml
sudo editor /etc/controltower/controltower.env
sudo editor /etc/controltower/controltower.yaml
```

The env file carries the TLS certificate/include paths used by the nginx template, so keep those aligned with the droplet's existing nginx certificate pattern.
On the current `bratek.io` host, the authoritative mounted source paths are `/app/schedulelab_data/published` for ScheduleLab and `/app/data/runtime/profitintel.db` for ProfitIntel.

Deploy or update the app code and virtualenv:

```bash
cd /srv/controltower/app
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash ./infra/deploy/controltower/deploy_update.sh /path/to/ControlTower
```

Install or refresh the web service, nginx site, and cron schedule:

```bash
sudo CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/infra/deploy/controltower/install_host.sh
```

## Exact Production Commands

Start or restart the web process:

```bash
sudo systemctl restart controltower-web
sudo systemctl status controltower-web --no-pager
```

Run preflight:

```bash
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/preflight_controltower.sh --config /etc/controltower/controltower.yaml
```

Run smoke:

```bash
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/smoke_controltower.sh --config /etc/controltower/controltower.yaml
```

Verify diagnostics through nginx:

```bash
curl -fsS https://controltower.bratek.io/diagnostics > /tmp/controltower-diagnostics.html
curl -fsS https://controltower.bratek.io/api/diagnostics | python3 -m json.tool
```

## Local Access Triage

If a Windows workstation says `https://controltower.bratek.io` is down or shows the parked-domain certificate, do not restart the VM first. Prove whether the browser is resolving the wrong IP before treating this as a production outage.

Operator checks:

- Run `powershell -ExecutionPolicy Bypass -File .\ops\windows\Test-ControlTowerDns.ps1`.
- Treat `208.91.112.55` or `2620:101:9000:53::55` as a local-DNS failure, not a Control Tower VM failure.
- Prove the production edge directly with `curl.exe -sS -D - -o NUL --resolve controltower.bratek.io:443:161.35.177.158 https://controltower.bratek.io/`.
- If public resolvers return `161.35.177.158` but the workstation does not, switch the active interface DNS temporarily or use a proof-only hosts override.

Detailed DNS/TLS commands and remediation steps live in [`infra/deploy/controltower/DNS_TLS_RUNBOOK.md`](/C:/Dev/ControlTower/infra/deploy/controltower/DNS_TLS_RUNBOOK.md).

Verify release readiness using persisted evidence:

```bash
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/release_readiness_controltower.sh --config /etc/controltower/controltower.yaml --skip-pytest --skip-acceptance
```

Install or refresh the scheduler:

```bash
sudo CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/infra/deploy/controltower/install_host.sh
sudo cat /etc/cron.d/controltower
```

Run the one-command production verification flow:

```bash
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/verify_controltower_production.sh --config /etc/controltower/controltower.yaml
```

## Daily vs Weekly

Daily run:

- Command: `python .\scripts\run_daily_controltower.py --config .\controltower.yaml`
- Uses the real ScheduleLab and ProfitIntel sources.
- Writes live Obsidian outputs to the configured vault.
- Updates `.controltower_runtime/latest_run.json`
- Writes a timestamped operation summary under `.controltower_runtime/operations/history/`
- Captures a diagnostics snapshot under `.controltower_runtime/diagnostics/`
- Refreshes `.controltower_runtime/artifact_index.json`
- Applies safe retention pruning

Weekly run:

- Command: `python .\scripts\run_weekly_controltower.py --config .\controltower.yaml`
- Runs the same live export path as daily
- Executes live route/export smoke verification
- Rebuilds release-readiness artifacts, including pytest and acceptance
- Updates `.controltower_runtime/release/latest_release_readiness.json`
- Produces the operator/executive release markdown in `.controltower_runtime/release/latest_release_readiness.md`

Preflight:

- Command: `python .\scripts\preflight_controltower.py --config .\controltower.yaml`
- Checks config load, markdown templates, UI assets, registry, source validation, diagnostics capture, artifact index refresh, and retention dry-run/safe pruning

Smoke verification:

- Command: `python .\scripts\smoke_controltower.py --config .\controltower.yaml`
- Verifies `/`, `/projects`, `/runs`, `/exports/latest`, `/diagnostics`, `/api/diagnostics`, and the latest run detail/compare routes
- Verifies the latest export manifest points at real preview/output/versioned files

Diagnostics snapshot:

- Command: `python .\scripts\diagnostics_snapshot_controltower.py --config .\controltower.yaml`
- Captures a point-in-time operator snapshot without writing new notes

Release readiness:

- Command: `python .\scripts\release_readiness_controltower.py --config .\controltower.yaml`
- Rebuilds the formal release gate artifacts and updates the latest pointers

Linux production equivalents:

- `bash /srv/controltower/app/ops/linux/run_daily_controltower.sh --config /etc/controltower/controltower.yaml`
- `bash /srv/controltower/app/ops/linux/run_weekly_controltower.sh --config /etc/controltower/controltower.yaml`
- `bash /srv/controltower/app/ops/linux/preflight_controltower.sh --config /etc/controltower/controltower.yaml`
- `bash /srv/controltower/app/ops/linux/smoke_controltower.sh --config /etc/controltower/controltower.yaml`
- `bash /srv/controltower/app/ops/linux/diagnostics_snapshot_controltower.sh --config /etc/controltower/controltower.yaml`
- `bash /srv/controltower/app/ops/linux/release_readiness_controltower.sh --config /etc/controltower/controltower.yaml --skip-pytest --skip-acceptance`

## Expected Outputs

Under `.controltower_runtime/`:

- `latest_run.json`: stable pointer to the newest export run
- `history/<run_id>.json`: export history record
- `runs/<run_id>/manifest.json`: per-run export manifest
- `release/latest_release_readiness.json`: newest release gate JSON
- `release/latest_release_readiness.md`: newest operator/executive release summary
- `release/release_readiness_<timestamp>.json|md`: timestamped release history
- `diagnostics/latest_diagnostics.json`: newest diagnostics snapshot
- `diagnostics/diagnostics_<timestamp>.json`: timestamped diagnostics history
- `operations/history/<operation_id>.json`: daily/weekly/preflight/smoke/release summary JSON
- `operations/latest_<operation>.json`: latest pointer per operation type
- `artifact_index.json`: stable index for newest and recent artifacts
- `logs/<operation>_<timestamp>.stdout.log`
- `logs/<operation>_<timestamp>.stderr.log`

In the configured vault:

- Rolling portfolio note in `10 Exports/Portfolio Weekly Summary.md`
- Rolling project weekly briefs in `02 Projects/<Project>/Weekly Brief.md`
- Rolling project dossiers in `02 Projects/<Project>/<Project> - Dossier.md`
- Timestamped weekly copies if `obsidian.timestamped_weekly_notes` is enabled

## How To Read Release Readiness

The markdown summary in `.controltower_runtime/release/latest_release_readiness.md` shows:

- overall verdict
- gate results for pytest, acceptance, route checks, export checks, and source validation
- failing checks, if any
- latest evidence references
- operator recommendation

Interpretation:

- `READY`: all gates passed
- `NOT_READY`: at least one gate failed; use the failing checks and remaining risks sections first

## How To Read Diagnostics

Use `/diagnostics` for the human view and `/api/diagnostics` for tooling.

Key fields:

- `config.status`: whether the loaded config is valid
- `templates.markdown.status` and `templates.ui.status`: required template availability
- `registry.status`: identity registry load state
- `acceptance.last_status`: last persisted acceptance result
- `release.status`: latest release gate verdict
- `latest_run.status`: latest export status
- `operations.latest_run_status`: last scheduled/manual operation outcome
- `artifacts.presence_checks.*`: required pointer/index presence
- `artifacts.recent_history_file_count`: number of retained export history records

Good production diagnostics look like:

- `/` returns HTTP 200 through nginx
- `/diagnostics` returns HTTP 200 through nginx
- `/api/diagnostics` returns HTTP 200 and `config.status = loaded`
- `release.status` is `ready`
- `latest_run.status` is `success`
- `operations.latest_run_status` is `success`
- `artifacts.artifact_index_present` is `true`
- `artifacts.latest_diagnostics_present` is `true`

## First Checks When A Run Fails

1. Open the newest operation summary in `.controltower_runtime/operations/history/`.
2. Check the paired stdout/stderr logs in `.controltower_runtime/logs/`.
3. If the failure is export-related, inspect `.controltower_runtime/latest_run.json` and the referenced `runs/<run_id>/manifest.json`.
4. If the failure is a weekly/release failure, open `.controltower_runtime/release/latest_release_readiness.md`.
5. Open `/diagnostics` or inspect `.controltower_runtime/diagnostics/latest_diagnostics.json`.
6. For web-process issues, check `sudo journalctl -u controltower-web -n 100 --no-pager`.

## Recovery Steps

Config failures:

- Symptom: preflight/daily/weekly exits with config error.
- Manual recovery: `python .\scripts\preflight_controltower.py --config .\controltower.yaml`
- Check: YAML parse errors, wrong path, missing registry path, invalid retention values.

Template failures:

- Symptom: startup or preflight reports missing markdown/UI templates.
- Manual recovery: restore missing files under `src/controltower/render/templates/` or `src/controltower/api/templates/`, then rerun `preflight_controltower.py`.

YAML failures:

- Symptom: config or registry malformed YAML.
- Manual recovery:

```powershell
python .\scripts\preflight_controltower.py --config .\controltower.yaml
python .\run_controltower.py validate-sources --config .\controltower.yaml
```

Route failures:

- Symptom: smoke or weekly summary shows `route_checks.status = fail`.
- Manual recovery:

```powershell
python .\scripts\smoke_controltower.py --config .\controltower.yaml --refresh-export
python .\run_controltower.py --config .\controltower.yaml serve
```

Export failures:

- Symptom: smoke or weekly summary shows `export_checks.status = fail`.
- Manual recovery:

```powershell
python .\scripts\run_daily_controltower.py --config .\controltower.yaml
python .\scripts\smoke_controltower.py --config .\controltower.yaml
```

Registry failures:

- Symptom: ambiguous alias or missing registry path.
- Manual recovery: repair [`config/project_registry.yaml`](/C:/Dev/ControlTower/config/project_registry.yaml), then rerun `preflight_controltower.py`.

## Artifact Retention

- Retention is controlled by `runtime.retention` in the YAML config.
- Use `--retention-dry-run` on preflight/daily/weekly to see what would be pruned without deleting anything.
- Latest pointer files are never deleted.
- The most recent successful export artifacts are retained even if older than the count limit.

## Exact Manual Recovery Commands

```powershell
python .\scripts\preflight_controltower.py --config .\controltower.yaml
python .\scripts\run_daily_controltower.py --config .\controltower.yaml
python .\scripts\run_weekly_controltower.py --config .\controltower.yaml
python .\scripts\smoke_controltower.py --config .\controltower.yaml --refresh-export
python .\scripts\diagnostics_snapshot_controltower.py --config .\controltower.yaml
python .\scripts\release_readiness_controltower.py --config .\controltower.yaml
python .\run_controltower.py --config .\controltower.yaml serve
```

Linux production:

```bash
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/preflight_controltower.sh --config /etc/controltower/controltower.yaml
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/run_daily_controltower.sh --config /etc/controltower/controltower.yaml
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/run_weekly_controltower.sh --config /etc/controltower/controltower.yaml
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/smoke_controltower.sh --config /etc/controltower/controltower.yaml
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/diagnostics_snapshot_controltower.sh --config /etc/controltower/controltower.yaml
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/release_readiness_controltower.sh --config /etc/controltower/controltower.yaml --skip-pytest --skip-acceptance
CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/verify_controltower_production.sh --config /etc/controltower/controltower.yaml
sudo systemctl restart controltower-web
sudo journalctl -u controltower-web -n 100 --no-pager
```
