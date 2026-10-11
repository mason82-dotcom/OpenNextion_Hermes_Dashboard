"""Source contracts for explicitly local, bounded and discard-only PTT.

These protect the architecture; the PDM driver and touch transitions still
require an actual Arduino build and a deliberate hardware trial.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = (ROOT / "firmware/HermesTouch/HermesTouch.ino").read_text(encoding="utf-8")
MIC = (ROOT / "firmware/HermesTouch/MicLevelWorker.h").read_text(encoding="utf-8")
WORKER = (ROOT / "firmware/HermesTouch/TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
    "\nstatic void updateMicUi()", 1,
)[0]


class TestLocalOnlyPushToTalk(unittest.TestCase):
    def test_version_and_default_mic_off(self):
        self.assertIn('label(screen, "v0.8.2 | ONX3248G035"', FIRMWARE)
        self.assertIn("#ifndef HT_MIC_TEST_ENABLED\n#define HT_MIC_TEST_ENABLED 0", FIRMWARE)
        self.assertIn('#if HT_MIC_TEST_ENABLED\n#include "MicLevelWorker.h"', FIRMWARE)

    def test_ptt_control_requires_explicit_microphone_opt_in(self):
        self.assertIn("chatPttButton = lv_btn_create(p)", CHAT)
        self.assertIn("lv_obj_add_event_cb(chatPttButton, onPttTouch, LV_EVENT_ALL", CHAT)
        self.assertIn("lv_obj_add_state(chatPttButton, LV_STATE_DISABLED)", CHAT)
        self.assertIn('"HALTEN: TEST"', CHAT)
        self.assertIn('"PTT: AUS"', CHAT)
        self.assertRegex(CHAT, r"#if HT_MIC_TEST_ENABLED\s+lv_obj_add_event_cb")

    def test_press_release_and_press_lost_are_handled(self):
        self.assertIn("static void onPttTouch(lv_event_t *event)", FIRMWARE)
        self.assertIn("code == LV_EVENT_PRESSED && activePage == 3", FIRMWARE)
        self.assertIn("code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST", FIRMWARE)
        self.assertIn("micPttSetHeld(true)", FIRMWARE)
        self.assertIn("micPttSetHeld(false)", FIRMWARE)

    def test_navigation_aborts_capture(self):
        self.assertIn("if (page != 3) micPttSetHeld(false)", FIRMWARE)
        self.assertIn("static void showPage(int page)", FIRMWARE)
        self.assertIn("showPage(i)", FIRMWARE)

    def test_strict_four_second_and_sample_size_bounds(self):
        self.assertIn("MIC_PTT_MAX_MS = 4000", MIC)
        self.assertIn("MIC_PTT_MAX_SAMPLES =", MIC)
        self.assertIn("MIC_SAMPLE_RATE * MIC_PTT_MAX_MS / 1000", MIC)
        self.assertIn("MIC_PTT_MAX_SAMPLES * sizeof(int16_t) == 128000", MIC)
        self.assertIn("(uint32_t)(startLoopMs - pttStartedMs) >= MIC_PTT_MAX_MS", MIC)
        self.assertIn("pttSamples >= MIC_PTT_MAX_SAMPLES", MIC)
        self.assertIn("pttSamples == MIC_PTT_MAX_SAMPLES", MIC)

    def test_audio_buffer_allocated_only_for_press_and_in_psram(self):
        self.assertIn("if (pttAudio == nullptr && held && pttArmed && failedReads == 0)", MIC)
        self.assertIn("heap_caps_malloc(", MIC)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", MIC)
        self.assertIn("if (pttAudio == nullptr)", MIC)
        self.assertIn("MicPttPhase::NO_PSRAM", MIC)
        self.assertNotIn("malloc(", MIC.replace("heap_caps_malloc(", ""))

    def test_pcm_secure_discard_and_no_auto_rearm_on_timeout(self):
        self.assertIn("volatile uint8_t *dest", MIC)
        self.assertIn("for (size_t i = 0; i < count; ++i) dest[i] = 0", MIC)
        self.assertIn("heap_caps_free(audio)", MIC)
        self.assertIn("micPttDiscard(pttAudio, pttSamples)", MIC)
        self.assertGreaterEqual(MIC.count("micPttDiscard(pttAudio, pttSamples)"), 3)
        self.assertIn("pttArmed = !held", MIC)
        self.assertIn("pttArmed = !heldNow", MIC)
        self.assertIn("pttArmed = false", MIC)
        self.assertIn("if (!held) pttArmed = true", MIC)
        self.assertIn("memset(pcm, 0, sizeof(pcm))", MIC)

    def test_only_counts_and_state_cross_worker_boundary(self):
        shared = MIC.split("struct MicLevelSnapshot {", 1)[1].split("};", 1)[0]
        for field in ("MicPttPhase pttPhase", "uint32_t pttDurationMs",
                      "uint32_t pttSamples"):
            self.assertIn(field, shared)
        self.assertNotIn("int16_t *", shared)
        self.assertNotIn("pcm[", shared)
        self.assertIn("std::atomic<bool> micPttHeld", MIC)
        self.assertIn("micPttHeld.store", MIC)
        self.assertIn("micPttHeld.load", MIC)
        self.assertIn("xSemaphoreTake(micLevelMutex, 0)", MIC)

    def test_ui_only_reads_state_and_never_pcm(self):
        self.assertIn("static void micLevelTask(void *)", MIC)
        self.assertIn("micLevelI2S.readBytes(", MIC)
        self.assertIn("micLevelRead(mic)", FIRMWARE)
        self.assertIn('lv_label_set_text(chatPttStatus, "PTT: VERWORFEN")', FIRMWARE)
        self.assertIn('lv_label_set_text(chatPttStatus, "PTT: LIMIT 4s")', FIRMWARE)
        self.assertIn('lv_label_set_text(chatPttStatus, "PTT: RAM FEHLT")', FIRMWARE)
        self.assertNotIn("micLevelI2S.readBytes", FIRMWARE)
        self.assertNotIn("lv_", MIC)

    def test_chat_send_stays_hard_disabled(self):
        self.assertIn("lv_obj_add_state(chatInput, LV_STATE_DISABLED)", CHAT)
        self.assertIn("lv_obj_add_state(chatSend, LV_STATE_DISABLED)", CHAT)
        self.assertNotIn("lv_obj_add_event_cb(chatSend", CHAT)
        self.assertNotIn("lv_keyboard_create(", FIRMWARE)
        self.assertIn('"CHAT IST DEAKTIVIERT"', CHAT)
        self.assertIn('"NUR VORSCHAU / KEIN VERSAND"', CHAT)

    def test_ptt_does_not_add_network_storage_or_agent_actions(self):
        for needle in ("http.POST(", "http.PUT(", "http.DELETE(", "http.PATCH(",
                       "setInsecure(", "WebServer", "AsyncWebServer"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, FIRMWARE + MIC + WORKER)
        for needle in ("#include <WiFi.h>", "WiFiClient", "HTTPClient",
                       "SD.open(", "fopen(", "fwrite(", "Serial.write("):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, MIC)
        self.assertIn('urlBase + "/v1/status"', WORKER)
        self.assertIn("http.GET()", WORKER)

    def test_layout_preserves_composer_and_navigation(self):
        for fragment in (
            "lv_obj_set_pos(chatPttButton, 10, 194)",
            "lv_obj_set_size(chatPttButton, 145, 39)",
            "lv_obj_t *micCard = card(p, 10, 236, 300, 32)",
            "lv_obj_set_pos(chatInput, 10, 273)",
            "lv_obj_set_pos(chatSend, 233, 273)",
            'label(p, "NUR VORSCHAU / KEIN VERSAND", 13, 328',
        ):
            self.assertIn(fragment, CHAT)


if __name__ == "__main__":
    unittest.main()
