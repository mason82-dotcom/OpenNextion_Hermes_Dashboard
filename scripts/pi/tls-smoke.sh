#!/usr/bin/env bash
# TLS-verified, proxy-free Pi status probe. Prints no tokens, passwords or raw responses.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
for f in "$ROOT/config/bridge.env" "$ROOT/config/tls.env" "$ROOT/config/pki/ca.crt"; do
  if [[ ! -s "$f" ]]; then
    printf 'Missing TLS probe prerequisite: %s\n' "${f##*/}" >&2
    exit 2
  fi
done
set -a
# shellcheck disable=SC1090
. "$ROOT/config/bridge.env"
# shellcheck disable=SC1090
. "$ROOT/config/tls.env"
set +a

python3 - "$ROOT/config/pki/ca.crt" <<'PY'
import json
import os
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

ctx = ssl.create_default_context(cafile=sys.argv[1])
ctx.check_hostname = True
ctx.verify_mode = ssl.CERT_REQUIRED

host = os.environ["HERMES_TOUCH_TLS_BIND"]
port = int(os.environ.get("HERMES_TOUCH_TLS_PORT", "8766"))
token = os.environ["HERMES_TOUCH_TOKEN"]
url = f"https://{host}:{port}/v1/status"
req = Request(url, headers={"X-Hermes-Touch-Token": token, "Accept": "application/json"})
# Intentionally do not use HTTPS_PROXY/HTTP_PROXY/ALL_PROXY from the Pi shell:
# traffic to its own LAN address must be a direct, certificate-verified connection.
opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ctx))

try:
    with opener.open(req, timeout=5) as response:
        doc = json.load(response)
except HTTPError as exc:
    # An HTTP status here came from a TLS-verified direct peer; never print the
    # response body, arbitrary proxy messages, request headers or credentials.
    hints = {
        401: "Device token not accepted; check TLS service and bridge token consistency.",
        403: "Request forbidden by HTTPS service.",
        404: "Wrong endpoint/service on port 8766.",
        405: "HTTP method denied.",
        502: "Unexpected or oversized response from loopback bridge.",
        503: "HTTPS service reachable, but loopback bridge on 127.0.0.1:8765 unavailable.",
    }
    print("TLS certificate validation: OK (direct connection, trusted CA and IP match)")
    print(f"HTTP status: {exc.code}")
    print(hints.get(exc.code, "HTTPS service returned an error; check the service on port 8766."))
    raise SystemExit(1)
except URLError as exc:
    reason = exc.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        print("TLS FAIL: server certificate, CA chain, time or IP name validation failed.")
    elif isinstance(reason, ssl.SSLError):
        print("TLS FAIL: encrypted handshake failed.")
    elif isinstance(reason, ConnectionRefusedError):
        print("CONNECTION FAIL: no HTTPS listener on the configured Pi LAN IP and port 8766.")
    else:
        print(f"CONNECTION FAIL: {type(reason).__name__}; inspect local listener/firewall.")
    raise SystemExit(1)
except (OSError, ValueError, TypeError):
    print("TLS probe FAIL: transport error or invalid JSON received.")
    raise SystemExit(1)

if not isinstance(doc, dict) or doc.get("ok") is not True:
    raise SystemExit("TLS probe FAIL: authenticated service returned unexpected JSON.")
hermes = doc.get("hermes", {})
sysinfo = doc.get("system", {})
print("TLS verified against locally generated CA: YES (direct, no proxy)")
print("Bridge JSON status: ok")
print("Hermes API healthy:", hermes.get("api_healthy"))
print("Hermes Dashboard status:", hermes.get("dashboard_status_available"))
print("Gateway running:", hermes.get("gateway_running"))
print("Pi CPU temp (C):", sysinfo.get("cpu_temp_c"))
print("Pi RAM used (%):", sysinfo.get("ram_used_pct"))
print("Pi load:", sysinfo.get("load1"))
print("Chat enabled:", doc.get("chat", {}).get("enabled"))
PY
