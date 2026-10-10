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
        with patch.object(module, "dashboard_probe", return_value={"dashboard_reachable": False, "version": None}):
            code, data = self.req(token=module.TOKEN)
        self.assertEqual(code, 200)
        self.assertIn("system", data)
        self.assertEqual(data["schema_version"], 1)
        self.assertFalse(data["chat"]["enabled"])
        self.assertFalse(data["hermes"]["dashboard_reachable"])

    def test_admin_absent(self):
        code, data = self.req(path="/v1/admin", token=module.TOKEN)
        self.assertEqual((code, data["error"]), (404, "not_found"))

    def test_post_forbidden(self):
        code, data = self.req(path="/v1/chat", token=module.TOKEN, method="POST")
        self.assertEqual((code, data["error"]), (403, "read_only"))


if __name__ == "__main__":
    unittest.main()
