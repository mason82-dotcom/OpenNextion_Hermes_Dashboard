#!/usr/bin/env bash
# Monitors the already-running private LAN TLS endpoint; does not touch Hermes.
# Uses only the independent device token (not the loopback Bridge token).
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ ! -r "$ROOT/config/tls.env" || ! -r "$ROOT/config/pki/ca.crt" ]]; then
  printf 'TLS config/public CA not found. See docs/TLS-LIVE-SETUP.md\n' >&2
  exit 2
fi
set -a
# shellcheck disable=SC1090
. "$ROOT/config/tls.env"
set +a
exec python3 "$ROOT/scripts/pi/stability_monitor.py" "$@"
