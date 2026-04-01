#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "install_host.sh must run as root." >&2
  exit 64
fi

ENV_FILE="${1:-${CONTROLTOWER_ENV_FILE:-/etc/controltower/controltower.env}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_ROOT="$SCRIPT_DIR/templates"
RENDER_PYTHON="${CONTROLTOWER_BOOTSTRAP_PYTHON:-python3}"

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
: "${PYTHON_BIN:?PYTHON_BIN must be set in the env file.}"
: "${CONTROLTOWER_DOMAIN:?CONTROLTOWER_DOMAIN must be set in the env file.}"
: "${CONTROLTOWER_SERVICE_USER:?CONTROLTOWER_SERVICE_USER must be set in the env file.}"

CONTROLTOWER_SERVICE_GROUP="${CONTROLTOWER_SERVICE_GROUP:-$CONTROLTOWER_SERVICE_USER}"
CONTROLTOWER_SERVICE_NAME="${CONTROLTOWER_SERVICE_NAME:-controltower-web}"
CONTROLTOWER_CRON_USER="${CONTROLTOWER_CRON_USER:-$CONTROLTOWER_SERVICE_USER}"
CONTROLTOWER_PORT="${CONTROLTOWER_PORT:-8787}"
CONTROLTOWER_DAILY_CRON="${CONTROLTOWER_DAILY_CRON:-30 5 * * 1-5}"
CONTROLTOWER_WEEKLY_CRON="${CONTROLTOWER_WEEKLY_CRON:-0 6 * * 6}"
CONTROLTOWER_TLS_CERTIFICATE="${CONTROLTOWER_TLS_CERTIFICATE:-/etc/letsencrypt/live/$CONTROLTOWER_DOMAIN/fullchain.pem}"
CONTROLTOWER_TLS_CERTIFICATE_KEY="${CONTROLTOWER_TLS_CERTIFICATE_KEY:-/etc/letsencrypt/live/$CONTROLTOWER_DOMAIN/privkey.pem}"
CONTROLTOWER_TLS_OPTIONS_INCLUDE="${CONTROLTOWER_TLS_OPTIONS_INCLUDE:-/etc/letsencrypt/options-ssl-nginx.conf}"
CONTROLTOWER_TLS_DHPARAM="${CONTROLTOWER_TLS_DHPARAM:-/etc/letsencrypt/ssl-dhparams.pem}"
CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR="${CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR:-/etc/nginx/sites-available}"
CONTROLTOWER_NGINX_SITE_ENABLED_DIR="${CONTROLTOWER_NGINX_SITE_ENABLED_DIR:-/etc/nginx/sites-enabled}"
CONTROLTOWER_NGINX_SITE_NAME="${CONTROLTOWER_NGINX_SITE_NAME:-$CONTROLTOWER_DOMAIN}"
CONTROLTOWER_SYSTEMD_UNIT_DIR="${CONTROLTOWER_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

export APP_ROOT="$CONTROLTOWER_APP_ROOT"
export CONFIG_FILE="$CONTROLTOWER_CONFIG"
export ENV_FILE
export RUNTIME_ROOT="$CONTROLTOWER_RUNTIME_ROOT"
export PYTHON_BIN
export PORT="$CONTROLTOWER_PORT"
export SERVICE_USER="$CONTROLTOWER_SERVICE_USER"
export SERVICE_GROUP="$CONTROLTOWER_SERVICE_GROUP"
export SERVICE_NAME="$CONTROLTOWER_SERVICE_NAME"
export CRON_USER="$CONTROLTOWER_CRON_USER"
export DAILY_CRON="$CONTROLTOWER_DAILY_CRON"
export WEEKLY_CRON="$CONTROLTOWER_WEEKLY_CRON"
export DOMAIN="$CONTROLTOWER_DOMAIN"
export TLS_CERTIFICATE="$CONTROLTOWER_TLS_CERTIFICATE"
export TLS_CERTIFICATE_KEY="$CONTROLTOWER_TLS_CERTIFICATE_KEY"
export TLS_OPTIONS_INCLUDE="$CONTROLTOWER_TLS_OPTIONS_INCLUDE"
export TLS_DHPARAM="$CONTROLTOWER_TLS_DHPARAM"

