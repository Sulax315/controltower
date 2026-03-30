#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/controltower_operation.sh" diagnostics_snapshot diagnostics_snapshot_controltower.py "$@"
