"""Stability monitor tests: pure math + mocked HTTPS (never need Pi or tokens)."""
import importlib.util
import math
from pathlib import Path
import unittest
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / "scripts/pi/stability_monitor.py"
spec = importlib.util.spec_from_file_location("stability_monitor", SOURCE)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class TestStabilityMonitor(unittest.TestCase):
    def test_lan_ip_restriction(self):
        self.assertEqual(monitor.private_lan_address("192.168.178.63"), "192.168.178.63")
        for value in ("0.0.0.0", "127.0.0.1", "8.8.8.8", "100.98.97.84",
                      "172.8.0.1", "localhost", "::1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                monitor.private_lan_address(value)

    def test_read_only_bridge_schema_and_metrics(self):
        doc = {
            "ok": True, "schema_version": 1,
            "hermes": {"api_healthy": True, "dashboard_status_available": True,
                       "gateway_running": False},
            "system": {"cpu_temp_c": 52.2, "ram_used_pct": 63.4, "load1": 0.71},
        }
        self.assertEqual(monitor.status_fields(doc), {
            "api_healthy": True, "dashboard_available": True,
            "gateway_running": False, "cpu_temp_c": 52.2,
            "ram_used_pct": 63.4, "load1": 0.71,
        })

    def test_bad_status_denied(self):
        for data in (None, {}, {"ok": True, "schema_version": 123},
                     {"ok": False, "schema_version": 1},
                     {"ok": True, "schema_version": 1, "hermes": "bad", "system": {}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                monitor.status_fields(data)

    def test_invalid_numbers_do_not_become_metrics(self):
        doc = {
            "ok": True, "schema_version": 1, "hermes": {},
            "system": {"cpu_temp_c": float("nan"), "ram_used_pct": True, "load1": -1},
        }
        values = monitor.status_fields(doc)
        self.assertIsNone(values["cpu_temp_c"])
        self.assertIsNone(values["ram_used_pct"])
        self.assertIsNone(values["load1"])

    def test_summary_counts_and_percentile(self):
        rows = [
            {"result": "ok", "latency_ms": 12.0, "cpu_temp_c": 52.0,
             "ram_used_pct": 60.0, "load1": 0.4,
             "api_healthy": True, "gateway_running": True, "dashboard_available": True},
            {"result": "http_error", "latency_ms": 10, "http_code": 503},
            {"result": "http_error", "latency_ms": 12, "http_code": 503},
            {"result": "ok", "latency_ms": 24.0, "cpu_temp_c": 55.0,
             "ram_used_pct": 64.0, "load1": 1.0,
             "api_healthy": False, "gateway_running": False, "dashboard_available": False},
        ]
        result = monitor.summary(rows)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["success"], 2)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["success_pct"], 50.0)
        self.assertEqual(result["max_consecutive_failures"], 2)
        self.assertEqual(result["latency_ms"]["p50"], 12.0)
        self.assertEqual(result["latency_ms"]["p95"], 24.0)
        self.assertEqual(result["pi_metrics"]["cpu_temp_c"], {"min": 52.0, "max": 55.0})
        self.assertEqual(result["gateway_off_samples"], 1)
        self.assertEqual(result["hermes_unhealthy_samples"], 1)
        self.assertEqual(result["dashboard_unavailable_samples"], 1)

    def test_empty_summary(self):
        result = monitor.summary([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success_pct"], 0)
        self.assertIsNone(result["latency_ms"]["p95"])

    def test_probe_stores_safe_fields_not_token_or_payload(self):
        class FakeResponse:
            status = 200
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *unused): return False
            def read(self, length): return self.value
        payload = (
            b'{"ok":true,"schema_version":1,'
            b'"hermes":{"api_healthy":true},'
            b'"system":{"cpu_temp_c":52.1,"ram_used_pct":63,"load1":0.5},'
            b'"private_secret":"not-for-log"}'
        )
        fake = Mock()
        fake.open.return_value = FakeResponse(payload)
        token = "secret-do-not-save-or-log-1234567890"
        row = monitor.probe(fake, "https://192.168.178.63:8766/v1/status", token, 4.5)
        self.assertEqual(row["result"], "ok")
        self.assertEqual(row["http_code"], 200)
        self.assertEqual(row["cpu_temp_c"], 52.1)
        self.assertNotIn("private_secret", str(row))
        self.assertNotIn(token, str(row))
        request = fake.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(request.full_url.endswith("/v1/status"))
        self.assertIn(token, request.headers.values())

    def test_no_redirect_follows_token(self):
        self.assertIsNone(monitor.NoRedirect().redirect_request(
            None, None, 302, "moved", {}, "https://elsewhere.example/v1/status"))


if __name__ == "__main__":
    unittest.main()
