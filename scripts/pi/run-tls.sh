#!/usr/bin/env bash
# Start TLS gateway on the Pi's configured LAN IP only.
# REQUIRE the existing read-only Bridge running on loopback.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for file in "$ROOT/config/bridge.env" "$ROOT/config/tls.env"; do
  if [[ ! -f "$file" ]]; then
    printf 'Missing %s\n' "$file" >&2
    exit 2
  fi
done
set -a
# shellcheck disable=SC1090
. "$ROOT/config/bridge.env"
# shellcheck disable=SC1090
. "$ROOT/config/tls.env"
set +a
if [[ "${HERMES_TOUCH_BIND:-127.0.0.1}" != "127.0.0.1" ]]; then
  printf 'REFUSED: bridge HTTP must bind only to 127.0.0.1.\n' >&2
  exit 3
fi
exec python3 "$ROOT/bridge/tls_status_server.py"
