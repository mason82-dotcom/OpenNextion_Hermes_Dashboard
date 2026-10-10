"""Integration checks for the TLS-only read-only facade; no Pi network needed."""
import importlib.util
import io
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

os.environ["HERMES_TOUCH_TOKEN"] = "tls-unit-test-token-abcdefghijklmnopqr"
SOURCE = Path(__file__).resolve().parents[1] / "bridge" / "tls_status_server.py"
spec = importlib.util.spec_from_file_location("hermes_touch_tls", SOURCE)
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)


class TestTlsConfig(unittest.TestCase):
    def test_bind_is_lan_only(self):
        self.assertEqual(tls.validate_private_bind("192.168.2.11"), "192.168.2.11")
        for ip in ("", "0.0.0.0", "127.0.0.1", "::1", "8.8.8.8", "fe80::1"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                tls.validate_private_bind(ip)


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL is required for temporary TLS test certs")
class TestTlsStatusHandler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="hermes-touch-tls-")
        p = Path(cls.temp.name)
        ca_key = p / "ca.key"
        ca_crt = p / "ca.crt"
        server_key = p / "server.key"
        csr = p / "server.csr"
        crt = p / "server.crt"
        ext = p / "server.ext"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec",
             "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
             "-days", "2", "-keyout", str(ca_key), "-out", str(ca_crt),
             "-subj", "/CN=Hermes Touch Unit Test CA",
             "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["openssl", "req", "-newkey", "ec",
             "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
             "-keyout", str(server_key), "-out", str(csr),
             "-subj", "/CN=Hermes Touch TLS Test"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ext.write_text("subjectAltName=IP:127.0.0.1\n"
                       "keyUsage=critical,digitalSignature\n"
                       "extendedKeyUsage=serverAuth\n")
        subprocess.run(
            ["openssl", "x509", "-req", "-in", str(csr),
             "-CA", str(ca_crt), "-CAkey", str(ca_key),
             "-CAcreateserial", "-days", "2",
             "-extfile", str(ext), "-out", str(crt)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), tls.Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(server_key))
        cls.httpd.socket = ctx.wrap_socket(cls.httpd.socket, server_side=True)
        cls.port = cls.httpd.server_port
        cls.context = ssl.create_default_context(cafile=str(ca_crt))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def req(self, path="/v1/status", token=None, method="GET", hostname="127.0.0.1", ctx=None):
        header = {"X-Hermes-Touch-Token": token} if token is not None else {}
        request = Request(f"https://{hostname}:{self.port}{path}", headers=header, method=method)
        try:
            with urlopen(request, context=ctx or self.context, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def test_missing_token_rejected(self):
        self.assertEqual(self.req()[0], 401)

    def test_write_denied(self):
        self.assertEqual(self.req(method="POST", token=tls.TOKEN)[0], 405)

    def test_non_status_path_denied(self):
        self.assertEqual(self.req(path="/v1/status?x=1", token=tls.TOKEN)[0], 404)
        self.assertEqual(self.req(path="/v1/chat", token=tls.TOKEN)[0], 404)

    def test_verified_read_only_status(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return None
            def read(self, _n): return b'{"ok":true,"schema_version":1,"chat":{"enabled":false}}'
        with patch.object(tls, "urlopen", return_value=Response()) as forwarded:
            code, payload = self.req(token=tls.TOKEN)
        self.assertEqual(code, 200)
        self.assertIs(payload["ok"], True)
        self.assertIs(payload["chat"]["enabled"], False)
        self.assertTrue(forwarded.call_args.args[0].full_url.startswith("http://127.0.0.1:"))

    def test_tls_cannot_use_untrusted_ca(self):
        with self.assertRaises(URLError):
            self.req(token=tls.TOKEN, ctx=ssl.create_default_context())

    def test_tls_requires_matching_san(self):
        with self.assertRaises(URLError):
            self.req(token=tls.TOKEN, hostname="localhost")

    def test_unavailable_local_bridge_is_503(self):
        with patch.object(tls, "urlopen", side_effect=URLError("connection refused")):
            code, doc = self.req(token=tls.TOKEN)
        self.assertEqual(code, 503)
        self.assertEqual(doc["error"], "loopback_bridge_unavailable")


if __name__ == "__main__":
    unittest.main()
