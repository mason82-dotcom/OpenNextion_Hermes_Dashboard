#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FILE="$ROOT/config/bridge.env"
if [[ ! -f "$FILE" ]]; then printf 'Missing config/bridge.env\n' >&2; exit 1; fi
# Trusted, local-only config created by create-local-config.sh.
set -a
# shellcheck disable=SC1090
. "$FILE"
set +a
exec python3 "$ROOT/bridge/hermes_touch_bridge.py"
