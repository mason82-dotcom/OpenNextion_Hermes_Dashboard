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
