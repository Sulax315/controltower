#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "release_controltower.sh is deprecated; use infra/deploy/controltower/deploy_update.sh instead." >&2
exec bash "$REPO_ROOT/infra/deploy/controltower/deploy_update.sh" "$@"
