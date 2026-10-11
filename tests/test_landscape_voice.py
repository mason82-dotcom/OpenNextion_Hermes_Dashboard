"""v0.8.4: physical 480x320 landscape, separate speech tab and bounded
local speaker test, including actual native C++ touch and PCM math tests.

Source-contract tests do NOT certify physical CST826 touch orientation:
that requires a deliberate hardware flash and corner-button trial.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch/HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")
SPK = (SKETCH.parent / "SpeakerToneWorker.h").read_text(encoding="utf-8")
PCM = (SKETCH.parent / "SpeakerPcmTest.h").read_text(encoding="utf-8")
TOUCH = (SKETCH.parent / "LandscapeTouch.h").read_text(encoding="utf-8")
BRIDGE = (SKETCH.parent / "TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
    "\n// SPRACHE is a separate", 1,
)[0]
VOICE = FIRMWARE.split("static void buildVoicePage(lv_obj_t *p) {", 1)[1].split(
    "\n// Read aggregate audio level only;", 1,
)[0]
NAV = FIRMWARE.split("static void buildUi() {", 1)[1].split(
    "\nstatic void updateLocalSystem()", 1,
)[0]


class LandscapeAndVoiceTab(unittest.TestCase):
    def test_landscape_version_and_runtime_dimensions(self):
        self.assertIn('Hermes Touch v0.8.4 (candidate)', FIRMWARE)
        self.assertIn('gfx->setRotation(1)', FIRMWARE)
        self.assertIn('SCREEN_W = LCD_V_RES', FIRMWARE)
        self.assertIn('SCREEN_H = LCD_H_RES', FIRMWARE)
        self.assertIn('SCREEN_W * BUF_LINES', FIRMWARE)
        self.assertIn('dispDrv.hor_res = gfx->width()', FIRMWARE)
        self.assertIn('dispDrv.ver_res = gfx->height()', FIRMWARE)

    def test_touch_rotation_not_a_simple_clamp(self):
        self.assertIn('#include "LandscapeTouch.h"', FIRMWARE)
        self.assertIn('mapNativeTouchToLandscape(', FIRMWARE)
        self.assertIn('point.x, point.y, LCD_H_RES, LCD_V_RES', FIRMWARE)
        self.assertIn('nativeHeight - 1 - py', TOUCH)
        self.assertIn('static_cast<int16_t>(px)', TOUCH)

    def test_five_distinct_landscape_tabs(self):
        self.assertIn('PAGE_COUNT = 5', FIRMWARE)
        self.assertIn('VOICE_PAGE = 4', FIRMWARE)
        self.assertIn('{"STATUS", "GRAPH", "SYSTEM", "CHAT", "SPRACHE"}', NAV)
        self.assertIn('pages[i] = makePage(screen)', NAV)
        self.assertIn('buildChatPage(pages[3])', NAV)
        self.assertIn('buildVoicePage(pages[VOICE_PAGE])', NAV)
        self.assertIn('lv_obj_set_pos(navBtns[i], 5 + i * 95, 39)', NAV)
        self.assertIn('lv_obj_set_size(navBtns[i], 90, 35)', NAV)
        # five 90px navigation buttons, separated by 5px, fit in 480px.
        self.assertLessEqual(5 + 4 * 95 + 90, 480)
        self.assertLessEqual(39 + 35, 80)

    def test_ptt_cannot_remain_held_when_leaving_voice(self):
        self.assertIn('if (page != VOICE_PAGE) micPttSetHeld(false)', FIRMWARE)
        self.assertIn('code == LV_EVENT_PRESSED && activePage == VOICE_PAGE', FIRMWARE)
        self.assertIn('code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST', FIRMWARE)
        self.assertIn('micPttSetHeld(false)', FIRMWARE)

    def test_voice_has_mic_ptt_pcm_speaker_volume_and_stop(self):
        for token in ('chatPttButton = lv_btn_create(p)',
                      'chatMicBar = lv_bar_create(micCard)',
                      'chatDiagPcm = label(diag,',
                      'chatDiagPsram = label(diag,',
                      'chatSpeakerButton = lv_btn_create(spk)',
                      'chatSpeakerStop = lv_btn_create(spk)',
                      'chatSpeakerVolume = lv_slider_create(spk)',
                      'lv_slider_set_range(chatSpeakerVolume, 0, 100)',
                      'lv_obj_add_state(chatSpeakerVolume, LV_STATE_DISABLED)'):
            self.assertIn(token, VOICE)

    def test_voice_widgets_fit_page_height_240_and_width_480(self):
        # Fixed surfaces and controls in content coordinates y=0..239.
        for x, y, w, h in ((10, 49, 190, 39),
                           (10, 94, 460, 32),
                           (10, 134, 282, 101),
                           (300, 134, 170, 101)):
            with self.subTest(rect=(x, y, w, h)):
                self.assertLessEqual(x + w, 480)
                self.assertLessEqual(y + h, 240)
        self.assertIn('lv_obj_set_pos(chatPttButton, 10, 49)', VOICE)

    def test_chat_remains_strictly_text_only_and_disabled(self):
        self.assertIn('lv_obj_add_state(chatInput, LV_STATE_DISABLED)', CHAT)
        self.assertIn('lv_obj_add_state(chatSend, LV_STATE_DISABLED)', CHAT)
        self.assertNotIn('lv_obj_add_event_cb(chatSend', CHAT)
        self.assertNotIn('lv_keyboard_create(', CHAT)
        for forbidden in ('chatPttButton', 'chatSpeakerButton', 'chatMicBar',
                          'chatDiagPcm', 'onPttTouch', 'speakerToneRequest'):
            self.assertNotIn(forbidden, CHAT)
        self.assertNotIn('lv_textarea_create(', VOICE)

    def test_speaker_volume_caps_previous_test_amplitude(self):
        self.assertIn('SPK_TEST_MAX_AMPLITUDE = 2500', PCM)
        self.assertIn('speakerClampLevel', PCM)
        self.assertIn('speakerLevelAmplitude', PCM)
        self.assertIn('speakerRenderLocalTestTone', PCM)
        self.assertIn('speakerToneRequest(speakerVolumePct)', FIRMWARE)
        self.assertIn('speakerToneVolume.store(boundedVolume', SPK)
        self.assertIn('speakerRenderLocalTestTone(', SPK)

    def test_stop_is_worker_signal_without_direct_i2c_or_lvgl(self):
        self.assertIn('speakerToneRequestStop();', FIRMWARE)
        self.assertIn('std::atomic<bool> speakerToneStop', SPK)
        self.assertIn('speakerToneStop.load(std::memory_order_acquire)', SPK)
        self.assertIn('SpeakerTonePhase::STOPPED', SPK)
        self.assertIn('speakerAmpSet(false)', FIRMWARE)
        self.assertNotIn('Wire.', SPK)
        self.assertNotIn('lv_', SPK)

    def test_read_only_https_and_no_audio_transport(self):
        self.assertIn('urlBase + "/v1/status"', BRIDGE)
        self.assertIn('client.setCACert(HT_CA_CERT)', BRIDGE)
        for forbidden in ('http.POST(', 'http.PUT(', 'http.PATCH(',
                          'http.DELETE(', 'setInsecure(', 'fwrite(', 'SD.open('):
            self.assertNotIn(forbidden, FIRMWARE + SPK + PCM + BRIDGE)
        self.assertNotIn('micLevelI2S.readBytes', SPK)

    @unittest.skipUnless(shutil.which("g++"), "host g++ not installed")
    def test_actual_cpp_rotation_and_local_pcm_volume(self):
        source = r"""
