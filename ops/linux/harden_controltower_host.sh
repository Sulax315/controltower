#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "harden_controltower_host.sh must run as root." >&2
  exit 64
fi

ENV_FILE="${1:-${CONTROLTOWER_ENV_FILE:-/etc/controltower/controltower.env}}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing Control Tower env file: $ENV_FILE" >&2
  exit 65
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${CONTROLTOWER_APP_ROOT:?CONTROLTOWER_APP_ROOT must be set in the env file.}"
: "${CONTROLTOWER_CONFIG:?CONTROLTOWER_CONFIG must be set in the env file.}"
: "${CONTROLTOWER_RUNTIME_ROOT:?CONTROLTOWER_RUNTIME_ROOT must be set in the env file.}"
: "${CONTROLTOWER_SERVICE_USER:?CONTROLTOWER_SERVICE_USER must be set in the env file.}"

CONTROLTOWER_SERVICE_GROUP="${CONTROLTOWER_SERVICE_GROUP:-$CONTROLTOWER_SERVICE_USER}"
CONTROLTOWER_HOME="${CONTROLTOWER_HOME:-$(dirname "$CONTROLTOWER_APP_ROOT")}"
CONTROLTOWER_SHARED_ROOT="${CONTROLTOWER_SHARED_ROOT:-$(dirname "$CONTROLTOWER_RUNTIME_ROOT")}"
CONTROLTOWER_SHARED_OPS_ROOT="${CONTROLTOWER_SHARED_OPS_ROOT:-$CONTROLTOWER_SHARED_ROOT/ops}"
SSH_DIR="$CONTROLTOWER_HOME/.ssh"
LOOPBACK_KEY="$SSH_DIR/controltower_release_loopback"
LOOPBACK_PUB="$LOOPBACK_KEY.pub"
LOOPBACK_ALIAS="${CONTROLTOWER_LOOPBACK_SSH_ALIAS:-controltower-loopback}"
LOOPBACK_HOST="${CONTROLTOWER_LOOPBACK_SSH_HOST:-controltower.bratek.io}"
LOOPBACK_HOSTNAME="${CONTROLTOWER_LOOPBACK_SSH_HOSTNAME:-127.0.0.1}"
LOOPBACK_PORT="${CONTROLTOWER_LOOPBACK_SSH_PORT:-22}"
ORCHESTRATION_ROOT="${CONTROLTOWER_ORCHESTRATION_ROOT:-$CONTROLTOWER_SHARED_OPS_ROOT/orchestration}"

resolve_vault_root() {
  "${PYTHON_BIN:-python3}" - "$CONTROLTOWER_CONFIG" <<'PY'
import sys
from pathlib import Path

import yaml

payload = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
vault_root = ((payload.get("obsidian") or {}).get("vault_root") or "").strip()
if not vault_root:
    raise SystemExit("obsidian.vault_root is missing from the Control Tower config.")
print(vault_root)
PY
}

ensure_loopback_known_hosts() {
  local temp_file
  temp_file="$(mktemp)"
  if [[ -f "$SSH_DIR/known_hosts" ]]; then
    awk -v alias="$LOOPBACK_ALIAS" -v host="$LOOPBACK_HOST" '
      $1 == alias || $1 == host || index($1, alias ",") == 1 || index($1, host ",") == 1 { next }
      { print }
    ' "$SSH_DIR/known_hosts" >"$temp_file"
  fi
  ssh-keyscan -p "$LOOPBACK_PORT" -t ed25519,ecdsa,rsa "$LOOPBACK_HOSTNAME" 2>/dev/null \
    | awk -v alias="$LOOPBACK_ALIAS" -v host="$LOOPBACK_HOST" '{ $1 = alias "," host; print }' >>"$temp_file"
  install -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" -m 0600 "$temp_file" "$SSH_DIR/known_hosts"
  rm -f "$temp_file"
}

VAULT_ROOT="$(resolve_vault_root)"

install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" "$CONTROLTOWER_RUNTIME_ROOT"
install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" "$CONTROLTOWER_SHARED_OPS_ROOT"
install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" "$ORCHESTRATION_ROOT"
install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" "$VAULT_ROOT"
chown -R "$CONTROLTOWER_SERVICE_USER:$CONTROLTOWER_SERVICE_GROUP" "$CONTROLTOWER_RUNTIME_ROOT" "$CONTROLTOWER_SHARED_OPS_ROOT" "$ORCHESTRATION_ROOT" "$VAULT_ROOT"

install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" -m 0700 "$SSH_DIR"
if [[ ! -f "$LOOPBACK_KEY" ]]; then
  sudo -u "$CONTROLTOWER_SERVICE_USER" ssh-keygen -q -t ed25519 -N "" -f "$LOOPBACK_KEY"
fi

if [[ ! -f "$SSH_DIR/authorized_keys" ]]; then
  install -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" -m 0600 /dev/null "$SSH_DIR/authorized_keys"
fi
if ! grep -qxF "$(cat "$LOOPBACK_PUB")" "$SSH_DIR/authorized_keys"; then
  printf '%s\n' "$(cat "$LOOPBACK_PUB")" >>"$SSH_DIR/authorized_keys"
fi

cat >"$SSH_DIR/config" <<EOF
Host ${LOOPBACK_HOST} ${LOOPBACK_ALIAS}
    HostName ${LOOPBACK_HOSTNAME}
    HostKeyAlias ${LOOPBACK_ALIAS}
    User ${CONTROLTOWER_SERVICE_USER}
    Port ${LOOPBACK_PORT}
    IdentityFile ~/.ssh/controltower_release_loopback
    IdentitiesOnly yes
    BatchMode yes
    StrictHostKeyChecking yes
    CheckHostIP no
EOF

ensure_loopback_known_hosts

chown "$CONTROLTOWER_SERVICE_USER:$CONTROLTOWER_SERVICE_GROUP" \
  "$SSH_DIR/config" \
  "$SSH_DIR/authorized_keys" \
  "$SSH_DIR/known_hosts" \
  "$LOOPBACK_KEY" \
  "$LOOPBACK_PUB"
chmod 0600 "$SSH_DIR/config" "$SSH_DIR/authorized_keys" "$SSH_DIR/known_hosts" "$LOOPBACK_KEY"
chmod 0644 "$LOOPBACK_PUB"

echo "Vault ownership repaired: $VAULT_ROOT"
echo "Runtime ownership repaired: $CONTROLTOWER_RUNTIME_ROOT"
echo "Approval orchestration ownership repaired: $ORCHESTRATION_ROOT"
echo "Loopback SSH hardened: $SSH_DIR/config"