render_template() {
  local template_path="$1"
  local output_path="$2"
  "$RENDER_PYTHON" - "$template_path" "$output_path" <<'PY'
import os
import sys
from pathlib import Path

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
content = template_path.read_text(encoding="utf-8")
replacements = {
    "__APP_ROOT__": os.environ["APP_ROOT"],
    "__CONFIG_FILE__": os.environ["CONFIG_FILE"],
    "__ENV_FILE__": os.environ["ENV_FILE"],
    "__RUNTIME_ROOT__": os.environ["RUNTIME_ROOT"],
    "__PYTHON_BIN__": os.environ["PYTHON_BIN"],
    "__PORT__": os.environ["PORT"],
    "__SERVICE_USER__": os.environ["SERVICE_USER"],
    "__SERVICE_GROUP__": os.environ["SERVICE_GROUP"],
    "__SERVICE_NAME__": os.environ["SERVICE_NAME"],
    "__CRON_USER__": os.environ["CRON_USER"],
    "__DAILY_CRON__": os.environ["DAILY_CRON"],
    "__WEEKLY_CRON__": os.environ["WEEKLY_CRON"],
    "__DOMAIN__": os.environ["DOMAIN"],
    "__TLS_CERTIFICATE__": os.environ["TLS_CERTIFICATE"],
    "__TLS_CERTIFICATE_KEY__": os.environ["TLS_CERTIFICATE_KEY"],
    "__TLS_OPTIONS_INCLUDE__": os.environ["TLS_OPTIONS_INCLUDE"],
    "__TLS_DHPARAM__": os.environ["TLS_DHPARAM"],
}
for needle, replacement in replacements.items():
    content = content.replace(needle, replacement)
output_path.write_text(content, encoding="utf-8", newline="\n")
PY
}

install -d -o "$CONTROLTOWER_SERVICE_USER" -g "$CONTROLTOWER_SERVICE_GROUP" "$CONTROLTOWER_RUNTIME_ROOT" "$CONTROLTOWER_RUNTIME_ROOT/logs"
install -d "$CONTROLTOWER_SYSTEMD_UNIT_DIR" "$CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR" "$CONTROLTOWER_NGINX_SITE_ENABLED_DIR"

render_template "$TEMPLATE_ROOT/controltower-web.service.tpl" "$TMP_DIR/controltower-web.service"
render_template "$TEMPLATE_ROOT/controltower.cron.tpl" "$TMP_DIR/controltower.cron"
render_template "$TEMPLATE_ROOT/controltower-nginx.conf.tpl" "$TMP_DIR/controltower-nginx.conf"

install -m 0644 "$TMP_DIR/controltower-web.service" "$CONTROLTOWER_SYSTEMD_UNIT_DIR/$CONTROLTOWER_SERVICE_NAME.service"
install -m 0644 "$TMP_DIR/controltower.cron" "/etc/cron.d/controltower"
install -m 0644 "$TMP_DIR/controltower-nginx.conf" "$CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR/$CONTROLTOWER_NGINX_SITE_NAME"
ln -sfn "$CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR/$CONTROLTOWER_NGINX_SITE_NAME" "$CONTROLTOWER_NGINX_SITE_ENABLED_DIR/$CONTROLTOWER_NGINX_SITE_NAME"

if [[ "$CONTROLTOWER_NGINX_SITE_NAME" != "$CONTROLTOWER_DOMAIN.conf" ]]; then
  rm -f \
    "$CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR/$CONTROLTOWER_DOMAIN.conf" \
    "$CONTROLTOWER_NGINX_SITE_ENABLED_DIR/$CONTROLTOWER_DOMAIN.conf"
fi

systemctl daemon-reload
systemctl enable --now "$CONTROLTOWER_SERVICE_NAME.service"
nginx -t
systemctl reload nginx
bash "$CONTROLTOWER_APP_ROOT/ops/linux/harden_controltower_host.sh" "$ENV_FILE"

echo "Installed systemd unit: $CONTROLTOWER_SYSTEMD_UNIT_DIR/$CONTROLTOWER_SERVICE_NAME.service"
echo "Installed cron file: /etc/cron.d/controltower"
echo "Installed nginx site: $CONTROLTOWER_NGINX_SITE_AVAILABLE_DIR/$CONTROLTOWER_NGINX_SITE_NAME"
