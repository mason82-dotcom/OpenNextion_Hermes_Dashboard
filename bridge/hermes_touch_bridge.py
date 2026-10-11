#!/usr/bin/env python3
"""Hermes Touch status bridge. Python >=3.10, stdlib only.

Does not modify Hermes config, systemd services, credentials or memory.
Status is read-only. The optional quick-command chat accepts only the ID of
a prompt from the local whitelist file; free text never reaches Hermes.
Use trusted local access only; HTTP token headers are not encryption.
"""
from __future__ import annotations

import hmac
import json
import os
import re
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
_ROOT = Path(__file__).resolve().parents[1]
CHAT_PROMPTS_FILE = Path(os.environ.get(
    "HERMES_TOUCH_CHAT_PROMPTS", str(_ROOT / "config" / "chat-prompts.json")))
# The Hermes API key stays on the Pi. Read from Hermes' own env file so that
# no second copy of the secret exists; never sent to the ESP32.
HERMES_ENV_FILE = Path(os.environ.get(
    "HERMES_API_KEY_FILE", str(Path.home() / ".hermes" / ".env")))


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


# ---------------------------------------------------------------------------
# Quick-command chat. The device sends only a whitelisted prompt ID; the
# prompt text lives exclusively in the local config/chat-prompts.json.
# One job at a time, rate limited, answers sanitized to short ASCII text.
# ---------------------------------------------------------------------------
CHAT_MAX_PROMPTS = 6
CHAT_ID_RE = re.compile(r"^[a-z0-9_]{1,16}$")
CHAT_LABEL_MAX = 14
CHAT_PROMPT_MAX = 2000
CHAT_ANSWER_MAX = 700
CHAT_MIN_INTERVAL_S = 15.0
CHAT_MAX_PER_HOUR = 20
CHAT_UPSTREAM_TIMEOUT_S = 180.0
CHAT_BODY_MAX = 256
CHAT_STYLE_SUFFIX = (
    "\n\nAntworte auf Deutsch, kurz (hoechstens 5 Saetze), als reiner Text "
    "ohne Markdown, Tabellen oder Emojis. Die Antwort erscheint auf einem "
    "kleinen Display.")
_UMLAUTS = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss", "–": "-", "—": "-", "„": '"', "“": '"', "”": '"',
    "‚": "'", "‘": "'", "’": "'", "…": "...", "°": " Grad ", "€": "EUR",
    "\u00a0": " ",
})


