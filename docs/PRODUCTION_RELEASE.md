# Control Tower Production Release

This is the single authoritative release lane for Control Tower.

## Exact Operator Command

Authoritative workstation command:

```bash
bash infra/deploy/controltower/deploy_update.sh
```

Compatibility wrappers still exist, but they are deprecated delegates, not alternate release implementations:

- `powershell -ExecutionPolicy Bypass -File .\ops\windows\Invoke-ControlTowerRelease.ps1`
- `python scripts/release_controltower.py`
- `bash ops/linux/release_controltower.sh`

The authoritative command reads the exact production target from [`infra/deploy/controltower/controltower.release.yaml`](/C:/Dev/ControlTower/infra/deploy/controltower/controltower.release.yaml).

## What The Release Command Enforces

1. Verifies the working tree is clean.
2. Verifies the current branch is `main`.
3. Verifies the authoritative git remote `origin` exists.
4. Verifies `git fetch origin main` succeeds.
5. Refuses releases when local is behind or diverged from `origin/main`.
6. Pushes local `HEAD` to `origin/main` when the checkout is safely ahead.
7. Stamps and ships the validated source-trace payload containing local `HEAD`, remote `origin/main`, and push status.
8. Copies the checked-in VM release script to `/tmp/release_remote.sh` over SCP, marks it executable, and runs it via `/bin/bash`.
9. On the VM, hard-resets the deployment checkout to the exact commit, reinstalls Python dependencies, refreshes host assets when they changed, and restarts `controltower-web`.
10. Runs the mandatory auth-aware production verifier against nginx/public HTTPS using the production env-backed app credentials.
11. Persists `latest_release_source_trace.json` and `latest_live_deployment.json` under the runtime release directory.
12. Confirms from outside the box that `https://controltower.bratek.io/healthz` is healthy, then proves the live build through authenticated diagnostics and the persisted live-deployment artifact.

## Before First Use

- Configure the local git remote named `origin`.
- Ensure the SSH identity used by the workstation can authenticate to `deploy@controltower.bratek.io`.
- Ensure the deploy user can run the needed service commands with passwordless sudo, or run the release as root on the VM.
- Ensure `/srv/controltower/app` is a real git checkout with `run_controltower.py` and `pyproject.toml` present. The release command intentionally refuses to treat a copied or half-deleted tree as authoritative.

## Freshness Proof

These are the authoritative freshness checks after a release:

- `curl https://controltower.bratek.io/healthz`
  Expected: JSON body `{"status":"ok"}`.
- `curl -I https://controltower.bratek.io/`
  Expected: `303` redirect to `/login`.
- `https://controltower.bratek.io/login`
  Expected: HTTP 200 login page with `Sign In`, `AUTH REQUIRED`, and versioned static asset URLs.
- Authenticated `GET /api/diagnostics`
  Expected: `product.build_metadata.git_commit` matches the intended commit and `release.live_deployment_present` is `true`.
- `/srv/controltower/shared/.controltower_runtime/release/latest_live_deployment.json`
  Expected: persisted record showing the accepted live commit and deployment timestamp.

## Notification Seam

Control Tower did not already have a real release-notification transport for production deploys.

The release command now supports an opt-in webhook seam:

```powershell
$env:CONTROLTOWER_RELEASE_NOTIFY_WEBHOOK_URL = "https://example/webhook"
python .\scripts\deploy_update_controltower.py --notify-webhook-url $env:CONTROLTOWER_RELEASE_NOTIFY_WEBHOOK_URL
```

When unset, the release summary records `notification.status = not_configured`.

## Manual VM Fallback

Use this only when workstation SSH release execution is unavailable but the pushed commit already exists on `origin/main`.

```bash
test -d /srv/controltower/app/.git
test -f /srv/controltower/app/run_controltower.py
test -f /srv/controltower/app/pyproject.toml
cd /srv/controltower/app
git fetch --prune origin
git checkout -B main <COMMIT>
git reset --hard <COMMIT>
find /srv/controltower/app/infra/deploy/controltower /srv/controltower/app/ops/linux -type f -name '*.sh' -exec chmod 0755 {} +
find /srv/controltower/app -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
/srv/controltower/venv/bin/python -m pip install -e '/srv/controltower/app[dev]'
sudo systemctl restart controltower-web
curl -fsS http://127.0.0.1:8787/healthz
sudo env CONTROLTOWER_ENV_FILE=/etc/controltower/controltower.env bash /srv/controltower/app/ops/linux/verify_controltower_production.sh --config /etc/controltower/controltower.yaml --public-base-url https://controltower.bratek.io --backend-base-url http://127.0.0.1:8787 --expected-commit <COMMIT> --skip-smoke --skip-release-readiness
cat /srv/controltower/shared/.controltower_runtime/release/latest_live_deployment.json
```

## Entry Point Ownership

- `infra/deploy/controltower/deploy_update.sh` is the single operator-facing release handoff.
- `ops/linux/verify_controltower_production.sh` and `scripts/verify_production_deployment.py` remain the mandatory post-deploy gate.
- `scripts/release_controltower.py`, `ops/linux/release_controltower.sh`, and `ops/windows/Invoke-ControlTowerRelease.ps1` are deprecated compatibility wrappers only.
- `infra/deploy/controltower/release_remote.sh` is an internal transport substrate for the authoritative handoff, not a separate operator command.
