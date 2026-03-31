#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: release_remote.sh --app-root PATH --branch BRANCH --commit SHA --venv-python PATH --runtime-root PATH --env-file PATH --config PATH --service-name NAME --backend-base-url URL --public-base-url URL [--git-remote NAME] --source-trace-b64 BASE64
EOF
}

APP_ROOT=""
BRANCH=""
COMMIT=""
VENV_PYTHON=""
RUNTIME_ROOT=""
ENV_FILE=""
CONFIG_PATH=""
SERVICE_NAME=""
BACKEND_BASE_URL=""
PUBLIC_BASE_URL=""
GIT_REMOTE_NAME="origin"
SOURCE_TRACE_B64=""
SERVICE_ACTIVE_TIMEOUT_SECONDS=30
BACKEND_HEALTH_TIMEOUT_SECONDS=30

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app-root) APP_ROOT="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --venv-python) VENV_PYTHON="$2"; shift 2 ;;
    --runtime-root) RUNTIME_ROOT="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --config) CONFIG_PATH="$2"; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --backend-base-url) BACKEND_BASE_URL="$2"; shift 2 ;;
    --public-base-url) PUBLIC_BASE_URL="$2"; shift 2 ;;
    --git-remote) GIT_REMOTE_NAME="$2"; shift 2 ;;
    --source-trace-b64) SOURCE_TRACE_B64="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

for required in APP_ROOT BRANCH COMMIT VENV_PYTHON RUNTIME_ROOT ENV_FILE CONFIG_PATH SERVICE_NAME BACKEND_BASE_URL PUBLIC_BASE_URL SOURCE_TRACE_B64; do
  if [[ -z "${!required}" ]]; then
    echo "Missing required argument: ${required}" >&2
    usage >&2
    exit 64
  fi
done

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo -n)
fi

STEP=""
STEP_COMMAND=""
PREVIOUS_HEAD="unknown"

run_step() {
  local step="$1"
  local action="$2"
  shift 2
  STEP="$step"
  STEP_COMMAND="$(printf '%q ' "$@")"
  echo "==> ${STEP}"
  local output=""
  if ! output="$("$@" 2>&1)"; then
    if [[ -n "$output" ]]; then
      echo "$output" >&2
    fi
    fail "${output:-Command exited non-zero.}" "$action"
  fi
  if [[ -n "$output" ]]; then
    echo "$output"
  fi
}

current_checkout_head() {
  git -C "$APP_ROOT" rev-parse HEAD 2>/dev/null || true
}

public_live_state() {
  python3 - "$PUBLIC_BASE_URL" <<'PY'
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

url = sys.argv[1].rstrip("/") + "/healthz"
request = Request(url, headers={"User-Agent": "controltower-release-remote/1.0"})
try:
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        print(json.dumps({
            "reachable": True,
            "status_code": response.status,
            "status": payload.get("status"),
        }))
except HTTPError as exc:
    print(json.dumps({"reachable": False, "status_code": exc.code, "error": str(exc)}))
except (URLError, OSError, json.JSONDecodeError) as exc:
    print(json.dumps({"reachable": False, "error": str(exc)}))
PY
}

