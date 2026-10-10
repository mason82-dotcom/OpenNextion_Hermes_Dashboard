#!/usr/bin/env bash
# Certificate-verified status request. Prints only selected fields, never tokens.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck disable=SC1090
. "$ROOT/config/bridge.env"
# shellcheck disable=SC1090
. "$ROOT/config/tls.env"
set +a
CA="$ROOT/config/pki/ca.crt"
python3 - "$CA" <<'PY'
import json, os, ssl, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
ctx = ssl.create_default_context(cafile=sys.argv[1])
url = f'https://{os.environ["HERMES_TOUCH_TLS_BIND"]}:{os.environ["HERMES_TOUCH_TLS_PORT"]}/v1/status'
req = Request(url, headers={"X-Hermes-Touch-Token": os.environ["HERMES_TOUCH_TOKEN"]})
try:
    with urlopen(req, context=ctx, timeout=5) as response:
        doc = json.load(response)
except (OSError, ValueError, ssl.SSLError, HTTPError, URLError) as exc:
    raise SystemExit(f"TLS status FAIL: {type(exc).__name__} (certificate or server issue)")
hermes = doc.get("hermes", {})
sysinfo = doc.get("system", {})
print("TLS verified against locally generated CA: YES")
print("Bridge JSON status:", "ok" if doc.get("ok") else "error")
print("Hermes API healthy:", hermes.get("api_healthy"))
print("Hermes Dashboard status:", hermes.get("dashboard_status_available"))
print("Gateway running:", hermes.get("gateway_running"))
print("Pi CPU temp (C):", sysinfo.get("cpu_temp_c"))
print("Pi RAM used (%):", sysinfo.get("ram_used_pct"))
print("Pi load:", sysinfo.get("load1"))
print("Chat enabled:", doc.get("chat", {}).get("enabled"))
PY
