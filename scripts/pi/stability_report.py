#!/usr/bin/env python3
"""Offline quality assessment of existing Hermes Touch Pi HTTPS monitor summaries.

No network, Pi service calls, credentials, writes, or ESP32 access.
Policy thresholds are advisory, not evidence of an ESP32 hardware endurance test.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STABILITY = ROOT / "build/stability"
MAX_JSON_BYTES = 1024 * 1024
MIN_TEST_MINUTES = 30.0
MIN_COVERAGE = 0.95
MAX_PASS_P95_MS = 250.0
MAX_FAIL_P95_MS = 1000.0


def _number(value, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Missing or invalid numeric field: {name}")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"Missing or invalid numeric field: {name}")
    return result


def _integer(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Missing or invalid count: {name}")
    return value


def validate(report: dict) -> dict:
    """Validate shape and internal accounting before assigning quality labels."""
    if not isinstance(report, dict):
        raise ValueError("Summary must be a JSON object")
    total = _integer(report.get("total"), "total")
    success = _integer(report.get("success"), "success")
    failed = _integer(report.get("failed"), "failed")
    longest = _integer(report.get("max_consecutive_failures"), "max_consecutive_failures")
    if not total or success + failed != total or longest > failed:
        raise ValueError("Inconsistent request totals or failure streak")
    counts = report.get("result_counts")
    if not isinstance(counts, dict) or not counts or any(
        not isinstance(key, str) or not key or isinstance(value, bool)
        or not isinstance(value, int) or value < 0
        for key, value in counts.items()
    ):
        raise ValueError("Invalid result counts")
    if sum(counts.values()) != total or counts.get("ok", 0) != success:
        raise ValueError("Result category counts do not match sample totals")
    pct = _number(report.get("success_pct"), "success_pct")
    if pct > 100 or abs(pct - round(success * 100 / total, 2)) > 0.02:
        raise ValueError("Success percentage does not match sample totals")
    for field in (
        "hermes_unhealthy_samples", "gateway_off_samples",
        "dashboard_unavailable_samples",
    ):
        if _integer(report.get(field), field) > success:
            raise ValueError(f"Out-of-range count: {field}")
    minutes = _number(report.get("configured_minutes"), "configured_minutes")
    interval = _number(report.get("interval_seconds"), "interval_seconds")
    elapsed = _number(report.get("actual_seconds"), "actual_seconds")
    if minutes == 0 or minutes > 240 or interval < 1 or elapsed > 241 * 60:
        raise ValueError("Unsupported test duration or sample interval")
    latency = report.get("latency_ms")
    if not isinstance(latency, dict):
        raise ValueError("Missing latency summary")
    if success:
        for key in ("avg", "p50", "p95", "max"):
            _number(latency.get(key), f"latency_ms.{key}")
        if latency["p50"] > latency["p95"] or latency["p95"] > latency["max"]:
            raise ValueError("Inconsistent latency percentiles")
    elif any(latency.get(key) is not None for key in ("avg", "p50", "p95", "max")):
        raise ValueError("Successful latency data without successful requests")
    return report


def evaluate(report: dict) -> tuple[str, list[str]]:
    """Offline policy: PASS = full run, no failures/unhealthy samples, p95 <=250 ms.

    WARN = some degradation; FAIL = repeated/sustained faults. A partial run
    remains INCOMPLETE even if its visible sample subset looks healthy.
    """
    report = validate(report)
    total = report["total"]
    failed = report["failed"]
    success = report["success"]
    elapsed = report["actual_seconds"]
    minutes = report["configured_minutes"]
    interval = report["interval_seconds"]
    expected = minutes * 60 / interval
    minimum = math.floor(MIN_COVERAGE * expected)
    reasons = []
    if minutes < MIN_TEST_MINUTES or elapsed < minutes * 60 * 0.98 or total < minimum:
        reasons.append(
            f"Unvollstaendig: {elapsed:.1f} s, {total} Messungen "
            f"(Ziel mindestens {minutes * 60 * 0.98:.0f} s und {minimum} Messungen)"
        )
        return "INCOMPLETE", reasons

    if failed:
        reasons.append(f"{failed} HTTPS-Fehler, laengste Fehlerfolge {report['max_consecutive_failures']}")
    for key, label in (
        ("hermes_unhealthy_samples", "Hermes unhealthy"),
        ("gateway_off_samples", "Gateway off"),
        ("dashboard_unavailable_samples", "Dashboard unavailable"),
    ):
        if report[key]:
            reasons.append(f"{label}: {report[key]} Messungen")
    if success and report["latency_ms"]["p95"] > MAX_PASS_P95_MS:
        reasons.append(f"p95 {report['latency_ms']['p95']:.1f} ms > {MAX_PASS_P95_MS:.0f} ms")

    critical = (
        failed / total > 0.01
        or report["max_consecutive_failures"] >= 3
        or any(report[key] >= 3 for key in (
            "hermes_unhealthy_samples", "gateway_off_samples",
            "dashboard_unavailable_samples",
        ))
        or (success and report["latency_ms"]["p95"] > MAX_FAIL_P95_MS)
    )
    if critical:
        return "FAIL", reasons or ["Kritische Qualitaetsgrenze ueberschritten"]
    if reasons:
        return "WARN", reasons
    return "PASS", ["Keine HTTPS-Fehler, keine negativen Hermes-Statuswerte; p95 im Zielbereich"]


def read_summary(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Missing, symlinked or oversized summary file")
    with path.open("r", encoding="utf-8") as handle:
        return validate(json.load(handle))


def latest_summary(folder: Path) -> Path:
    if not folder.is_dir():
        raise ValueError("No local stability monitor results found")
    candidates = sorted(
        (p for p in folder.glob("pi-tls-*.summary.json")
         if p.is_file() and not p.is_symlink()),
        reverse=True,
    )
    if not candidates:
        raise ValueError("No completed stability monitor summary found")
    return candidates[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Pi TLS stability assessment")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--latest", action="store_true",
                          help="read newest completed build/stability summary")
    selector.add_argument("--summary", type=Path,
                          help="explicit path to a completed .summary.json file")
    args = parser.parse_args(argv)
    try:
        path = latest_summary(STABILITY) if args.latest else args.summary
        report = read_summary(path)
        outcome, reasons = evaluate(report)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        print("REFUSED: missing, unreadable or inconsistent local monitor summary.", file=sys.stderr)
        return 2
    # Never print configuration values, untrusted JSON strings or response bodies.
    print("PI HTTPS STABILITY ASSESSMENT (read-only, Pi perspective)")
    print(f"Result: {outcome}")
    print(f"Measurements: {report['success']}/{report['total']} OK, "
          f"{report['failed']} failed | {report['success_pct']}%")
    print(f"Elapsed: {report['actual_seconds']} s | interval: {report['interval_seconds']} s")
    print(f"Failure streak: {report['max_consecutive_failures']}")
    print(f"Latency p95: {report['latency_ms']['p95']} ms")
    print(f"Hermes unhealthy: {report['hermes_unhealthy_samples']}; "
          f"gateway off: {report['gateway_off_samples']}; "
          f"dashboard unavailable: {report['dashboard_unavailable_samples']}")
    for reason in reasons:
        print(f"Reason: {reason}")
    print("LIMIT: Pi TLS checks do NOT measure ESP32 heap, PSRAM, resets or touch latency.")
    return {"PASS": 0, "WARN": 1, "FAIL": 1, "INCOMPLETE": 2}[outcome]


if __name__ == "__main__":
    raise SystemExit(main())
