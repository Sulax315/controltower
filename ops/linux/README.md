# Linux Operations Pack

These wrappers execute the same production Python entrypoints as Windows. When `CONTROLTOWER_RUNTIME_ROOT` or `CONTROLTOWER_CONFIG` is set, logs land in the configured runtime root instead of the repo-local default.

## Recommended Production Model

- systemd for the always-on web process
- cron for the scheduled `daily` and `weekly` operations
- one persistent runtime root such as `/srv/controltower/shared/.controltower_runtime`

Use the full droplet pack in [`infra/deploy/controltower/README.md`](/C:/Dev/ControlTower/infra/deploy/controltower/README.md) for the nginx site, systemd unit, cron install, and deploy/update scripts.

For releases, use `bash infra/deploy/controltower/deploy_update.sh`. The verifier still expects the source-control trace written by that handoff, so `verify_controltower_production.sh` on its own is a diagnostics tool, not a complete release handoff.

## Manual Invocation

```bash
export CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env
chmod +x ops/linux/*.sh infra/deploy/controltower/*.sh

./ops/linux/preflight_controltower.sh --config /etc/controltower/controltower.yaml
./ops/linux/run_daily_controltower.sh --config /etc/controltower/controltower.yaml
./ops/linux/run_weekly_controltower.sh --config /etc/controltower/controltower.yaml
./ops/linux/smoke_controltower.sh --config /etc/controltower/controltower.yaml
./ops/linux/diagnostics_snapshot_controltower.sh --config /etc/controltower/controltower.yaml
./ops/linux/release_readiness_controltower.sh --config /etc/controltower/controltower.yaml --skip-pytest --skip-acceptance
./ops/linux/verify_controltower_production.sh --config /etc/controltower/controltower.yaml
```

## Runtime Evidence

Wrapper logs land under `<runtime_root>/logs/`, for example:

- `/srv/controltower/shared/.controltower_runtime/logs/daily_<timestamp>.stdout.log`
- `/srv/controltower/shared/.controltower_runtime/logs/daily_<timestamp>.stderr.log`
- `/srv/controltower/shared/.controltower_runtime/logs/weekly_<timestamp>.stdout.log`
- `/srv/controltower/shared/.controltower_runtime/logs/weekly_<timestamp>.stderr.log`

Each operation also writes a summary JSON into `<runtime_root>/operations/history/`.
