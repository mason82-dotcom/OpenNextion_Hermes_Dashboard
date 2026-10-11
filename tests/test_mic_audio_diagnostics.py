"""v0.8.3: host-testable PCM math and source safety contracts.

The 16-kHz PDM clock, actual capture continuity and PSRAM lifetime still
require connected Arduino compile plus a *deliberately approved* hardware test.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch/HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")
MIC = (SKETCH.parent / "MicLevelWorker.h").read_text(encoding="utf-8")
MATH = (SKETCH.parent / "MicAudioMetrics.h").read_text(encoding="utf-8")
WORKER = (SKETCH.parent / "TelemetryWorker.h").read_text(encoding="utf-8")
CHAT = FIRMWARE.split("static void buildChatPage(lv_obj_t *p) {", 1)[1].split(
    "\nstatic void buildVoicePage(", 1,
)[0]
VOICE = FIRMWARE.split("static void buildVoicePage(lv_obj_t *p) {", 1)[1].split(
    "\n// Read aggregate audio level only;", 1,
)[0]


class MicAudioDiagnosticsTests(unittest.TestCase):
    def test_version_and_mic_opt_in(self):
        self.assertIn('label(screen, "v0.8.4 | 480x320"', FIRMWARE)
        self.assertIn("#ifndef HT_MIC_TEST_ENABLED\n#define HT_MIC_TEST_ENABLED 0", FIRMWARE)
        self.assertIn('#if HT_MIC_TEST_ENABLED\n#include "MicLevelWorker.h"', FIRMWARE)

    def test_numeric_diagnostics_never_share_pcm_data(self):
        shared = MIC.split("struct MicLevelSnapshot {", 1)[1].split("};", 1)[0]
        for field in ("uint32_t pttSamples", "uint16_t pttRms",
                      "uint16_t pttPeak", "uint8_t pttClipPct",
                      "uint32_t pttRateHz", "uint8_t pttCoveragePct"):
            self.assertIn(field, shared)
        self.assertNotIn("int16_t *", shared)
        self.assertNotIn("pcm[", shared)
        self.assertIn("micLevelRead(mic)", FIRMWARE)
        self.assertNotIn("lv_", MIC + MATH)

    def test_math_is_pure_and_does_not_retain_pcm(self):
        self.assertIn("struct MicAudioMetrics", MATH)
        self.assertIn("uint64_t energy", MATH)
        self.assertIn("uint32_t samples", MATH)
        self.assertIn("uint16_t peak", MATH)
        self.assertIn("uint32_t clipped", MATH)
        self.assertIn("const int16_t *pcm, size_t count", MATH)
        self.assertNotIn("int16_t *audio", MATH)
        for forbidden in ("WiFi", "HTTPClient", "fopen(", "fwrite(",
                          "Serial.", "lv_", "ESP_I2S"):
            self.assertNotIn(forbidden, MATH)

    def test_worker_accumulates_only_actually_copied_samples(self):
        self.assertIn("const size_t take = min(count, left)", MIC)
        self.assertIn("memcpy(pttAudio + pttSamples, pcm, take * sizeof(int16_t))", MIC)
        self.assertIn("micMetricsAccumulate(pttMetrics, pcm, take)", MIC)
        self.assertIn("pttSamples += take", MIC)
        self.assertIn("micMetricsRms(pttMetrics)", MIC)
        self.assertIn("micMetricsClippedPercent(pttMetrics)", MIC)
        self.assertIn("sample.pttPeak = pttMetrics.peak", MIC)
        self.assertIn("sample.pttSamples = pttLastSamples", MIC)

    def test_throughput_is_observed_not_a_calibrated_audio_clock(self):
        self.assertIn("micMetricsThroughput(pttLastSamples, pttDurationMs)", MIC)
        self.assertIn("micMetricsCoverage(", MIC)
        self.assertIn("elapsedMs < 200", MATH)
        self.assertIn("if (percent > 100) percent = 100", MATH)
        self.assertIn("not I2S clock", MIC)
        self.assertIn("NOT proof of an exact or gapless I2S clock", MATH)

    def test_memory_before_min_after_from_worker_only(self):
        for field in ("pttPsramBeforeKB", "pttPsramMinKB", "pttPsramAfterKB",
                      "pttMemoryValid"):
            self.assertIn(field, MIC)
        self.assertIn("pttPsramBeforeBytes = ESP.getFreePsram()", MIC)
        self.assertIn("pttPsramMinBytes = ESP.getFreePsram()", MIC)
        self.assertIn("if (freePsram < pttPsramMinBytes)", MIC)
        self.assertIn("pttPsramAfterBytes = ESP.getFreePsram()", MIC)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", MIC)
        self.assertNotIn("heap_caps_malloc(", FIRMWARE)

    def test_memory_diagnostics_reset_for_new_capture(self):
        self.assertIn("pttMetrics = MicAudioMetrics{}", MIC)
        self.assertIn("pttMemoryValid = true", MIC)
        self.assertIn("pttMemoryValid = false", MIC)
        self.assertIn('pttPsramAfterBytes = 0; // "after" unavailable while recording', MIC)
        self.assertIn("pttLastSamples = 0", MIC)

    def test_diagnostics_are_on_separate_voice_tab_in_landscape(self):
        self.assertIn('label(diag, "PCM-DIAGNOSE"', VOICE)
        for diag in ("chatDiagPcm", "chatDiagRate", "chatDiagRms", "chatDiagPsram"):
            self.assertIn(diag + " = label(diag,", VOICE)
        self.assertIn("lv_obj_set_pos(chatPttButton, 10, 49)", VOICE)
        self.assertIn("lv_obj_set_pos(chatInput, 10, 157)", CHAT)
        self.assertIn("lv_obj_set_pos(chatSend, 368, 157)", CHAT)
        self.assertNotIn("chatDiagPcm", CHAT)

    def test_progress_bar_is_bounded_and_only_gui_owned(self):
        self.assertIn("chatPttProgress = lv_bar_create(chatPttButton)", VOICE)
        self.assertIn("lv_bar_set_range(chatPttProgress, 0, 4000)", VOICE)
        self.assertIn("mic.pttDurationMs > MIC_PTT_MAX_MS", FIRMWARE)
        self.assertIn("lv_bar_set_value(chatPttProgress,", FIRMWARE)
        self.assertNotIn("lv_", MIC)

    def test_error_path_does_not_display_stale_diagnostics(self):
        self.assertIn("mic.pttPhase == MicPttPhase::ERROR", FIRMWARE)
        self.assertIn("mic.pttPhase == MicPttPhase::NO_PSRAM", FIRMWARE)
        self.assertIn('"PCM: FEHLER / KEIN PUFFER"', FIRMWARE)
        self.assertIn('"PSRAM KB: -- / -- / --"', FIRMWARE)
        self.assertIn('mic.pttPhase == MicPttPhase::RECORDING', FIRMWARE)
        self.assertIn('PSRAM KB: %lu / %lu / --', FIRMWARE)

    def test_readonly_is_not_weakened(self):
        self.assertIn('lv_obj_add_state(chatInput, LV_STATE_DISABLED)', CHAT)
        self.assertIn('lv_obj_add_state(chatSend, LV_STATE_DISABLED)', CHAT)
        self.assertNotIn("lv_obj_add_event_cb(chatSend", CHAT)
        self.assertNotIn("lv_keyboard_create(", FIRMWARE)
        self.assertIn('urlBase + "/v1/status"', WORKER)
        self.assertIn("client.setCACert(HT_CA_CERT)", WORKER)
        for forbidden in ("http.POST(", "http.PUT(", "http.DELETE(",
                          "http.PATCH(", "setInsecure(", "fwrite(", "SD.open("):
            self.assertNotIn(forbidden, FIRMWARE + MIC + MATH)

    @unittest.skipUnless(shutil.which("g++"), "host C++ compiler not installed")
    def test_aggregate_math_executes_on_host_cpp(self):
        source = r"""
