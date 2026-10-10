#!/usr/bin/env bash
# Local integration smoke test. Prints no tokens or Hermes configuration.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FILE="$ROOT/config/bridge.env"
if [[ ! -f "$FILE" ]]; then
  printf 'Missing config/bridge.env; create it first.\n' >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
. "$FILE"
set +a
python3 - <<'PY'
import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

host = os.environ.get("HERMES_TOUCH_BIND", "127.0.0.1")
port = os.environ.get("HERMES_TOUCH_PORT", "8765")
url = f"http://{host}:{port}/v1/status"
req = Request(url, headers={"X-Hermes-Touch-Token": os.environ["HERMES_TOUCH_TOKEN"]})
try:
    with urlopen(req, timeout=3) as response:
        doc = json.load(response)
except (HTTPError, URLError, ValueError, TimeoutError, OSError) as exc:
    raise SystemExit(f"Bridge not available: {type(exc).__name__} (ensure bridge running)")
system = doc.get("system", {})
hermes = doc.get("hermes", {})
print("Bridge:", "ok" if doc.get("ok") else "error")
print("Hermes API /health:", "healthy" if hermes.get("api_healthy") else "not confirmed")
print("Hermes Dashboard /api/status:", "reachable" if hermes.get("dashboard_reachable") else "not confirmed")
print("CPU temp:", system.get("cpu_temp_c"))
print("RAM used (%):", system.get("ram_used_pct"))
print("System load 1min:", system.get("load1"))
print("Chat writes:", "disabled" if not doc.get("chat", {}).get("enabled") else "ENABLED (unexpected)")
PY
