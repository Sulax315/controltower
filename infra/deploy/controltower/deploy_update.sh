#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${CONTROLTOWER_ENV_FILE:-/etc/controltower/controltower.env}"
SOURCE_ROOT="${1:-$(pwd)}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing Control Tower env file: $ENV_FILE" >&2
  exit 65
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${CONTROLTOWER_APP_ROOT:?CONTROLTOWER_APP_ROOT must be set in the env file.}"
: "${CONTROLTOWER_VENV_ROOT:?CONTROLTOWER_VENV_ROOT must be set in the env file.}"
: "${CONTROLTOWER_RUNTIME_ROOT:?CONTROLTOWER_RUNTIME_ROOT must be set in the env file.}"

BOOTSTRAP_PYTHON="${CONTROLTOWER_BOOTSTRAP_PYTHON:-python3}"
TARGET_PYTHON="$CONTROLTOWER_VENV_ROOT/bin/python"

if [[ ! -f "$SOURCE_ROOT/pyproject.toml" ]]; then
  echo "Source root does not look like the Control Tower repo: $SOURCE_ROOT" >&2
  exit 66
fi

install -d "$CONTROLTOWER_APP_ROOT" "$CONTROLTOWER_VENV_ROOT" "$CONTROLTOWER_RUNTIME_ROOT" "$CONTROLTOWER_RUNTIME_ROOT/logs"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.controltower_runtime/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '.venv/' \
  "$SOURCE_ROOT/" "$CONTROLTOWER_APP_ROOT/"

# Windows-origin deploy archives may lose execute bits, so restore the Linux
# wrapper scripts before systemd, cron, or operator checks invoke them.
find \
  "$CONTROLTOWER_APP_ROOT/infra/deploy/controltower" \
  "$CONTROLTOWER_APP_ROOT/ops/linux" \
  -type f -name '*.sh' -exec chmod 0755 {} +

if [[ ! -x "$TARGET_PYTHON" ]]; then
  "$BOOTSTRAP_PYTHON" -m venv "$CONTROLTOWER_VENV_ROOT"
fi

"$TARGET_PYTHON" -m pip install --upgrade pip
"$TARGET_PYTHON" -m pip install -e "$CONTROLTOWER_APP_ROOT[dev]"

echo "Control Tower deployed to $CONTROLTOWER_APP_ROOT"
echo "Virtualenv python: $TARGET_PYTHON"
echo "Runtime root: $CONTROLTOWER_RUNTIME_ROOT"
