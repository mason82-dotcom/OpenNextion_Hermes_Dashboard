"""Quick-command chat: whitelist, limits and sanitizing (no Hermes needed)."""
import importlib.util
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

os.environ.setdefault("HERMES_TOUCH_TOKEN", "test-token-12345678901234567890")
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ht_bridge_chat", ROOT / "bridge/hermes_touch_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
spec = importlib.util.spec_from_file_location("ht_tls_chat", ROOT / "bridge/tls_status_server.py")
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)

PROMPTS = [{"id": "pi_status", "label": "PI-STATUS", "prompt": "Wie geht es dem Pi?"},
           {"id": "witz", "label": "WITZ", "prompt": "Ein Witz bitte."}]


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def wait_state(chat, timeout=2.0):
    end = time.monotonic() + timeout
    while chat.state()["state"] == "running" and time.monotonic() < end:
        time.sleep(0.01)
    return chat.state()


class PromptFileTests(unittest.TestCase):
    def load(self, payload):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
            return bridge.load_chat_prompts(path)

    def test_example_file_is_valid(self):
        prompts, reason = bridge.load_chat_prompts(ROOT / "deploy/chat-prompts.example.json")
        self.assertEqual(reason, "ok")
        self.assertTrue(1 <= len(prompts) <= bridge.CHAT_MAX_PROMPTS)

    def test_missing_file_disables_chat(self):
        self.assertEqual(bridge.load_chat_prompts(Path("/nonexistent/x.json")),
                         ([], "no_prompt_file"))

    def test_any_invalid_entry_disables_whole_list(self):
        good = {"id": "a", "label": "A", "prompt": "x"}
        for bad in (
            {"id": "Bad-ID", "label": "A", "prompt": "x"},
            {"id": "b", "label": "Umlaut ä", "prompt": "x"},
            {"id": "b", "label": "VIEL ZU LANGES LABEL", "prompt": "x"},
            {"id": "b", "label": "B", "prompt": "   "},
            {"id": "a", "label": "Doppelt", "prompt": "x"},
            {"id": "b", "label": "B", "prompt": "x", "vary": "ja"},
        ):
            with self.subTest(bad=bad):
                self.assertEqual(self.load({"prompts": [good, bad]}), ([], "invalid_prompt_file"))
        self.assertEqual(self.load({"prompts": [good] * 7})[1], "invalid_prompt_file")
        self.assertEqual(self.load("not json")[1], "invalid_prompt_file")

    def test_api_key_read_from_hermes_env_without_other_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("OTHER_KEY=nope\nAPI_SERVER_KEY='secret-value'\n")
            self.assertEqual(bridge.read_hermes_api_key(env), "secret-value")
            self.assertEqual(bridge.read_hermes_api_key(Path(tmp) / "missing"), "")


class DisplayTextTests(unittest.TestCase):
    def test_umlauts_markdown_and_non_ascii_removed(self):
        text = bridge.display_text("## Übersicht\n**Temperatur:** 52 °C 🔥\n* Größe [Link](http://x)")
        self.assertEqual(text, "Uebersicht\nTemperatur: 52 Grad C\n- Groesse Link")
        self.assertTrue(all(ch == "\n" or 32 <= ord(ch) < 127 for ch in text))

    def test_length_limit(self):
        text = bridge.display_text("a " * 1000)
        self.assertLessEqual(len(text), bridge.CHAT_ANSWER_MAX)
        self.assertTrue(text.endswith("..."))


