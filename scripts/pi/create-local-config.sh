#!/usr/bin/env bash
# Creates local credentials in ignored config file. Never overwrites existing config.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="$ROOT/config/bridge.env"
mkdir -p "$ROOT/config"
if [[ -e "$TARGET" ]]; then
  printf 'Already exists: %s\nNo changes made.\n' "$TARGET"
  exit 0
fi
umask 077
TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
printf "HERMES_TOUCH_BIND=127.0.0.1\nHERMES_TOUCH_PORT=8765\nHERMES_TOUCH_TOKEN=%s\nHERMES_DASHBOARD_URL=http://127.0.0.1:9119\n" "$TOKEN" > "$TARGET"
chmod 600 "$TARGET"
printf 'Created %s (mode 600). No secrets printed.\n' "$TARGET"
printf 'Default binding: loopback only. Agent files unchanged.\n'
