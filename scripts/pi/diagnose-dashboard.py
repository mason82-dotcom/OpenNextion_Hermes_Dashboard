#!/usr/bin/env python3
"""Safe read-only localhost dashboard diagnostic (no secrets displayed)."""
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:9119"
LIMIT = 65536


def check(path):
    started = time.monotonic()
    code, reason, json_type = None, "ok", "not-read"
    try:
        req = Request(BASE + path, headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as response:
            code = response.status
            body = response.read(LIMIT + 1)
        if len(body) > LIMIT:
            reason = "response_too_large"
        else:
            try:
                data = json.loads(body)
                json_type = "object" if isinstance(data, dict) else type(data).__name__
            except (ValueError, UnicodeDecodeError):
                reason = "invalid_json"
    except HTTPError as exc:
        code, reason = exc.code, f"http_{exc.code}"
    except (socket.timeout, TimeoutError):
        reason = "timeout"
    except URLError as exc:
        reason = "timeout" if isinstance(exc.reason, (socket.timeout, TimeoutError)) else "connection_error"
    except OSError:
        reason = "connection_error"
    elapsed_ms = int((time.monotonic() - started) * 1000)
    print(f"{path}: http={code if code is not None else '-'}, "
          f"elapsed_ms={elapsed_ms}, json={json_type}, reason={reason}")


if __name__ == "__main__":
    print("Hermes Dashboard localhost-only endpoint diagnosis (no secrets)")
    check("/api/health")
    check("/api/status")
