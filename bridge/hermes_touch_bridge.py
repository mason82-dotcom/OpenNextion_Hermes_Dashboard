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
import socket
import threading
import time
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
    """Bounded, read-only dashboard check with diagnostic reason codes."""
    result = {
        "dashboard_reachable": False,
        "dashboard_status_available": False,
        "dashboard_reason": "pending",
        "dashboard_http_status": None,
        "gateway_running": None,
        "version": None,
    }
    try:
        req = Request(DASHBOARD_URL + "/api/status", headers={"Accept": "application/json"})
        with urlopen(req, timeout=3.0) as response:
            result["dashboard_reachable"] = True
            result["dashboard_http_status"] = response.status
            body = response.read(65537)
            if len(body) > 65536:
                result["dashboard_reason"] = "response_too_large"
            else:
                try:
                    data = json.loads(body)
                    if isinstance(data, dict):
                        result["dashboard_status_available"] = True
                        result["dashboard_reason"] = "ok"
                        version = data.get("version")
                        result["version"] = str(version)[:80] if version is not None else None
                        gateway = data.get("gateway_running")
                        result["gateway_running"] = gateway if isinstance(gateway, bool) else None
                    else:
                        result["dashboard_reason"] = "unexpected_json"
                except (ValueError, UnicodeDecodeError):
                    result["dashboard_reason"] = "invalid_json"
    except HTTPError as exc:
        result["dashboard_reachable"] = True
        result["dashboard_reason"] = f"http_{exc.code}"
        result["dashboard_http_status"] = exc.code
    except (TimeoutError, socket.timeout):
        result["dashboard_reason"] = "timeout"
    except URLError as exc:
        result["dashboard_reason"] = (
            "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout))
            else "connection_error"
        )
    except OSError:
        result["dashboard_reason"] = "connection_error"

    # The lightweight public /api/health can still confirm HTTP reachability
    # if /api/status is slow or unavailable.
    if not result["dashboard_reachable"]:
        try:
            req = Request(DASHBOARD_URL + "/api/health",
                          headers={"Accept": "application/json"})
            with urlopen(req, timeout=1.5) as response:
                result["dashboard_reachable"] = 200 <= response.status < 300
        except HTTPError:
            result["dashboard_reachable"] = True
        except (URLError, TimeoutError, socket.timeout, OSError):
            pass
    return result


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
    except HTTPError:
        # An HTTP error status proves the API answered, but not that it is healthy.
        return {"api_reachable": True, "api_healthy": False}
    except (URLError, TimeoutError, OSError, ValueError):
        return {"api_reachable": False, "api_healthy": False}


# Hermes dashboard status may take seconds; never block ESP32 HTTP requests.
# A complete probe cycle normally finishes every 15s. Fail closed if the
# background worker stops updating the cache for longer than three intervals.
PROBE_MAX_AGE_SECONDS = 45.0
_probe_lock = threading.Lock()
_probe_data = {
    "dashboard_reachable": False,
    "dashboard_status_available": False,
    "dashboard_reason": "pending",
    "dashboard_http_status": None,
    "gateway_running": None,
    "version": None,
    "api_reachable": False,
    "api_healthy": False,
}
_last_probe_monotonic = None
_last_probe_success = None  # UTC Unix seconds of last COMPLETED cycle, not healthy state.


def health_snapshot(*, now_monotonic=None):
    """Return cached health, never reporting expired results as healthy.

    Pi metrics remain independently live in status_payload(). An HTTPS 200
    indicates that the bridge responded, not necessarily that Hermes is alive.
    """
    with _probe_lock:
        data = dict(_probe_data)
        last_mono = _last_probe_monotonic
        last_epoch = _last_probe_success

    current = time.monotonic() if now_monotonic is None else now_monotonic
    age = None if last_mono is None else current - last_mono
    fresh = age is not None and 0.0 <= age <= PROBE_MAX_AGE_SECONDS
    data.update({
        "probe_fresh": fresh,
        "probe_age_s": round(age, 1) if age is not None and age >= 0 else None,
        "last_probe_success": last_epoch,
    })
    if not fresh:
        # False -> definitely not confirmed healthy. Unknown gateway -> "--"
        # on the ESP32; never carry forward a previous ON state.
        data.update({
            "dashboard_reachable": False,
            "dashboard_status_available": False,
            "dashboard_reason": "pending" if last_mono is None else "stale_cache",
            "dashboard_http_status": None,
            "gateway_running": None,
            "version": None,
            "api_reachable": False,
            "api_healthy": False,
        })
    return data


def probe_cycle():
    """Publish a full coherent probe result only if both functions returned."""
    data = {**dashboard_probe(), **api_health_probe()}
    completed_mono = time.monotonic()
    completed_epoch = int(time.time())
    global _last_probe_monotonic, _last_probe_success
    with _probe_lock:
        _probe_data.update(data)
        _last_probe_monotonic = completed_mono
        _last_probe_success = completed_epoch


def probe_worker(stop_event):
    while not stop_event.is_set():
        try:
            probe_cycle()
        except Exception:
            pass  # Next cycle retries; never leak upstream exception details.
        if stop_event.wait(15):
            break


def status_payload():
    return {
        "ok": True,
        "schema_version": 1,
        "system": system_snapshot(),
        "hermes": health_snapshot(),
        "chat": {"enabled": False},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesTouch/0.3"

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
    stop_event = threading.Event()
    worker = threading.Thread(target=probe_worker, args=(stop_event,), daemon=True)
    worker.start()
    print(f"Hermes Touch: http://{HOST}:{PORT} (READ-ONLY)", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        worker.join(timeout=2)
        server.server_close()


if __name__ == "__main__":
    main()
