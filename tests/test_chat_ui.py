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
    "\nstatic void buildVoicePage(", 1,
)[0]
VOICE = FIRMWARE.split("static void buildVoicePage(lv_obj_t *p) {", 1)[1].split(
    "\n// Read aggregate audio level only;", 1,
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

    def test_chat_all_widgets_fit_in_landscape(self):
        # Layout on 480x320: page content y=80..319 with 240px height.
        for x, y, w, h in (
            (10, 67, 460, 78),
            (10, 157, 348, 48),
            (368, 157, 102, 48),
        ):
            with self.subTest(rect=(x, y, w, h)):
                self.assertLessEqual(x + w, 480)
                self.assertLessEqual(y + h, 240)
        self.assertIn("lv_obj_set_pos(chatHistory, 10, 67)", CHAT)
        self.assertIn("lv_obj_set_size(chatHistory, 460, 78)", CHAT)
        self.assertIn("lv_obj_set_pos(chatInput, 10, 157)", CHAT)
        self.assertIn("lv_obj_set_pos(chatSend, 368, 157)", CHAT)
        self.assertIn("lv_obj_set_size(chatSend, 102, 48)", CHAT)

    def test_composer_is_visually_disabled_not_white(self):
        self.assertIn("lv_obj_set_style_bg_color(chatInput, lv_color_hex(0x24374D)", CHAT)
        self.assertIn("LV_PART_MAIN | LV_STATE_DISABLED", CHAT)
        self.assertIn("lv_obj_set_style_bg_color(chatSend, lv_color_hex(0x20334C)", CHAT)

    def test_voice_meter_is_only_on_dedicated_voice_tab(self):
        self.assertIn("chatMicBar = lv_bar_create(micCard)", VOICE)
        self.assertIn("lv_bar_set_range(chatMicBar, 0, 100)", VOICE)
        self.assertIn('"MIC: AUS (nur lokal)"', VOICE)
        self.assertIn('"MIC: STARTET (lokal)"', VOICE)
        self.assertNotIn("micLevelI2S", VOICE)
        self.assertNotIn("chatMicBar", CHAT)
        self.assertNotIn("onPttTouch", CHAT)
        self.assertNotIn("chatSpeakerButton", CHAT)

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
