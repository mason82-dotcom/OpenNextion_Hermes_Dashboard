"""Static safety and layout contracts for the disabled Hermes Chat UI shell.

No Hermes messages, credentials or transports are needed to run these checks.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = (ROOT / "firmware/HermesTouch/HermesTouch.ino").read_text(encoding="utf-8")
WORKER = (ROOT / "firmware/HermesTouch/TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
    "\nstatic void buildUi()", 1,
)[0]


class TestChatUiShell(unittest.TestCase):
    def test_chat_remains_visibly_disabled(self):
        self.assertIn('"CHAT IST DEAKTIVIERT"', CHAT)
        self.assertIn('"NUR VORSCHAU / KEIN VERSAND"', CHAT)
        self.assertIn('"Keine Agent-Befehle oder"', CHAT)

    def test_scrollable_transcript_shell_and_empty_state(self):
        self.assertIn("lv_obj_t *chatHistory = lv_obj_create(p)", CHAT)
        self.assertIn("lv_obj_set_scroll_dir(chatHistory, LV_DIR_VER)", CHAT)
        self.assertIn('"NOCH KEIN CHATVERLAUF"', CHAT)
        self.assertNotIn("Beispiel-Nachricht", CHAT)

    def test_composer_textarea_is_hard_disabled(self):
        self.assertIn("lv_obj_t *chatInput = lv_textarea_create(p)", CHAT)
        self.assertIn("lv_textarea_set_one_line(chatInput, true)", CHAT)
        self.assertIn("lv_obj_add_state(chatInput, LV_STATE_DISABLED)", CHAT)
        self.assertNotIn("lv_textarea_set_text(chatInput,", CHAT)
        self.assertNotIn("lv_keyboard_create(", CHAT)

    def test_send_control_has_no_callback_and_is_disabled(self):
        self.assertIn("lv_obj_t *chatSend = lv_btn_create(p)", CHAT)
        self.assertIn("lv_obj_add_state(chatSend, LV_STATE_DISABLED)", CHAT)
        self.assertNotIn("lv_obj_add_event_cb(chatSend", CHAT)
        self.assertNotIn("lv_event_send(chatSend", CHAT)

    def test_chat_all_widgets_fit_before_navigation(self):
        # Page inner coordinate area: 320 x 352, bottom navigation follows.
        for x, y, w, h in (
            (10, 64, 300, 125),
            (10, 194, 145, 39),
            (10, 236, 300, 32),
            (10, 273, 215, 48),
            (233, 273, 77, 48),
        ):
            with self.subTest(rect=(x, y, w, h)):
                self.assertIn(f"lv_obj_set_pos(", CHAT)
                self.assertLessEqual(x + w, 320)
                self.assertLessEqual(y + h, 352)
        self.assertIn("lv_obj_set_pos(chatHistory, 10, 64)", CHAT)
        self.assertIn("lv_obj_set_size(chatHistory, 300, 125)", CHAT)
        self.assertIn("lv_obj_t *micCard = card(p, 10, 236, 300, 32)", CHAT)
        self.assertIn("lv_obj_set_pos(chatInput, 10, 273)", CHAT)
        self.assertIn("lv_obj_set_pos(chatSend, 233, 273)", CHAT)
        self.assertIn("lv_obj_set_size(chatSend, 77, 48)", CHAT)

    def test_composer_is_visually_disabled_not_white(self):
        self.assertIn("lv_obj_set_style_bg_color(chatInput, lv_color_hex(0x24374D)", CHAT)
        self.assertIn("LV_PART_MAIN | LV_STATE_DISABLED", CHAT)
        self.assertIn("lv_obj_set_style_bg_color(chatSend, lv_color_hex(0x20334C)", CHAT)

    def test_microphone_meter_only_shows_local_aggregate(self):
        self.assertIn("chatMicBar = lv_bar_create(micCard)", CHAT)
        self.assertIn("lv_bar_set_range(chatMicBar, 0, 100)", CHAT)
        self.assertIn('"MIC: AUS (nur lokal)"', CHAT)
        self.assertIn('"MIC: STARTET (lokal)"', CHAT)
        self.assertNotIn("micLevelI2S", CHAT)

    def test_no_new_network_write_surface(self):
        self.assertIn('urlBase + "/v1/status"', WORKER)
        self.assertIn("http.GET()", WORKER)
        for forbidden in (
            "http.POST(", "http.PUT(", "http.DELETE(", "http.PATCH(",
            "HTTPClient", "WiFiClient", "setInsecure(", "HERMES_API_KEY",
        ):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, CHAT)
        self.assertNotIn("http.POST(", WORKER)
        self.assertNotIn("http.PUT(", WORKER)
        self.assertNotIn("http.DELETE(", WORKER)


if __name__ == "__main__":
    unittest.main()
