"""v0.8 diagnostics source contracts; compilation/hardware still required.

These tests ensure observability code stays read-only, heap measurements are
local, and FreeRTOS stack instrumentation cannot touch LVGL from another task.
"""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = (ROOT / "firmware/HermesTouch/HermesTouch.ino").read_text(encoding="utf-8")
WORKER = (ROOT / "firmware/HermesTouch/TelemetryWorker.h").read_text(encoding="utf-8")


class V08DiagnosticsTests(unittest.TestCase):
    def test_version_bumped_only_in_candidate_firmware(self):
        self.assertIn('label(screen, "v0.8.4 | 480x320"', FIRMWARE)
        self.assertIn("Hermes Touch v0.8.4 (candidate)", FIRMWARE)

    def test_heap_minimum_is_real_esp32_measurement(self):
        self.assertIn("ESP.getFreeHeap()", FIRMWARE)
        self.assertIn("ESP.getMinFreeHeap()", FIRMWARE)
        self.assertIn("Heap: %lu KB | Min: %lu KB", FIRMWARE)

    def test_largest_free_internal_block_is_not_total_psram(self):
        self.assertIn("#include <esp_heap_caps.h>", FIRMWARE)
        self.assertIn("heap_caps_get_largest_free_block(", FIRMWARE)
        self.assertIn("MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT", FIRMWARE)
        self.assertIn("Groesster Block: %lu KB", FIRMWARE)

    def test_worker_stack_watermark_sampled_from_worker_task_only(self):
        self.assertIn("uint32_t workerStackMinFreeBytes = 0;", WORKER)
        start = WORKER.index("static void telemetryTask(void *)")
        end = WORKER.index("static bool telemetryStart()", start)
        task = WORKER[start:end]
        self.assertIn("uxTaskGetStackHighWaterMark(nullptr)", task)
        self.assertLess(task.index("telemetryPoll(snapshot)"),
                        task.index("uxTaskGetStackHighWaterMark(nullptr)"))
        self.assertLess(task.index("uxTaskGetStackHighWaterMark(nullptr)"),
                        task.index("telemetryPublish(snapshot)"))

    def test_gui_reads_published_snapshot_not_task_state(self):
        self.assertIn("telemetryReadSnapshot(incoming)", FIRMWARE)
        self.assertIn("displayedWorkerStackFreeBytes = incoming.workerStackMinFreeBytes", FIRMWARE)
        self.assertIn("TLS-Stack min. frei: %lu B", FIRMWARE)
        self.assertIn("displayedWorkerStackObserved = true;", FIRMWARE)
        self.assertIn("if (displayedWorkerStackObserved)", FIRMWARE)
        self.assertNotIn("uxTaskGetStackHighWaterMark", FIRMWARE)
        self.assertNotIn("lv_", WORKER)

    def test_system_labels_fit_landscape_page(self):
        self.assertIn("card(p, 10, 34, 220, 190)", FIRMWARE)
        self.assertIn("card(p, 240, 34, 230, 190)", FIRMWARE)
        system = FIRMWARE.split("static void buildSystemPage(lv_obj_t *p) {", 1)[1].split(
            "\n// CHAT is a read-only text-chat shell;", 1,
        )[0]
        offsets = re.findall(r'label\(mem, "[^"]+", 8, (\d+), 216,', system)
        self.assertEqual([int(y) for y in offsets], [5, 34, 63, 92, 121, 150])
        self.assertLessEqual(240 + 230, 480)
        self.assertLessEqual(34 + 190, 240)

    def test_offline_mode_does_not_require_network_task(self):
        self.assertIn('#if !HT_DEMO_MODE\n#include "TelemetryWorker.h"', FIRMWARE)
        self.assertIn('#if HT_DEMO_MODE\n  lv_label_set_text(systemStack, "TLS-Task: OFFLINE");', FIRMWARE)
        self.assertIn("HT_DEMO_MODE 1", FIRMWARE)

    def test_system_uptime_psram_touch_and_readonly_still_present(self):
        for value in ("ESP.getFreePsram()", "ESP.getPsramSize()", "systemUptime",
                      "systemTouches", "Touch-Aktionen: %lu"):
            with self.subTest(field=value):
                self.assertIn(value, FIRMWARE)
        self.assertIn('urlBase + "/v1/status"', WORKER)
        self.assertIn("http.GET()", WORKER)
        for forbidden in ("http.POST(", "http.PUT(", "http.DELETE(", "http.PATCH("):
            self.assertNotIn(forbidden, FIRMWARE + WORKER)


if __name__ == "__main__":
    unittest.main()
