#!/usr/bin/env bash
set -euo pipefail

resolve_config_arg() {
  local expect_value=0
  local arg
  for arg in "$@"; do
    if [[ "$expect_value" -eq 1 ]]; then
      printf '%s\n' "$arg"
      return 0
    fi
    case "$arg" in
      --config)
        expect_value=1
        ;;
      --config=*)
        printf '%s\n' "${arg#--config=}"
        return 0
        ;;
    esac
  done
  return 1
}

load_env_file() {
  local env_file="$1"
  if [[ -z "$env_file" ]]; then
    return 0
  fi
  if [[ ! -f "$env_file" ]]; then
    echo "Missing Control Tower env file: $env_file" >&2
    exit 65
  fi
  set -a
  # shellcheck disable=SC1090
  source "$env_file"
  set +a
}

resolve_runtime_root() {
  local repo_root="$1"
  local python_bin="$2"
  local config_path="$3"
  local runtime_root="${CONTROLTOWER_RUNTIME_ROOT:-}"
  local resolved

  if [[ -n "$runtime_root" ]]; then
    printf '%s\n' "$runtime_root"
    return 0
  fi

  if [[ -n "$config_path" ]]; then
    set +e
    resolved="$("$python_bin" - "$repo_root" "$config_path" <<'PY'
import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
config_path = Path(sys.argv[2])
src_root = repo_root / "src"
if str(src_root) not in sys.path:
    sys.path.insert(0, str(src_root))

from controltower.config import load_config

print(load_config(config_path).runtime.state_root)
PY
)"
    if [[ $? -eq 0 && -n "$resolved" ]]; then
      set -e
      printf '%s\n' "$resolved"
      return 0
    fi
    set -e
  fi

  printf '%s\n' "$repo_root/.controltower_runtime"
}

if [[ $# -lt 2 ]]; then
  echo "usage: controltower_operation.sh <operation-name> <script-name> [script args...]" >&2
  exit 64
fi

load_env_file "${CONTROLTOWER_ENV_FILE:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-${CONTROLTOWER_APP_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}}"
OPERATION_NAME="$1"
SCRIPT_NAME="$2"
shift 2

PYTHON_BIN="${PYTHON_BIN:-python3}"
CONFIG_PATH="${CONTROLTOWER_CONFIG:-}"
if [[ -z "$CONFIG_PATH" ]]; then
  CONFIG_PATH="$(resolve_config_arg "$@" || true)"
fi
if [[ -n "$CONFIG_PATH" ]]; then
  export CONTROLTOWER_CONFIG="$CONFIG_PATH"
fi

RUNTIME_ROOT="$(resolve_runtime_root "$REPO_ROOT" "$PYTHON_BIN" "$CONFIG_PATH")"
LOG_ROOT="$RUNTIME_ROOT/logs"
mkdir -p "$LOG_ROOT"

STAMP="$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
STDOUT_LOG="$LOG_ROOT/${OPERATION_NAME}_${STAMP}.stdout.log"
STDERR_LOG="$LOG_ROOT/${OPERATION_NAME}_${STAMP}.stderr.log"
export CONTROLTOWER_STDOUT_LOG="$STDOUT_LOG"
export CONTROLTOWER_STDERR_LOG="$STDERR_LOG"

cd "$REPO_ROOT"
set +e
"$PYTHON_BIN" "$REPO_ROOT/scripts/$SCRIPT_NAME" "$@" >"$STDOUT_LOG" 2>"$STDERR_LOG"
STATUS=$?
set -e

echo "Operation: $OPERATION_NAME"
echo "ExitCode: $STATUS"
echo "StdoutLog: $STDOUT_LOG"
echo "StderrLog: $STDERR_LOG"
echo "RuntimeRoot: $RUNTIME_ROOT"

exit $STATUS