have_passwordless_sudo() {
  if [[ ${#SUDO[@]} -eq 0 ]]; then
    return 0
  fi
  "${SUDO[@]}" true >/dev/null 2>&1
}

service_main_pid() {
  systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null || echo 0
}

service_state() {
  systemctl is-active "$SERVICE_NAME" 2>/dev/null || true
}

restart_service() {
  if have_passwordless_sudo; then
    "${SUDO[@]}" systemctl restart "$SERVICE_NAME"
    return 0
  fi

  local pid
  pid="$(service_main_pid)"
  if [[ -z "$pid" || "$pid" == "0" ]]; then
    fail "Passwordless sudo is unavailable and $SERVICE_NAME is not currently running, so the service cannot be restarted safely." "Grant the deploy user passwordless sudo for systemctl or start the service manually as root."
  fi
  if ! kill "$pid"; then
    fail "Passwordless sudo is unavailable and the current $SERVICE_NAME PID $pid could not be terminated for a restart." "Grant the deploy user passwordless sudo for systemctl or restart the service manually as root."
  fi
  sleep 2
}

wait_for_service_active() {
  local deadline=$((SECONDS + SERVICE_ACTIVE_TIMEOUT_SECONDS))
  local current_state=""
  while (( SECONDS < deadline )); do
    current_state="$(service_state)"
    if [[ "$current_state" == "active" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "Service $SERVICE_NAME did not reach active state within ${SERVICE_ACTIVE_TIMEOUT_SECONDS}s (last state: ${current_state:-unknown})." >&2
  return 1
}

fail() {
  local reason="$1"
  local action="$2"
  local current_head
  current_head="$(current_checkout_head)"
  local service_state="unknown"
  if [[ ${#SUDO[@]} -eq 0 ]]; then
    service_state="$(systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
  else
    service_state="$("${SUDO[@]}" systemctl is-active "$SERVICE_NAME" 2>/dev/null || true)"
  fi
  echo "RELEASE STEP FAILED" >&2
  echo "Step: ${STEP:-unknown}" >&2
  echo "Command: ${STEP_COMMAND:-unknown}" >&2
  echo "Reason: $reason" >&2
  echo "Deployment checkout before attempt: ${PREVIOUS_HEAD:-unknown}" >&2
  echo "Deployment checkout now: ${current_head:-unknown}" >&2
  echo "Service state: ${service_state:-unknown}" >&2
  echo "Public live state: $(public_live_state)" >&2
  echo "Recommended action: $action" >&2
  echo "Recent service log tail:" >&2
  if have_passwordless_sudo; then
    "${SUDO[@]}" journalctl -u "$SERVICE_NAME" -n 80 --no-pager >&2 || true
  else
    systemctl status "$SERVICE_NAME" --no-pager >&2 || true
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager >&2 || true
  fi
  exit 1
}

verify_health_status() {
  local url="$1"
  python3 - "$url" <<'PY'
import json
import sys
from urllib.request import Request, urlopen

url = sys.argv[1]
request = Request(url, headers={"User-Agent": "controltower-release-remote/1.0"})
with urlopen(request, timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"Expected status 'ok' from {url}, got {payload.get('status')!r}.")
PY
}

wait_for_backend_health() {
  local url="$1"
  local deadline=$((SECONDS + BACKEND_HEALTH_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if verify_health_status "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Backend health endpoint did not report ok within ${BACKEND_HEALTH_TIMEOUT_SECONDS}s: $url" >&2
  return 1
}

write_deployment_manifest() {
  python3 - "$RUNTIME_ROOT" "$BRANCH" "$COMMIT" "$PREVIOUS_HEAD" "$SERVICE_NAME" "$BACKEND_BASE_URL" "$PUBLIC_BASE_URL" "$SOURCE_TRACE_B64" <<'PY'
import base64
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

runtime_root = Path(sys.argv[1])
branch = sys.argv[2]
commit = sys.argv[3]
previous_commit = sys.argv[4]
service_name = sys.argv[5]
backend_base_url = sys.argv[6]
public_base_url = sys.argv[7]
source_trace_b64 = sys.argv[8]
deployed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
release_root = runtime_root / "release"
history_root = release_root / "deployments"
release_root.mkdir(parents=True, exist_ok=True)
history_root.mkdir(parents=True, exist_ok=True)
source_trace = json.loads(base64.urlsafe_b64decode(source_trace_b64.encode("ascii")).decode("utf-8"))
payload = {
    "schema_version": "2026-03-30",
    "deployed_at": deployed_at,
    "hostname": socket.gethostname(),
    "branch": branch,
    "git_commit": commit,
    "previous_checkout_commit": previous_commit,
    "service_name": service_name,
    "backend_base_url": backend_base_url,
    "public_base_url": public_base_url,
    "local_head_commit": source_trace.get("local_head_commit"),
    "remote_origin_main_commit": source_trace.get("remote_origin_main_commit"),
    "source_push_status": source_trace.get("push_status"),
    "verification_status": "pass",
}
stamp = deployed_at.replace(":", "-")
history_path = history_root / f"deployment_{stamp}.json"
latest_path = release_root / "latest_live_deployment.json"
history_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
latest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(str(history_path))
print(str(latest_path))
PY
}

write_source_trace() {
  python3 - "$RUNTIME_ROOT" "$SOURCE_TRACE_B64" <<'PY'
import base64
import json
import sys
from pathlib import Path

runtime_root = Path(sys.argv[1])
payload = json.loads(base64.urlsafe_b64decode(sys.argv[2].encode("ascii")).decode("utf-8"))
path = runtime_root / "release" / "latest_release_source_trace.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(str(path))
PY
}

if [[ ! -d "$APP_ROOT/.git" ]]; then
  fail "Deployment app root is not a git checkout: $APP_ROOT" "Bootstrap the host with a real git clone at the documented app root before using the release command."
fi
if [[ ! -f "$APP_ROOT/pyproject.toml" ]]; then
  fail "Deployment app root is missing pyproject.toml: $APP_ROOT" "Verify the Control Tower app root path in the release spec."
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  fail "Configured virtualenv python is missing: $VENV_PYTHON" "Recreate the production virtualenv or correct the release spec."
fi

PREVIOUS_HEAD="$(current_checkout_head)"

DIRTY_TREE="$(git -C "$APP_ROOT" status --porcelain)"
if [[ -n "$DIRTY_TREE" ]]; then
  fail "Deployment checkout has uncommitted changes and cannot be reset safely." "Clean the remote checkout or archive the stray changes before retrying the release."
fi

run_step "git_fetch" "Verify the deployment checkout has the expected remote and network access." git -C "$APP_ROOT" fetch --prune "$GIT_REMOTE_NAME"
run_step "git_verify_commit" "Push the intended commit first so the VM can fetch it from the authoritative remote." git -C "$APP_ROOT" cat-file -e "${COMMIT}^{commit}"
run_step "git_checkout_target" "Inspect the deployment checkout and repair git permissions before retrying." git -C "$APP_ROOT" checkout -B "$BRANCH" "$COMMIT"
run_step "git_reset_exact_commit" "Inspect the deployment checkout and rerun once git can hard-reset to the requested commit." git -C "$APP_ROOT" reset --hard "$COMMIT"
run_step "git_normalize_filemode" "Disable filemode drift so executable-bit repair does not dirty the deployment checkout." git -C "$APP_ROOT" config core.filemode false
echo "==> write_release_source_trace"
write_source_trace

CHANGED_HOST_ASSETS="$(git -C "$APP_ROOT" diff --name-only "$PREVIOUS_HEAD" "$COMMIT" -- infra/deploy/controltower/templates infra/deploy/controltower/install_host.sh || true)"

run_step "restore_execute_bits" "Restore Linux execute bits on the deploy and ops scripts before retrying." find "$APP_ROOT/infra/deploy/controltower" "$APP_ROOT/ops/linux" -type f -name '*.sh' -exec chmod 0755 {} +
run_step "prune_python_caches" "Remove stale python caches manually if this cleanup step keeps failing." find "$APP_ROOT" -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
run_step "pip_install" "Inspect pip output and dependency resolution errors before retrying." "$VENV_PYTHON" -m pip install -e "$APP_ROOT[dev]"
run_step "remove_editable_metadata" "Remove generated editable-build metadata so the deployment checkout stays clean for the next release." rm -rf "$APP_ROOT/src/controltower.egg-info"

if [[ -n "$CHANGED_HOST_ASSETS" ]]; then
  if ! have_passwordless_sudo; then
    fail "Host asset changes require sudo, but passwordless sudo is unavailable for the deploy user." "Either rerun the release as root or grant passwordless sudo before deploying changes that affect nginx or systemd assets."
  fi
  run_step "install_host_assets" "Run sudo CONTROLTOWER_ENV_FILE=$ENV_FILE bash $APP_ROOT/infra/deploy/controltower/install_host.sh $ENV_FILE and confirm nginx/systemd install cleanly." "${SUDO[@]}" env CONTROLTOWER_ENV_FILE="$ENV_FILE" bash "$APP_ROOT/infra/deploy/controltower/install_host.sh" "$ENV_FILE"
else
  run_step "service_restart" "Inspect systemctl status and journal output for the service before retrying." restart_service
fi

run_step "systemd_active" "Inspect systemctl status and journal output for the service before retrying." wait_for_service_active
run_step "backend_health" "Inspect the service logs and backend listener if loopback health is still failing." wait_for_backend_health "$BACKEND_BASE_URL/healthz"
run_step "production_verify" "Use the verifier JSON above plus systemctl status to resolve the failing route, auth, or freshness check before retrying." env CONTROLTOWER_ENV_FILE="$ENV_FILE" bash "$APP_ROOT/ops/linux/verify_controltower_production.sh" --config "$CONFIG_PATH" --public-base-url "$PUBLIC_BASE_URL" --backend-base-url "$BACKEND_BASE_URL" --expected-commit "$COMMIT" --skip-smoke --skip-release-readiness

echo "==> write_release_manifest"
write_deployment_manifest
echo "Remote release accepted for commit $COMMIT"
