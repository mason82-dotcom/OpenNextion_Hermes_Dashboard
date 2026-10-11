"""Local NS4168 speaker tone source contracts (v0.8.3 candidate).

These are architectural tests, not proof of sound on physical hardware.
Speaker audio is a fixed test tone only and never contains microphone PCM.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch/HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")
SPK = (SKETCH.parent / "SpeakerToneWorker.h").read_text(encoding="utf-8")
MIC = (SKETCH.parent / "MicLevelWorker.h").read_text(encoding="utf-8")
BOARD = (SKETCH.parent / "BoardConfig.h").read_text(encoding="utf-8")
CONFIG = (SKETCH.parent / "Config.h.example").read_text(encoding="utf-8")
WORKER = (SKETCH.parent / "TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
    "\nstatic void updateMicUi()", 1,
)[0]


class SpeakerOutputContracts(unittest.TestCase):
    def test_manufacturer_speaker_pins_and_amp_control(self):
        for pin, number in (("SPEAKER_BCLK_PIN", 14),
                            ("SPEAKER_DATA_PIN", 15),
                            ("SPEAKER_WS_PIN", 16),
                            ("PCF8574_PIN_I2S_CTRL", 0)):
            self.assertRegex(BOARD, rf"{pin}\s*=\s*{number};")
        self.assertIn("PCF8574_PIN_LCD_RST = 6", BOARD)
        self.assertIn("PCF8574_ADDR = 0x38", BOARD)

    def test_output_is_independently_opt_in_and_default_off(self):
        self.assertIn("#define HT_SPEAKER_TEST_ENABLED 0", CONFIG)
        self.assertIn("#ifndef HT_SPEAKER_TEST_ENABLED\n#define HT_SPEAKER_TEST_ENABLED 0", FIRMWARE)
        self.assertIn("#if HT_SPEAKER_TEST_ENABLED\n#include \"SpeakerToneWorker.h\"", FIRMWARE)
        self.assertIn('#error "HT_SPEAKER_TEST_ENABLED must be 0 or 1"', FIRMWARE)
        self.assertIn("#define HT_MIC_TEST_ENABLED 0", CONFIG)

    def test_manufacturer_i2s1_tx_uses_msb_mono_16k(self):
        self.assertIn("#include <driver/i2s_std.h>", SPK)
        self.assertIn("I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER)", SPK)
        self.assertIn("I2S_STD_CLK_DEFAULT_CONFIG(SPK_SAMPLE_RATE)", SPK)
        self.assertIn("I2S_STD_MSB_SLOT_DEFAULT_CONFIG(", SPK)
        self.assertIn("I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO", SPK)
        self.assertIn("SPK_SAMPLE_RATE = 16000", SPK)
        for pin in ("SPEAKER_BCLK_PIN", "SPEAKER_DATA_PIN", "SPEAKER_WS_PIN"):
            self.assertIn(pin, SPK)

    def test_protects_microphone_auto_i2s_acquisition(self):
        self.assertIn("micLevelRead(micForSpeaker)", FIRMWARE)
        self.assertIn("micForSpeaker.ready || micForSpeaker.failed", FIRMWARE)
        self.assertIn("if (!speakerToneStartAttempted && expanderAvailable)", FIRMWARE)
        self.assertIn("speakerToneStartAttempted = true", FIRMWARE)
        self.assertIn("micLevelI2S.begin(I2S_MODE_PDM_RX", MIC)

    def test_amp_is_muted_before_LCD_reset_and_shared_pc8574_is_shadowed(self):
        self.assertIn("static uint8_t expanderShadow = 0xFF", FIRMWARE)
        self.assertIn("expanderShadow = (uint8_t)(0xFF & ~(1U << PCF8574_PIN_I2S_CTRL))", FIRMWARE)
        self.assertIn("expanderSetPin(PCF8574_PIN_LCD_RST, false)", FIRMWARE)
        self.assertIn("expanderSetPin(PCF8574_PIN_LCD_RST, true)", FIRMWARE)
        self.assertIn("expanderSetPin(PCF8574_PIN_I2S_CTRL, enabled)", FIRMWARE)
        self.assertIn("speakerAmpSet(false)", FIRMWARE)

    def test_expander_owned_by_main_loop_no_worker_wire_or_lvgl(self):
        self.assertIn("static void updateSpeakerUi()", FIRMWARE)
        self.assertIn("updateSpeakerUi(); // amp via main thread", FIRMWARE)
        self.assertNotIn("Wire.", SPK)
        self.assertNotIn("expander.", SPK)
        self.assertNotIn("lv_", SPK)
        self.assertIn("speakerToneAmpAcknowledged(true)", FIRMWARE)
        self.assertIn("speakerToneAmpAcknowledged(false)", FIRMWARE)

    def test_tone_requires_amp_handshake_and_has_hard_deadline(self):
        self.assertIn("SpeakerTonePhase::WAIT_AMP", SPK)
        self.assertIn("speakerToneAmpAck.load", SPK)
        self.assertIn("SPK_AMP_WAIT_MS = 250", SPK)
        self.assertIn("SPK_PLAY_DEADLINE_MS = 700", SPK)
        self.assertIn("speakerTonePublish(SpeakerTonePhase::WAIT_MUTE", SPK)
        self.assertIn("SpeakerTonePhase::ERROR", SPK)

    def test_tone_is_short_and_quiet_with_pop_fade(self):
        self.assertIn("SPK_TONE_MS = 250", SPK)
        self.assertIn("SPK_AMPLITUDE = 2500", SPK)
        self.assertIn("SPK_TONE_HZ = 660", SPK)
        self.assertIn("const uint32_t fadeSamples = SPK_SAMPLE_RATE / 100", SPK)
        self.assertIn("sinf(angle)", SPK)
        self.assertIn("memset(pcm, 0, sizeof(pcm))", SPK)

    def test_rapid_clicks_cannot_queue_a_second_tone(self):
        self.assertIn("speakerToneShared.phase = SpeakerTonePhase::QUEUED", SPK)
        self.assertIn("speakerTonePending.store(true, std::memory_order_release)", SPK)
        self.assertIn("xSemaphoreTake(speakerToneMutex, 0)", SPK)
        self.assertIn("phase != SpeakerTonePhase::READY && phase != SpeakerTonePhase::DONE", SPK)
        self.assertIn("speakerTonePending.exchange(false, std::memory_order_acq_rel)", SPK)

    def test_scrollable_ui_button_is_disabled_when_output_not_opted_in(self):
        self.assertIn("chatSpeakerButton = lv_btn_create(chatHistory)", CHAT)
        self.assertIn('"TESTTON"', CHAT)
        self.assertIn("lv_obj_add_event_cb(chatSpeakerButton, onSpeakerTest, LV_EVENT_CLICKED", CHAT)
        self.assertIn("lv_obj_add_state(chatSpeakerButton, LV_STATE_DISABLED)", CHAT)
        button = CHAT.split("chatSpeakerButton = lv_btn_create(chatHistory)", 1)[1].split(
            "lv_obj_t *speakerText =", 1,
        )[0]
        enabled = button.split("#if HT_SPEAKER_TEST_ENABLED", 1)[1].split("#else", 1)[0]
        disabled = button.split("#else", 1)[1].split("#endif", 1)[0]
        self.assertIn("lv_obj_add_event_cb(chatSpeakerButton", enabled)
        self.assertNotIn("lv_obj_add_event_cb(chatSpeakerButton", disabled)
        self.assertIn("LV_STATE_DISABLED", disabled)
        self.assertIn("lv_obj_set_scroll_dir(chatHistory, LV_DIR_VER)", CHAT)

    def test_worker_has_no_recorder_network_or_agent_transport(self):
        for forbidden in ("WiFiClient", "HTTPClient", "http.POST(",
                          "setInsecure(", "SD.open(", "fopen(", "fwrite(",
                          "i2s_channel_read(", "Serial.write(", "lv_"):
            with self.subTest(needle=forbidden):
                self.assertNotIn(forbidden, SPK)
        self.assertNotIn("speaker", WORKER.lower())
        self.assertIn('urlBase + "/v1/status"', WORKER)

    def test_mic_chat_readonly_and_connected_tls_unchanged(self):
        self.assertIn("lv_obj_add_state(chatInput, LV_STATE_DISABLED)", CHAT)
        self.assertIn("lv_obj_add_state(chatSend, LV_STATE_DISABLED)", CHAT)
        self.assertNotIn("lv_obj_add_event_cb(chatSend", CHAT)
        self.assertIn('"CHAT IST DEAKTIVIERT"', CHAT)
        self.assertIn('"NUR VORSCHAU / KEIN VERSAND"', CHAT)
        self.assertIn("client.setCACert(HT_CA_CERT)", WORKER)
        self.assertIn("HTTPC_DISABLE_FOLLOW_REDIRECTS", WORKER)
        for forbidden in ("http.POST(", "http.PUT(", "http.DELETE(",
                          "http.PATCH(", "setInsecure("):
            self.assertNotIn(forbidden, FIRMWARE + SPK + MIC + WORKER)


if __name__ == "__main__":
    unittest.main()