#include <cassert>
#include <cstdint>
#include "MicAudioMetrics.h"
int main() {
  MicAudioMetrics empty{};
  assert(micMetricsRms(empty) == 0);
  assert(micMetricsClippedPercent(empty) == 0);
  assert(micMetricsThroughput(64000, 0) == 0);
  assert(micMetricsThroughput(64000, 199) == 0);
  assert(micMetricsCoverage(64000, 0, 16000) == 0);
  assert(micMetricsCoverage(64000, 4000, 0) == 0);

  MicAudioMetrics sample{};
  const int16_t a[] = {3000, -3000};
  micMetricsAccumulate(sample, a, 2);
  assert(sample.samples == 2);
  assert(sample.peak == 3000);
  assert(sample.energy == 18000000ULL);
  assert(micMetricsRms(sample) == 3000);
  assert(micMetricsClippedPercent(sample) == 0);
  const int16_t b[] = {0, 31999, -32000, -32768};
  micMetricsAccumulate(sample, b, 4);
  assert(sample.samples == 6);
  assert(sample.peak == 32768);
  assert(sample.clipped == 2);
  assert(micMetricsClippedPercent(sample) == 33);

  assert(micMetricsThroughput(64000, 4000) == 16000);
  assert(micMetricsCoverage(64000, 4000, 16000) == 100);
  assert(micMetricsThroughput(32000, 4000) == 8000);
  assert(micMetricsCoverage(32000, 4000, 16000) == 50);
  assert(micMetricsCoverage(128000, 4000, 16000) == 100);
  assert(micMetricsCoverage(32000, 4000, 16000) <= 100);
  return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="mic-metrics-") as work:
            executable = Path(work) / "metrics_test"
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