#include <cassert>
#include <cstdint>
#include "LandscapeTouch.h"
#include "SpeakerPcmTest.h"
int main() {
  auto p = mapNativeTouchToLandscape(0,0);
  assert(p.x == 479 && p.y == 0);
  p = mapNativeTouchToLandscape(319,0);
  assert(p.x == 479 && p.y == 319);
  p = mapNativeTouchToLandscape(0,479);
  assert(p.x == 0 && p.y == 0);
  p = mapNativeTouchToLandscape(319,479);
  assert(p.x == 0 && p.y == 319);
  p = mapNativeTouchToLandscape(-900,900);
  assert(p.x == 0 && p.y == 0);

  assert(speakerClampLevel(-1) == 0);
  assert(speakerClampLevel(0) == 0);
  assert(speakerClampLevel(50) == 50);
  assert(speakerClampLevel(999) == 100);
  assert(speakerLevelAmplitude(100) == 2500);
  assert(speakerLevelAmplitude(50) == 1250);
  assert(speakerLevelAmplitude(0) == 0);
  assert(speakerLevelAmplitude(250) == 2500);

  int16_t pcm[256];
  assert(speakerRenderLocalTestTone(pcm, 256, 0, 100) == 256);
  assert(pcm[0] == 0);
  int peak = 0;
  for (int i=0;i<256;i++) {
    const int v = pcm[i] < 0 ? -(int)pcm[i] : pcm[i];
    if (v > peak) peak = v;
  }
  assert(peak > 2000 && peak <= 2500);
  assert(speakerRenderLocalTestTone(pcm, 256, 0, 50) == 256);
  for (int i=0;i<256;i++) assert(pcm[i] <= 1250 && pcm[i] >= -1250);
  assert(speakerRenderLocalTestTone(pcm, 256, 0, 0) == 256);
  for (int i=0;i<256;i++) assert(pcm[i] == 0);
  assert(speakerRenderLocalTestTone(pcm, 256, 3999, 100) == 1);
  assert(pcm[0] == 0);
  assert(speakerRenderLocalTestTone(pcm, 256, 4000, 100) == 0);
  assert(speakerRenderLocalTestTone(nullptr, 256, 0, 100) == 0);
  return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="voice-landscape-") as work:
            executable = Path(work) / "audio_test"
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-pedantic",
                 "-I", str(SKETCH.parent), "-x", "c++", "-", "-o", str(executable)],
                input=source, text=True, check=True, timeout=30,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run([str(executable)], check=True, timeout=10,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
