"""Static contracts for the opt-in quick-command CHAT tab on the ESP32."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch"
FIRMWARE = (SKETCH / "HermesTouch.ino").read_text(encoding="utf-8")
WORKER = (SKETCH / "TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = (SKETCH / "ChatWorker.h").read_text(encoding="utf-8")
EXAMPLE = (SKETCH / "Config.h.example").read_text(encoding="utf-8")
PAGE = FIRMWARE.split("static void buildQuickChatPage(lv_obj_t *p) {", 1)[1].split(
    "\nstatic void updateQuickChatUi(", 1)[0]


class QuickChatFirmwareTests(unittest.TestCase):
    def test_off_by_default_and_requires_connected_mode(self):
        self.assertIn("#define HT_CHAT_QUICK_ENABLED 0", EXAMPLE)
        self.assertIn("#ifndef HT_CHAT_QUICK_ENABLED\n#define HT_CHAT_QUICK_ENABLED 0", FIRMWARE)
        self.assertIn("#if HT_CHAT_QUICK_ENABLED && HT_DEMO_MODE\n#error", FIRMWARE)
        self.assertIn("#if HT_CHAT_QUICK_ENABLED\n#include \"ChatWorker.h\"", WORKER)
        # Without the opt-in the locked preview page is built unchanged.
        self.assertIn("#else\n  buildChatPage(pages[3]);\n#endif", FIRMWARE)

    def test_device_sends_only_whitelisted_prompt_id(self):
        posts = re.findall(r"chatHttp\(\"([^\"]+)\", (\w+)", CHAT)
        self.assertEqual(sorted(set(posts)), [("/v1/chat/ask", "body"),
                                              ("/v1/chat/prompts", "nullptr"),
                                              ("/v1/chat/state", "nullptr")])
        self.assertIn('"{\\"prompt_id\\":\\"%s\\"}", s.promptIds[requested]', CHAT)
        self.assertEqual(CHAT.count("http.POST("), 1)
        for forbidden in ("lv_keyboard_create(", "lv_textarea_create(", "HT_HERMES_API_KEY",
                          "Authorization", "/v1/chat/completions"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, CHAT + PAGE)

    def test_same_trust_rules_as_status_poll(self):
        self.assertIn("client.setCACert(HT_CA_CERT)", CHAT)
        self.assertIn('urlBase.startsWith("https://")', CHAT)
        self.assertIn("HTTPC_DISABLE_FOLLOW_REDIRECTS", CHAT)
        self.assertNotIn("setInsecure(", CHAT)

    def test_worker_never_touches_lvgl_and_gui_never_does_https(self):
        self.assertNotIn("lv_", CHAT.replace("CHAT_LABEL_LEN", ""))
        self.assertNotIn("chatHttp(", FIRMWARE)
        self.assertIn("chatService(snapshot.phase == TelemetryPhase::READY)", WORKER)
        self.assertIn("xSemaphoreTake(chatMutex, 0)", CHAT)  # zero-wait GUI read

    def test_answers_stay_in_ram(self):
        for forbidden in ("Preferences", "SPIFFS", "LittleFS", "nvs_", "SD.open(", "fopen("):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, CHAT + FIRMWARE)
        self.assertIn("static char chatLog[3072]", FIRMWARE)

    def test_buttons_only_from_pi_list_and_locked_while_busy(self):
        self.assertIn("lv_obj_add_flag(btn, LV_OBJ_FLAG_HIDDEN)", PAGE)
        self.assertIn("activePage != CHAT_PAGE", FIRMWARE)
        self.assertIn("if (locked) lv_obj_add_state(chatQuickButtons[i], LV_STATE_DISABLED)", FIRMWARE)
        self.assertIn("!chatIsBusy(s.phase)", CHAT)
        # Six buttons in a 3x2 grid plus the log box fit into the 480x240 page.
        self.assertIn("lv_obj_set_pos(btn, 10 + (i % 3) * 155, 26 + (i / 3) * 40)", PAGE)
        self.assertIn("lv_obj_set_pos(chatQuickLogBox, 10, 108)", PAGE)
        self.assertIn("lv_obj_set_size(chatQuickLogBox, 460, 128)", PAGE)


if __name__ == "__main__":
    unittest.main()
