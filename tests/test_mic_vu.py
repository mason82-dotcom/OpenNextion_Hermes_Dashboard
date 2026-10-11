"""v0.8.1 microphone source contracts: no audio persistence or Hermes write path."""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch/HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")
MIC = (SKETCH.parent / "MicLevelWorker.h").read_text(encoding="utf-8")
BOARD = (SKETCH.parent / "BoardConfig.h").read_text(encoding="utf-8")
WORKER = (SKETCH.parent / "TelemetryWorker.h").read_text(encoding="utf-8")


class TestMicrophoneLevel(unittest.TestCase):
    def test_mic_opt_in_disabled_by_default(self):
        self.assertIn("#ifndef HT_MIC_TEST_ENABLED\n#define HT_MIC_TEST_ENABLED 0", FIRMWARE)
        self.assertIn('#error "HT_MIC_TEST_ENABLED must be 0 or 1"', FIRMWARE)
        self.assertIn('#if HT_MIC_TEST_ENABLED\n#include "MicLevelWorker.h"', FIRMWARE)
        self.assertIn("#if HT_MIC_TEST_ENABLED\n  // Explicit opt-in only.", FIRMWARE)

    def test_verified_board_pdm_pin_mapping(self):
        self.assertRegex(BOARD, r"MIC_PDM_CLK_PIN\s*=\s*19;")
        self.assertRegex(BOARD, r"MIC_PDM_DATA_PIN\s*=\s*20;")
        self.assertIn("micLevelI2S.setPinsPdmRx(MIC_PDM_CLK_PIN, MIC_PDM_DATA_PIN)", MIC)

    def test_pdm_mono_16k_16bit_sampling(self):
        self.assertIn("#include <ESP_I2S.h>", MIC)
        self.assertIn("MIC_SAMPLE_RATE = 16000", MIC)
        self.assertIn("I2S_MODE_PDM_RX, MIC_SAMPLE_RATE", MIC)
        self.assertIn("I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO", MIC)
        self.assertIn("micLevelI2S.setTimeout(MIC_SAMPLE_TIMEOUT_MS)", MIC)

    def test_pcm_only_in_worker_local_stack(self):
        self.assertIn("int16_t pcm[MIC_PCM_SAMPLES]", MIC)
        self.assertIn("micLevelI2S.readBytes(", MIC)
        self.assertIn("const size_t count = got / sizeof(int16_t)", MIC)
        self.assertIn("uint64_t energy = 0", MIC)
        self.assertIn("sqrtf(", MIC)
        self.assertNotIn("recordWAV", MIC + FIRMWARE)
        for forbidden in ("SD.open(", "fopen(", "fwrite(", "HTTPClient",
                          "WiFiClient", "http.POST(", "http.PUT(", "http.DELETE(",
                          "http.PATCH(", "WebServer", "AsyncWebServer"):
            with self.subTest(api=forbidden):
                self.assertNotIn(forbidden, MIC)

    def test_only_level_aggregate_crosses_mutex(self):
        self.assertIn("struct MicLevelSnapshot", MIC)
        self.assertIn("uint8_t levelPercent", MIC)
        self.assertIn("uint32_t lastSampleMs", MIC)
        self.assertNotIn("pcm[", MIC.split("struct MicLevelSnapshot", 1)[1].split("};", 1)[0])
        self.assertIn("xSemaphoreTake(micLevelMutex, 0)", MIC)
        self.assertIn("xSemaphoreGive(micLevelMutex)", MIC)

    def test_i2s_never_blocks_lvgl_loop(self):
        self.assertIn("static void micLevelTask(void *)", MIC)
        self.assertIn('xTaskCreate(\n      micLevelTask, "mic-vu", 4096', MIC)
        self.assertIn("static void updateMicUi()", FIRMWARE)
        self.assertIn("micLevelRead(mic)", FIRMWARE)
        self.assertNotIn("micLevelI2S.readBytes", FIRMWARE)
        self.assertNotIn("lv_", MIC)
        self.assertNotIn("gfx->", MIC)

    def test_error_and_stale_states_never_show_last_level_as_live(self):
        self.assertIn("mic.failed", FIRMWARE)
        self.assertIn("MIC_VALID_AGE_MS", FIRMWARE)
        self.assertIn("MIC: FEHLER (lokal)", FIRMWARE)
        self.assertIn("MIC: WARTE (lokal)", FIRMWARE)
        self.assertIn("lv_bar_set_value(chatMicBar, 0, LV_ANIM_OFF)", FIRMWARE)

    def test_existing_readonly_tls_transport_unchanged(self):
        self.assertIn('urlBase + "/v1/status"', WORKER)
        self.assertIn("client.setCACert(HT_CA_CERT)", WORKER)
        self.assertIn("HTTPC_DISABLE_FOLLOW_REDIRECTS", WORKER)
        for forbidden in ("http.POST(", "http.PUT(", "http.DELETE(", "http.PATCH("):
            self.assertNotIn(forbidden, MIC + FIRMWARE + WORKER)

    def test_disabled_controls_remain_unchanged(self):
        chat = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
            "\nstatic void updateMicUi()", 1,
        )[0]
        self.assertIn("lv_obj_add_state(chatInput, LV_STATE_DISABLED)", chat)
        self.assertIn("lv_obj_add_state(chatSend, LV_STATE_DISABLED)", chat)
        self.assertNotIn("lv_obj_add_event_cb(chatSend", chat)
        self.assertNotIn("lv_keyboard_create(", FIRMWARE)


if __name__ == "__main__":
    unittest.main()
