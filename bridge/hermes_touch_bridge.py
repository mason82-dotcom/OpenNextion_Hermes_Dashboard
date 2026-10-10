#!/usr/bin/env python3
"""Read-only Hermes Touch status bridge. Python >=3.10, stdlib only.

Does not modify Hermes config, systemd services, credentials or memory.
Chat/OS command execution are intentionally NOT exposed.
Use trusted local access only; HTTP token headers are not encryption.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

HOST = os.environ.get("HERMES_TOUCH_BIND", "127.0.0.1")
PORT = int(os.environ.get("HERMES_TOUCH_PORT", "8765"))
TOKEN = os.environ.get("HERMES_TOUCH_TOKEN", "")
DASHBOARD_URL = os.environ.get("HERMES_DASHBOARD_URL", "http://127.0.0.1:9119").rstrip("/")
API_URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642").rstrip("/")


def optional_number(path: str, divisor: float = 1.0, decimals: int = 1):
    try:
        return round(float(Path(path).read_text().strip().split()[0]) / divisor, decimals)
    except (OSError, ValueError, IndexError):
        return None


def system_snapshot():
    mem = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    used = round(100 * (total - available) / total, 1) if total else None
    try:
        load = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load = None
    return {
        "cpu_temp_c": optional_number("/sys/class/thermal/thermal_zone0/temp", 1000),
        "ram_used_pct": used,
        "ram_total_mb": round(total / 1024) if total else None,
        "load1": load,
        "uptime_s": optional_number("/proc/uptime"),
    }


def dashboard_probe():
    # A reachable dashboard does not prove the Hermes gateway is healthy.
    try:
        with urlopen(Request(DASHBOARD_URL + "/api/status",
                             headers={"Accept": "application/json"}), timeout=1.0) as r:
            data = json.load(r)
            return {"dashboard_reachable": isinstance(data, dict),
                    "version": str(data.get("version", ""))[:80] if isinstance(data, dict) else None}
    except (URLError, HTTPError, TimeoutError, ValueError, OSError):
        return {"dashboard_reachable": False, "version": None}


def api_health_probe():
    """Probe the official public /health route, not a model inference request.

    Healthy API != authenticated model access or full gateway readiness.
    """
    try:
        req = Request(API_URL + "/health", headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.0) as r:
            payload = json.loads(r.read(4096))
            return {"api_reachable": True,
                    "api_healthy": isinstance(payload, dict) and payload.get("status") == "ok"}
    except (URLError, HTTPError, TimeoutError, OSError, ValueError):
        return {"api_reachable": False, "api_healthy": False}


def status_payload():
    return {
        "ok": True,
        "schema_version": 1,
        "system": system_snapshot(),
        "hermes": {**dashboard_probe(), **api_health_probe()},
        "chat": {"enabled": False},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesTouch/0.1"

    def log_message(self, fmt, *args):
        # Standard request log omits headers and secrets.
        super().log_message(fmt, *args)

    def respond(self, status, data):
        body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        value = self.headers.get("X-Hermes-Touch-Token", "")
        return len(TOKEN) >= 24 and hmac.compare_digest(TOKEN, value)

    def do_GET(self):
        if not self.allowed():
            self.respond(401, {"error": "unauthorized"})
        elif urlsplit(self.path).path == "/v1/status":
            self.respond(200, status_payload())
        else:
            self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if not self.allowed():
            self.respond(401, {"error": "unauthorized"})
        else:
            self.respond(403, {"error": "read_only"})


def main():
    if len(TOKEN) < 24:
        raise SystemExit("HERMES_TOUCH_TOKEN must contain at least 24 characters")
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: HTTP transmits your token unencrypted. Use only trusted isolated LAN.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes Touch: http://{HOST}:{PORT} (READ-ONLY)", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
