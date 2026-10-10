#!/usr/bin/env python3
"""Read-only, certificate-verified LAN stability monitor for Hermes Touch.

Measures the Pi TLS bridge (NOT the ESP32 heap or touch latency).
No credentials, HTTP response bodies, or raw error text go into logs.
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import os
from pathlib import Path
import ssl
import statistics
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[2]
FIELDS = (
    "utc", "result", "latency_ms", "http_code",
    "api_healthy", "dashboard_available", "gateway_running",
    "cpu_temp_c", "ram_used_pct", "load1",
)
LAN_RANGES = tuple(ipaddress.ip_network(x) for x in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def private_lan_address(address: str) -> str:
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not any(ip in network for network in LAN_RANGES):
        raise ValueError("Expected explicit private IPv4 address of Raspberry Pi")
    return str(ip)


def numeric_or_none(value, low: float, high: float):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or not low <= result <= high:
        return None
    return round(result, 3)


def status_fields(doc: dict) -> dict:
    if not isinstance(doc, dict) or doc.get("ok") is not True or doc.get("schema_version") != 1:
        raise ValueError("unsupported status payload")
    hermes = doc.get("hermes")
    system = doc.get("system")
    if not isinstance(hermes, dict) or not isinstance(system, dict):
        raise ValueError("missing bridge status data")
    return {
        "api_healthy": hermes.get("api_healthy") if isinstance(hermes.get("api_healthy"), bool) else None,
        "dashboard_available": (hermes.get("dashboard_status_available")
                                if isinstance(hermes.get("dashboard_status_available"), bool) else None),
        "gateway_running": (hermes.get("gateway_running")
                            if isinstance(hermes.get("gateway_running"), bool) else None),
        "cpu_temp_c": numeric_or_none(system.get("cpu_temp_c"), -20.0, 150.0),
        "ram_used_pct": numeric_or_none(system.get("ram_used_pct"), 0.0, 100.0),
        "load1": numeric_or_none(system.get("load1"), 0.0, 1000.0),
    }


def percentile(values: list[float], percent: int):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)], 1)


def summary(rows: list[dict]) -> dict:
    good = [row for row in rows if row["result"] == "ok"]
    durations = [float(row["latency_ms"]) for row in good]
    failure_streak = maximum = 0
    for row in rows:
        if row["result"] == "ok":
            failure_streak = 0
        else:
            failure_streak += 1
            maximum = max(maximum, failure_streak)
    counts = {}
    for row in rows:
        counts[row["result"]] = counts.get(row["result"], 0) + 1
    metrics = {}
    for key in ("cpu_temp_c", "ram_used_pct", "load1"):
        values = [float(row[key]) for row in good if row.get(key) is not None]
        metrics[key] = {"min": min(values), "max": max(values)} if values else None
    return {
        "total": len(rows),
        "success": len(good),
        "failed": len(rows) - len(good),
        "success_pct": round(100.0 * len(good) / len(rows), 2) if rows else 0,
        "max_consecutive_failures": maximum,
        "result_counts": counts,
        "latency_ms": {
            "avg": round(statistics.mean(durations), 1) if durations else None,
            "p50": percentile(durations, 50),
            "p95": percentile(durations, 95),
            "max": round(max(durations), 1) if durations else None,
        },
        "pi_metrics": metrics,
        "hermes_unhealthy_samples": sum(row.get("api_healthy") is False for row in good),
        "gateway_off_samples": sum(row.get("gateway_running") is False for row in good),
        "dashboard_unavailable_samples": sum(row.get("dashboard_available") is False for row in good),
    }


def make_client(ca_file: Path):
    context = ssl.create_default_context(cafile=str(ca_file))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    # No environment proxy. Never forward the device token on redirects.
    return build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())


def probe(opener, url: str, token: str, timeout: float) -> dict:
    request = Request(url, method="GET", headers={
        "X-Hermes-Touch-Token": token, "Accept": "application/json",
    })
    start = time.monotonic()
    row = {"result": "transport_error", "http_code": ""}
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(16385)
            if len(raw) > 16384:
                row["result"] = "oversize"
            else:
                row.update(status_fields(json.loads(raw)))
                row["result"] = "ok"
                row["http_code"] = response.status
    except HTTPError as error:
        # No exception text/body: may contain environment or credential details.
        row["result"] = "http_error"
        row["http_code"] = error.code
    except ssl.SSLError:
        row["result"] = "tls_error"
    except (URLError, TimeoutError, OSError):
        row["result"] = "transport_error"
    except (ValueError, UnicodeDecodeError, TypeError):
        row["result"] = "invalid_json"
    row["latency_ms"] = round((time.monotonic() - start) * 1000, 1)
    row["utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return row


def cli():
    parser = argparse.ArgumentParser(description="Read-only Hermes TLS LAN stability monitor")
    parser.add_argument("--minutes", type=float, default=30,
                        help="total duration in minutes (default: 30)")
    parser.add_argument("--interval", type=float, default=5,
                        help="start-to-start interval in seconds (default: 5)")
    parser.add_argument("--samples", type=int, default=None,
                        help="optional exact sample count for quick smoke tests")
    parser.add_argument("--timeout", type=float, default=4.5)
    args = parser.parse_args()
    if args.minutes <= 0 or args.minutes > 240 or args.interval < 1 or args.timeout < 1:
        parser.error("minutes must be 0–240, interval >= 1s and timeout >= 1s")
    if args.samples is not None and (args.samples < 1 or args.samples > 50000):
        parser.error("samples must be between 1 and 50000")
    return args


def run():
    args = cli()
    host = private_lan_address(os.environ["HERMES_TOUCH_TLS_BIND"])
    port = int(os.environ.get("HERMES_TOUCH_TLS_PORT", "8766"))
    token = os.environ.get("HERMES_TOUCH_DEVICE_TOKEN", "")
    if not 1 <= port <= 65535 or len(token) < 24:
        raise SystemExit("Missing valid TLS port or distinct device token")
    ca = ROOT / "config" / "pki" / "ca.crt"
    if not ca.is_file():
        raise SystemExit("Missing local public CA certificate")
    url = f"https://{host}:{port}/v1/status"
    client = make_client(ca)

    outdir = ROOT / "build" / "stability"
    outdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(outdir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csvpath = outdir / f"pi-tls-{stamp}.csv"
    jsonpath = outdir / f"pi-tls-{stamp}.summary.json"

    rows = []
    begin = time.monotonic()
    deadline = begin + args.minutes * 60
    next_tick = begin
    count = 0
    print(f"Pi HTTPS monitor: {host}:{port}, interval {args.interval:g} s")
    print("Only public system metrics; no tokens/passwords logged.")
    print(f"CSV: {csvpath}")
    fd = os.open(csvpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, FIELDS, extrasaction="ignore")
        writer.writeheader()
        try:
            while (args.samples is not None and count < args.samples) or (
                    args.samples is None and time.monotonic() < deadline):
                row = probe(client, url, token, args.timeout)
                writer.writerow(row)
                handle.flush()
                rows.append(row)
                count += 1
                if row["result"] != "ok":
                    print(f"Sample {count}: {row['result']}, HTTP {row['http_code'] or '-'}")
                elif count == 1 or count % max(1, math.ceil(60 / args.interval)) == 0:
                    print(f"Sample {count}: OK, {row['latency_ms']:.0f} ms")
                next_tick += args.interval
                until = next_tick - time.monotonic()
                if until > 0 and (args.samples is None or count < args.samples):
                    time.sleep(until)
        except KeyboardInterrupt:
            print("Stopped by user; reporting completed samples.")

    report = summary(rows)
    report["configured_minutes"] = args.minutes
    report["actual_seconds"] = round(time.monotonic() - begin, 1)
    report["interval_seconds"] = args.interval
    fd = os.open(jsonpath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print("\nPI HTTPS STABILITY SUMMARY (not ESP32 heap)")
    print(f"Requests: {report['total']}, success: {report['success']}, failed: {report['failed']}")
    print(f"Success rate: {report['success_pct']}% | max failure streak: {report['max_consecutive_failures']}")
    print(f"Latency ms: {report['latency_ms']}")
    print(f"Hermes unhealthy: {report['hermes_unhealthy_samples']}, gateway off: {report['gateway_off_samples']}")
    print(f"JSON: {jsonpath}")
    return 0 if rows and report["failed"] == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (KeyError, ValueError) as exc:
        # Never print the value of an environment variable or credential.
        raise SystemExit("Invalid local TLS monitor configuration") from None
