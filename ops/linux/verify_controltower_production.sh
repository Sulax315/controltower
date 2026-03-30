#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${CONTROLTOWER_ENV_FILE:-}" ]]; then
  if [[ ! -f "$CONTROLTOWER_ENV_FILE" ]]; then
    echo "Missing Control Tower env file: $CONTROLTOWER_ENV_FILE" >&2
    exit 65
  fi
  set -a
  # shellcheck disable=SC1090
  source "$CONTROLTOWER_ENV_FILE"
  set +a
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-${CONTROLTOWER_APP_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" "$REPO_ROOT/scripts/verify_production_deployment.py" "$@"
