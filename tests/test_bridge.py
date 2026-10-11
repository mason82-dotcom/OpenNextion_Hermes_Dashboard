import importlib.util
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ["HERMES_TOUCH_TOKEN"] = "test-token-12345678901234567890"
source = Path(__file__).resolve().parents[1] / "bridge" / "hermes_touch_bridge.py"
spec = importlib.util.spec_from_file_location("ht_bridge", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)

    def req(self, path="/v1/status", token=None, method="GET"):
        headers = {"X-Hermes-Touch-Token": token} if token else {}
        try:
            with urlopen(Request(self.base + path, headers=headers, method=method), timeout=3) as resp:
                return resp.status, json.load(resp)
        except HTTPError as e:
            return e.code, json.load(e)

    def test_no_token(self):
        code, data = self.req()
        self.assertEqual((code, data["error"]), (401, "unauthorized"))

    def test_invalid_token(self):
        code, _ = self.req(token="invalid")
        self.assertEqual(code, 401)

    def test_status(self):
        with patch.object(module, "health_snapshot", return_value={
            "dashboard_reachable": False,
            "dashboard_status_available": False,
            "api_reachable": True,
            "api_healthy": True,
        }):
            code, data = self.req(token=module.TOKEN)
        self.assertEqual(code, 200)
        self.assertIn("system", data)
        self.assertEqual(data["schema_version"], 1)
        self.assertFalse(data["chat"]["enabled"])
        self.assertFalse(data["hermes"]["dashboard_reachable"])
        self.assertTrue(data["hermes"]["api_healthy"])

    def test_api_health_success(self):
        import io
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"ok"}'
        with patch.object(module, "urlopen", return_value=response) as open_mock:
            probe = module.api_health_probe()
        self.assertEqual(probe, {"api_reachable": True, "api_healthy": True})
        self.assertTrue(open_mock.call_args.args[0].full_url.endswith("/health"))

    def test_api_health_offline(self):
        from urllib.error import URLError
        with patch.object(module, "urlopen", side_effect=URLError("refused")):
            self.assertEqual(module.api_health_probe(),
                             {"api_reachable": False, "api_healthy": False})

    def test_api_health_http_error_is_reachable_but_unhealthy(self):
        from urllib.error import HTTPError
        error = HTTPError("http://127.0.0.1:8642/health", 503, "unavailable", {}, None)
        with patch.object(module, "urlopen", side_effect=error):
            self.assertEqual(module.api_health_probe(),
                             {"api_reachable": True, "api_healthy": False})

    def test_dashboard_success(self):
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.__enter__.return_value.status = 200
        reply.__enter__.return_value.read.return_value = (
            b'{"version":"1.0","gateway_running":true}')
        with patch.object(module, "urlopen", return_value=reply) as mocked:
            data = module.dashboard_probe()
        self.assertTrue(data["dashboard_reachable"])
        self.assertTrue(data["dashboard_status_available"])
        self.assertEqual(data["dashboard_reason"], "ok")
        self.assertTrue(data["gateway_running"])
        self.assertEqual(mocked.call_count, 1)

    def test_dashboard_status_timeout_health_ok(self):
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.__enter__.return_value.status = 200
        with patch.object(module, "urlopen",
                          side_effect=[TimeoutError(), reply]) as mocked:
            data = module.dashboard_probe()
        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(data["dashboard_reachable"])
        self.assertFalse(data["dashboard_status_available"])
        self.assertEqual(data["dashboard_reason"], "timeout")

    def test_dashboard_http_401(self):
        from io import BytesIO
        error = HTTPError("http://127.0.0.1:9119/api/status",
                          401, "Unauthorized", None, BytesIO(b""))
        with patch.object(module, "urlopen", side_effect=error):
            data = module.dashboard_probe()
        self.assertTrue(data["dashboard_reachable"])
        self.assertFalse(data["dashboard_status_available"])
        self.assertEqual(data["dashboard_reason"], "http_401")

    def test_dashboard_bad_json(self):
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.__enter__.return_value.status = 200
        reply.__enter__.return_value.read.return_value = b"<html>login</html>"
        with patch.object(module, "urlopen", return_value=reply):
            data = module.dashboard_probe()
        self.assertTrue(data["dashboard_reachable"])
        self.assertFalse(data["dashboard_status_available"])
        self.assertEqual(data["dashboard_reason"], "invalid_json")

    def test_health_cache_is_fresh_only_within_45_seconds(self):
        cached = {
            **module._probe_data, "api_reachable": True, "api_healthy": True,
            "dashboard_reachable": True, "dashboard_status_available": True,
            "dashboard_reason": "ok", "gateway_running": True,
        }
        with patch.object(module, "_probe_data", cached), \
             patch.object(module, "_last_probe_monotonic", 100.0), \
             patch.object(module, "_last_probe_success", 1234567890):
            fresh = module.health_snapshot(now_monotonic=144.9)
            self.assertTrue(fresh["probe_fresh"])
            self.assertTrue(fresh["api_healthy"])
            self.assertTrue(fresh["gateway_running"])
            self.assertAlmostEqual(fresh["probe_age_s"], 44.9)
            self.assertEqual(fresh["last_probe_success"], 1234567890)

            expired = module.health_snapshot(now_monotonic=145.1)
            self.assertFalse(expired["probe_fresh"])
            self.assertFalse(expired["api_healthy"])
            self.assertFalse(expired["dashboard_status_available"])
            self.assertIsNone(expired["gateway_running"])
            self.assertEqual(expired["dashboard_reason"], "stale_cache")
            self.assertEqual(expired["last_probe_success"], 1234567890)

    def test_pending_health_cache_never_reports_healthy(self):
        cached = {**module._probe_data,
                  "api_healthy": True, "gateway_running": True,
                  "dashboard_status_available": True}
        with patch.object(module, "_probe_data", cached), \
             patch.object(module, "_last_probe_monotonic", None), \
             patch.object(module, "_last_probe_success", None):
            result = module.health_snapshot(now_monotonic=100)
            self.assertFalse(result["probe_fresh"])
            self.assertIsNone(result["probe_age_s"])
            self.assertIsNone(result["last_probe_success"])
            self.assertFalse(result["api_healthy"])
            self.assertIsNone(result["gateway_running"])
            self.assertEqual(result["dashboard_reason"], "pending")

    def test_completed_probe_cycle_publishes_timestamp_and_fresh_health(self):
        dashboard = {
            "dashboard_reachable": True, "dashboard_status_available": True,
            "dashboard_reason": "ok", "gateway_running": True,
        }
        api = {"api_reachable": True, "api_healthy": True}
        with patch.object(module, "_probe_data", dict(module._probe_data)), \
             patch.object(module, "_last_probe_monotonic", None), \
             patch.object(module, "_last_probe_success", None), \
             patch.object(module, "dashboard_probe", return_value=dashboard), \
             patch.object(module, "api_health_probe", return_value=api):
            module.probe_cycle()
            snapshot = module.health_snapshot()
            self.assertTrue(snapshot["probe_fresh"])
            self.assertTrue(snapshot["api_healthy"])
            self.assertTrue(snapshot["gateway_running"])
            self.assertLess(snapshot["probe_age_s"], 1)
            self.assertIsInstance(snapshot["last_probe_success"], int)

    def test_failed_probe_cycle_cannot_refresh_stale_health(self):
        cached = {**module._probe_data,
                  "api_healthy": True, "gateway_running": True}
        with patch.object(module, "_probe_data", cached), \
             patch.object(module, "_last_probe_monotonic", 100.0), \
             patch.object(module, "_last_probe_success", 1234567890), \
             patch.object(module, "dashboard_probe", side_effect=RuntimeError("probe crash")):
            with self.assertRaises(RuntimeError):
                module.probe_cycle()
            snapshot = module.health_snapshot(now_monotonic=146.0)
            self.assertFalse(snapshot["probe_fresh"])
            self.assertFalse(snapshot["api_healthy"])
            self.assertIsNone(snapshot["gateway_running"])
            self.assertEqual(snapshot["probe_age_s"], 46.0)

    def test_http_status_route_marks_expired_cache_unhealthy(self):
        cached = {
            **module._probe_data, "api_healthy": True,
            "dashboard_status_available": True, "gateway_running": True,
        }
        with patch.object(module, "_probe_data", cached), \
             patch.object(module, "_last_probe_monotonic", -100000.0), \
             patch.object(module, "_last_probe_success", 1234567890):
            code, payload = self.req(token=module.TOKEN)
        self.assertEqual(code, 200)
        self.assertFalse(payload["hermes"]["probe_fresh"])
        self.assertFalse(payload["hermes"]["api_healthy"])
        self.assertFalse(payload["hermes"]["dashboard_status_available"])
        self.assertIsNone(payload["hermes"]["gateway_running"])
        self.assertEqual(payload["hermes"]["dashboard_reason"], "stale_cache")

    def test_requests_never_call_upstream(self):
        with patch.object(module, "dashboard_probe",
                          side_effect=AssertionError("blocking upstream")), \
             patch.object(module, "api_health_probe",
                          side_effect=AssertionError("blocking upstream")):
            code, data = self.req(token=module.TOKEN)
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])

    def test_admin_absent(self):
        code, data = self.req(path="/v1/admin", token=module.TOKEN)
        self.assertEqual((code, data["error"]), (404, "not_found"))

    def test_post_forbidden(self):
        code, data = self.req(path="/v1/chat", token=module.TOKEN, method="POST")
        self.assertEqual((code, data["error"]), (403, "read_only"))


if __name__ == "__main__":
    unittest.main()