def load_chat_prompts(path: Path):
    """Return (prompts, reason). Any invalid entry disables the chat."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "no_prompt_file"
    except (OSError, ValueError, UnicodeDecodeError):
        return [], "invalid_prompt_file"
    items = data.get("prompts") if isinstance(data, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= CHAT_MAX_PROMPTS:
        return [], "invalid_prompt_file"
    prompts, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            return [], "invalid_prompt_file"
        pid, label, prompt = item.get("id"), item.get("label"), item.get("prompt")
        if (not isinstance(pid, str) or not CHAT_ID_RE.match(pid) or pid in seen
                or not isinstance(label, str)
                or not 1 <= len(label) <= CHAT_LABEL_MAX
                or not all(32 <= ord(ch) < 127 for ch in label)
                or not isinstance(prompt, str)
                or not 1 <= len(prompt.strip()) <= CHAT_PROMPT_MAX):
            return [], "invalid_prompt_file"
        seen.add(pid)
        prompts.append({"id": pid, "label": label, "prompt": prompt.strip()})
    return prompts, "ok"


def read_hermes_api_key(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == "API_SERVER_KEY":
                return value.strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def display_text(text: str, limit: int = CHAT_ANSWER_MAX) -> str:
    """Reduce an agent answer to short ASCII the LVGL default font can show."""
    text = text.translate(_UMLAUTS)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)   # links -> label
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)   # headings
    text = re.sub(r"^\s*[*+]\s+", "- ", text, flags=re.M)        # bullets
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = "".join(ch if ch == "\n" or 32 <= ord(ch) < 127 else " " for ch in text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > limit:
        text = text[:limit - 3].rstrip() + "..."
    return text


def ask_hermes(prompt: str, api_key: str) -> str:
    """Single stateless, non-streaming agent run via the local Hermes API."""
    body = json.dumps({
        "model": "hermes-agent",
        "stream": False,
        "messages": [{"role": "user", "content": prompt + CHAT_STYLE_SUFFIX}],
    }).encode("utf-8")
    req = Request(API_URL + "/v1/chat/completions", data=body, method="POST", headers={
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=CHAT_UPSTREAM_TIMEOUT_S) as response:
        raw = response.read(262145)
    if len(raw) > 262144:
        raise ValueError("response_too_large")
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty_answer")
    return content


class QuickChat:
    """Thread-safe single-job state machine; holds only the latest answer."""

    def __init__(self, prompts, reason, api_key, *, clock=time.monotonic, runner=None):
        self.prompts = {p["id"]: p for p in prompts}
        self.order = [p["id"] for p in prompts]
        self.reason = reason
        self.enabled = bool(prompts) and bool(api_key)
        if prompts and not api_key:
            self.reason = "no_api_key"
        self._api_key = api_key
        self._clock = clock
        self._runner = runner or ask_hermes
        self._lock = threading.Lock()
        self._job = 0
        self._state = "idle"
        self._prompt_id = None
        self._answer = ""
        self._error = None
        self._started = None
        self._finished = None
        self._history = []  # monotonic start times within the last hour

    def prompt_list(self):
        return [{"id": pid, "label": self.prompts[pid]["label"]} for pid in self.order]

    def ask(self, prompt_id):
        """Return (http_status, payload). Starts the job in a worker thread."""
        if not self.enabled:
            return 403, {"ok": False, "error": "chat_disabled"}
        if prompt_id not in self.prompts:
            return 404, {"ok": False, "error": "unknown_prompt"}
        now = self._clock()
        with self._lock:
            if self._state == "running":
                return 409, {"ok": False, "error": "busy"}
            self._history = [t for t in self._history if now - t < 3600.0]
            if ((self._history and now - self._history[-1] < CHAT_MIN_INTERVAL_S)
                    or len(self._history) >= CHAT_MAX_PER_HOUR):
                return 429, {"ok": False, "error": "rate_limited"}
            self._history.append(now)
            self._job += 1
            job = self._job
            self._state, self._prompt_id = "running", prompt_id
            self._answer, self._error = "", None
            self._started, self._finished = now, None
        prompt = self.prompts[prompt_id]["prompt"]
        threading.Thread(target=self._run, args=(job, prompt_id, prompt), daemon=True).start()
        return 202, {"ok": True, "job": job}

    def _run(self, job, prompt_id, prompt):
        answer, error = "", None
        try:
            answer = display_text(self._runner(prompt, self._api_key))
            if not answer:
                error = "empty_answer"
        except HTTPError as exc:
            error = "auth" if exc.code in (401, 403) else "upstream"
        except (TimeoutError, socket.timeout):
            error = "timeout"
        except URLError as exc:
            error = ("timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout))
                     else "upstream")
        except Exception:
            error = "upstream"  # Never echo agent/upstream error details.
        with self._lock:
            if job != self._job:
                return
            self._state = "error" if error else "done"
            self._answer, self._error = ("", error) if error else (answer, None)
            self._finished = self._clock()
        print(f"chat job={job} prompt={prompt_id} result={error or 'ok'}", flush=True)

    def state(self):
        now = self._clock()
        with self._lock:
            end = self._finished if self._finished is not None else now
            return {
                "ok": True,
                "enabled": self.enabled,
                "state": self._state,
                "job": self._job,
                "prompt_id": self._prompt_id,
                "answer": self._answer,
                "error": self._error,
                "elapsed_s": round(end - self._started, 1) if self._started else None,
            }


def make_quick_chat():
    prompts, reason = load_chat_prompts(CHAT_PROMPTS_FILE)
    return QuickChat(prompts, reason, read_hermes_api_key(HERMES_ENV_FILE) if prompts else "")


quick_chat = QuickChat([], "not_loaded", "")


def status_payload():
    return {
        "ok": True,
        "schema_version": 1,
        "system": system_snapshot(),
        "hermes": health_snapshot(),
        "chat": {"enabled": quick_chat.enabled, "mode": "quick"},
    }


def read_prompt_id(handler):
    """Parse {"prompt_id": "<id>"} from a small JSON body; anything else -> None."""
    try:
        length = int(handler.headers.get("Content-Length", ""))
    except ValueError:
        return None
    if not 0 < length <= CHAT_BODY_MAX:
        return None
    try:
        data = json.loads(handler.rfile.read(length))
    except (ValueError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(data, dict) or set(data) != {"prompt_id"}:
        return None
    pid = data["prompt_id"]
    return pid if isinstance(pid, str) and CHAT_ID_RE.match(pid) else None


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
        path = urlsplit(self.path).path
        if not self.allowed():
            self.respond(401, {"error": "unauthorized"})
        elif path == "/v1/status":
            self.respond(200, status_payload())
        elif path == "/v1/chat/prompts":
            self.respond(200, {"ok": True, "enabled": quick_chat.enabled,
                               "reason": quick_chat.reason,
                               "prompts": quick_chat.prompt_list()})
        elif path == "/v1/chat/state":
            self.respond(200, quick_chat.state())
        else:
            self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if not self.allowed():
            self.respond(401, {"error": "unauthorized"})
        elif urlsplit(self.path).path != "/v1/chat/ask":
            self.respond(403, {"error": "read_only"})
        else:
            prompt_id = read_prompt_id(self)
            if prompt_id is None:
                self.respond(400, {"ok": False, "error": "bad_request"})
            else:
                self.respond(*quick_chat.ask(prompt_id))


def main():
    if len(TOKEN) < 24:
        raise SystemExit("HERMES_TOUCH_TOKEN must contain at least 24 characters")
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: HTTP transmits your token unencrypted. Use only trusted isolated LAN.")
    global quick_chat
    quick_chat = make_quick_chat()
    print(f"Quick chat: {'ENABLED' if quick_chat.enabled else 'off'} "
          f"({quick_chat.reason}, {len(quick_chat.order)} prompts)", flush=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    stop_event = threading.Event()
    worker = threading.Thread(target=probe_worker, args=(stop_event,), daemon=True)
    worker.start()
    print(f"Hermes Touch: http://{HOST}:{PORT} (status read-only)", flush=True)
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