class QuickChatTests(unittest.TestCase):
    def make(self, runner, key="k" * 30, prompts=PROMPTS):
        self.clock = Clock()
        return bridge.QuickChat(prompts, "ok", key, clock=self.clock, runner=runner)

    def test_only_whitelisted_prompt_text_reaches_hermes(self):
        seen = []
        chat = self.make(lambda prompt, key: seen.append(prompt) or "Alles gut.")
        self.assertEqual(chat.ask("pi_status"), (202, {"ok": True, "job": 1}))
        state = wait_state(chat)
        self.assertEqual(seen, ["Wie geht es dem Pi?"])
        self.assertEqual((state["state"], state["answer"], state["prompt_id"]),
                         ("done", "Alles gut.", "pi_status"))
        self.assertEqual(chat.ask("rm -rf /")[0], 404)

    def test_vary_prompts_avoid_repeating_recent_answers(self):
        prompts = [{"id": "witz", "label": "WITZ", "prompt": "Ein Witz.", "vary": True},
                   {"id": "pi_status", "label": "PI", "prompt": "Status?", "vary": False}]
        seen, answers = [], iter(f"Witz {n}" for n in range(1, 20))
        chat = self.make(lambda prompt, key: seen.append(prompt) or next(answers), prompts=prompts)
        for _ in range(7):
            chat.ask("witz")
            wait_state(chat)
            self.clock.now += bridge.CHAT_MIN_INTERVAL_S
        self.assertTrue(seen[0].startswith("Ein Witz.\n\n(Variante "))
        self.assertNotIn("bereits gegeben", seen[0])
        self.assertIn("- Witz 1", seen[1])
        # Only the last CHAT_VARY_MEMORY answers are kept and sent back.
        self.assertNotIn("- Witz 1\n", seen[6] + "\n")
        self.assertIn("- Witz 2", seen[6])
        self.assertIn("- Witz 6", seen[6])
        chat.ask("pi_status")
        wait_state(chat)
        self.assertEqual(seen[-1], "Status?")  # non-vary prompts stay identical

    def test_busy_and_rate_limits(self):
        gate = threading.Event()
        chat = self.make(lambda prompt, key: gate.wait(2) and "ok")
        self.assertEqual(chat.ask("witz")[0], 202)
        self.assertEqual(chat.ask("witz"), (409, {"ok": False, "error": "busy"}))
        gate.set()
        wait_state(chat)
        self.assertEqual(chat.ask("witz")[1]["error"], "rate_limited")
        self.clock.now += bridge.CHAT_MIN_INTERVAL_S
        self.assertEqual(chat.ask("witz")[0], 202)
        wait_state(chat)
        for _ in range(bridge.CHAT_MAX_PER_HOUR):
            self.clock.now += bridge.CHAT_MIN_INTERVAL_S
            chat.ask("witz")
            wait_state(chat)
        self.clock.now += bridge.CHAT_MIN_INTERVAL_S
        self.assertEqual(chat.ask("witz")[0], 429)

    def test_disabled_without_prompts_or_key(self):
        self.assertEqual(self.make(lambda p, k: "x", prompts=[]).ask("witz")[0], 403)
        chat = self.make(lambda p, k: "x", key="")
        self.assertEqual((chat.enabled, chat.reason), (False, "no_api_key"))
        self.assertEqual(chat.ask("witz")[0], 403)

    def test_upstream_errors_are_codes_not_details(self):
        cases = (
            (HTTPError("u", 401, "secret detail", {}, None), "auth"),
            (HTTPError("u", 500, "secret detail", {}, None), "upstream"),
            (URLError(TimeoutError()), "timeout"),
            (RuntimeError("secret detail"), "upstream"),
        )
        for exc, code in cases:
            with self.subTest(code=code):
                def boom(prompt, key, exc=exc): raise exc
                chat = self.make(boom)
                chat.ask("witz")
                state = wait_state(chat)
                self.assertEqual((state["state"], state["error"], state["answer"]),
                                 ("error", code, ""))
                self.assertNotIn("secret", json.dumps(state))

    def test_hermes_request_shape(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n): return b'{"choices":[{"message":{"content":"Hallo"}}]}'
        with patch.object(bridge, "urlopen", return_value=Reply()) as opened:
            self.assertEqual(bridge.ask_hermes("Frage", "key-123"), "Hallo")
        req = opened.call_args.args[0]
        self.assertTrue(req.full_url.endswith("/v1/chat/completions"))
        self.assertEqual(req.get_header("Authorization"), "Bearer key-123")
        body = json.loads(req.data)
        self.assertEqual((body["model"], body["stream"]), ("hermes-agent", False))
        self.assertTrue(body["messages"][0]["content"].startswith("Frage"))


class BridgeHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, token=True):
        headers = {"X-Hermes-Touch-Token": bridge.TOKEN} if token else {}
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = Request(self.base + path, data=data, headers=headers,
                      method="POST" if data is not None else "GET")
        try:
            with urlopen(req, timeout=3) as r:
                return r.status, json.load(r)
        except HTTPError as e:
            return e.code, json.load(e)

    def test_endpoints(self):
        chat = bridge.QuickChat(PROMPTS, "ok", "k" * 30, runner=lambda p, k: "Antwort")
        with patch.object(bridge, "quick_chat", chat):
            code, data = self.call("/v1/chat/prompts")
            self.assertEqual(code, 200)
            self.assertEqual(data["prompts"], [{"id": "pi_status", "label": "PI-STATUS"},
                                               {"id": "witz", "label": "WITZ"}])
            self.assertNotIn("Wie geht es", json.dumps(data))  # prompt text stays on the Pi
            self.assertEqual(self.call("/v1/chat/ask", {"prompt_id": "witz"}, token=False)[0], 401)
            self.assertEqual(self.call("/v1/chat/ask", {"prompt_id": "witz", "text": "x"})[0], 400)
            self.assertEqual(self.call("/v1/chat/ask", b"x" * 300)[0], 400)
            self.assertEqual(self.call("/v1/chat/ask", {"prompt_id": "witz"})[0], 202)
            wait_state(chat)
            code, data = self.call("/v1/chat/state")
            self.assertEqual((code, data["state"], data["answer"]), (200, "done", "Antwort"))
            self.assertEqual(self.call("/v1/chat/other", {"prompt_id": "witz"})[0], 403)


class TlsChatTests(unittest.TestCase):
    def handler(self, path, body=b"", token=None, method="POST"):
        h = tls.Handler.__new__(tls.Handler)
        h.path = path
        h.headers = {"X-Hermes-Touch-Token": token or tls.DEVICE_TOKEN,
                     "Content-Length": str(len(body))}
        import io
        h.rfile = io.BytesIO(body)
        h.sent = []
        h.respond = lambda code, payload: h.sent.append((code, payload))
        getattr(h, "do_" + method)()
        return h.sent[0]

    def test_post_forwards_only_reserialized_id(self):
        with patch.object(tls, "DEVICE_TOKEN", "d" * 30), \
             patch.object(tls, "fetch_loopback", return_value=(202, b'{"ok":true,"job":7}')) as fwd:
            self.assertEqual(self.handler("/v1/chat/ask", b'{ "prompt_id" : "witz" }', "d" * 30),
                             (202, {"ok": True, "job": 7}))
        self.assertEqual(fwd.call_args.args, ("/v1/chat/ask", b'{"prompt_id": "witz"}'))

    def test_post_rejects_free_text_and_other_paths(self):
        with patch.object(tls, "DEVICE_TOKEN", "d" * 30), \
             patch.object(tls, "fetch_loopback", side_effect=AssertionError("must not forward")):
            for body in (b'{"prompt_id":"witz","text":"rm -rf"}', b'{"prompt_id":"WITZ"}',
                         b'{"message":"hi"}', b"x" * 300, b""):
                with self.subTest(body=body[:20]):
                    self.assertEqual(self.handler("/v1/chat/ask", body, "d" * 30)[0], 400)
            self.assertEqual(self.handler("/v1/chat/ask", b'{"prompt_id":"witz"}', "x" * 30)[0], 401)
            self.assertEqual(self.handler("/v1/status", b"{}", "d" * 30)[0], 405)
            self.assertEqual(self.handler("/v1/chat/ask?x=1", b"{}", "d" * 30)[0], 405)

    def test_bridge_refusals_relayed_without_details(self):
        with patch.object(tls, "DEVICE_TOKEN", "d" * 30):
            for code, error in tls.ASK_RELAYED.items():
                with patch.object(tls, "fetch_loopback", return_value=(code, b"")):
                    self.assertEqual(self.handler("/v1/chat/ask", b'{"prompt_id":"witz"}', "d" * 30),
                                     (code, {"ok": False, "error": error}))
            with patch.object(tls, "fetch_loopback", return_value=(500, b"trace")):
                self.assertEqual(self.handler("/v1/chat/ask", b'{"prompt_id":"witz"}', "d" * 30)[0], 503)

    def test_chat_gets_are_exact_paths(self):
        self.assertEqual(tls.GET_PATHS, {"/v1/status", "/v1/chat/prompts", "/v1/chat/state"})
        with patch.object(tls, "DEVICE_TOKEN", "d" * 30), \
             patch.object(tls, "fetch_loopback", return_value=(200, b'{"ok":true,"state":"idle"}')):
            self.assertEqual(self.handler("/v1/chat/state", token="d" * 30, method="GET"),
                             (200, {"ok": True, "state": "idle"}))
            self.assertEqual(self.handler("/v1/chat/state?x", token="d" * 30, method="GET")[0], 404)


if __name__ == "__main__":
    unittest.main()
