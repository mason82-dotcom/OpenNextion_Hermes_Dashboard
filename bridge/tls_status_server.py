#!/usr/bin/env python3
"""TLS-only LAN facade over the existing LOOPBACK Hermes Touch bridge.

Requires an explicit RFC1918 bind address, a valid TLS server certificate
and a separate device token. Does not expose Hermes directly.
Exact-path allowlist: status and quick-chat reads via GET, and one POST that
carries only a validated whitelist prompt ID (never free text).
Python stdlib only; no HTTP fallback or proxy tunnelling.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

TOKEN = os.environ.get("HERMES_TOUCH_TOKEN", "")
DEVICE_TOKEN = os.environ.get("HERMES_TOUCH_DEVICE_TOKEN", "")
LOCAL_PORT = int(os.environ.get("HERMES_TOUCH_PORT", "8765"))
TLS_BIND = os.environ.get("HERMES_TOUCH_TLS_BIND", "")
TLS_PORT = int(os.environ.get("HERMES_TOUCH_TLS_PORT", "8766"))
TLS_CERT = os.environ.get("HERMES_TOUCH_TLS_CERT", "")
TLS_KEY = os.environ.get("HERMES_TOUCH_TLS_KEY", "")
# A client that connects but never completes TLS or its request (port scan,
# ESP32 losing WiFi mid-handshake) must not hold a server thread forever.
CONNECTION_TIMEOUT_SECONDS = 10.0
GET_PATHS = frozenset(("/v1/status", "/v1/chat/prompts", "/v1/chat/state"))
ASK_PATH = "/v1/chat/ask"
PROMPT_ID_RE = re.compile(r"^[a-z0-9_]{1,16}$")
ASK_BODY_MAX = 256
# Only these bridge refusals are passed on to the device, without details.
ASK_RELAYED = {400: "bad_request", 403: "chat_disabled", 404: "unknown_prompt",
               409: "busy", 429: "rate_limited"}
PRIVATE_V4_NETWORKS = tuple(ipaddress.ip_network(prefix) for prefix in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


def validate_private_bind(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("TLS bind must be an explicit IPv4 LAN address") from exc
    if ip.version != 4 or not any(ip in net for net in PRIVATE_V4_NETWORKS):
        raise ValueError("TLS bind must be an explicit RFC1918 IPv4 LAN address")
    return str(ip)


def fetch_loopback(path: str, body: bytes | None = None) -> tuple[int, bytes]:
    """Call the internal Bridge without ever inheriting proxy settings.

    Authentication token must not be forwarded to an HTTP_PROXY/ALL_PROXY.
    Only the exact local loopback origin and allowlisted paths are used.
    """
    headers = {"X-Hermes-Touch-Token": TOKEN, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(f"http://127.0.0.1:{LOCAL_PORT}{path}", data=body, headers=headers,
                  method="POST" if body is not None else "GET")
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(req, timeout=2.0) as upstream:
            return upstream.status, upstream.read(16385)
    except HTTPError as exc:
        return exc.code, b""


def fetch_loopback_status() -> bytes:
    return fetch_loopback("/v1/status")[1]


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesTouchTLS/0.6"
    timeout = CONNECTION_TIMEOUT_SECONDS

    def log_message(self, _fmt, *_args):
        # Never include the request URL or token in logs.
        pass

    def respond(self, code: int, payload: dict):
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authenticated(self):
        supplied = self.headers.get("X-Hermes-Touch-Token", "")
        return len(DEVICE_TOKEN) >= 24 and hmac.compare_digest(DEVICE_TOKEN, supplied)

    def do_GET(self):
        # Exact match: reject query strings, path traversal and other endpoints.
        if self.path not in GET_PATHS:
            self.respond(404, {"error": "not_found"})
            return
        if not self.authenticated():
            self.respond(401, {"error": "unauthorized"})
            return
        try:
            if self.path == "/v1/status":
                code, data = 200, fetch_loopback_status()
            else:
                code, data = fetch_loopback(self.path)
            if code != 200:
                raise ValueError("unexpected backend status")
            if len(data) > 16384:
                self.respond(502, {"error": "upstream_too_large"})
                return
            # Never return an arbitrary upstream error or HTML to the device.
            status = json.loads(data)
            if not isinstance(status, dict) or status.get("ok") is not True:
                raise ValueError("unexpected backend response")
            self.respond(200, status)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            self.respond(503, {"error": "loopback_bridge_unavailable"})

    def do_POST(self):
        if self.path != ASK_PATH:
            self.respond(405, {"error": "read_only"})
            return
        if not self.authenticated():
            self.respond(401, {"error": "unauthorized"})
            return
        prompt_id = self.read_prompt_id()
        if prompt_id is None:
            self.respond(400, {"ok": False, "error": "bad_request"})
            return
        # Re-serialize: only the validated ID ever reaches the Bridge.
        body = json.dumps({"prompt_id": prompt_id}).encode("ascii")
        try:
            code, data = fetch_loopback(ASK_PATH, body)
            if code == 202:
                reply = json.loads(data)
                job = reply.get("job") if isinstance(reply, dict) else None
                if not isinstance(job, int) or isinstance(job, bool):
                    raise ValueError("unexpected backend response")
                self.respond(202, {"ok": True, "job": job})
            elif code in ASK_RELAYED:
                self.respond(code, {"ok": False, "error": ASK_RELAYED[code]})
            else:
                raise ValueError("unexpected backend status")
        except (URLError, TimeoutError, OSError, ValueError):
            self.respond(503, {"error": "loopback_bridge_unavailable"})

    def read_prompt_id(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        if not 0 < length <= ASK_BODY_MAX:
            return None
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError, OSError):
            return None
        if not isinstance(data, dict) or set(data) != {"prompt_id"}:
            return None
        pid = data["prompt_id"]
        return pid if isinstance(pid, str) and PROMPT_ID_RE.match(pid) else None

    def do_PUT(self):
        self.respond(405, {"error": "read_only"})

    def do_DELETE(self):
        self.respond(405, {"error": "read_only"})

    def do_PATCH(self):
        self.respond(405, {"error": "read_only"})


class TlsHTTPServer(ThreadingHTTPServer):
    """Performs the TLS handshake in the per-connection thread, not in accept().

    Wrapping the listening socket would run every handshake inside the single
    serve_forever() thread, so one idle TCP client blocks all other devices.
    """
    daemon_threads = True

    def __init__(self, address, handler, context: ssl.SSLContext):
        self.ssl_context = context
        super().__init__(address, handler)

    def finish_request(self, request, client_address):
        request.settimeout(CONNECTION_TIMEOUT_SECONDS)
        try:
            tls_sock = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            return  # Failed/aborted handshake: drop quietly, keep serving.
        try:
            self.RequestHandlerClass(tls_sock, client_address, self)
        except OSError:
            pass  # Client vanished or timed out mid-request.
        finally:
            tls_sock.close()


def make_server_context(certfile: str, keyfile: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_NO_COMPRESSION
    ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
    return ctx


def main():
    bind = validate_private_bind(TLS_BIND)
    if len(TOKEN) < 24 or len(DEVICE_TOKEN) < 24:
        raise SystemExit("Missing strong Bridge or device token")
    if hmac.compare_digest(TOKEN, DEVICE_TOKEN):
        raise SystemExit("Device token must differ from loopback Bridge token")
    if not TLS_CERT or not TLS_KEY:
        raise SystemExit("Missing TLS certificate/key configuration")
    if not Path(TLS_CERT).is_file() or not Path(TLS_KEY).is_file():
        raise SystemExit("TLS certificate or key not found")
    if not 1 <= TLS_PORT <= 65535 or not 1 <= LOCAL_PORT <= 65535:
        raise SystemExit("Invalid port")

    server = TlsHTTPServer((bind, TLS_PORT), Handler,
                           make_server_context(TLS_CERT, TLS_KEY))
    print(f"Hermes Touch TLS: https://{bind}:{TLS_PORT} (status + quick chat)", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
