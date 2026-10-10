"""Static invariants for the credential-free Hermes Touch display test.

These are source-contract checks, NOT a replacement for compiling and
testing on the physical OpenNextion ONX3248G035.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "HermesTouch" / "HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")


class FirmwareContractTests(unittest.TestCase):
    def test_no_private_config_required_for_offline_build(self):
        self.assertIn('#if __has_include("Config.h")', FIRMWARE)
        self.assertIn("#define HT_DEMO_MODE 1", FIRMWARE)

    def test_network_dependencies_conditional(self):
        self.assertIn("#if !HT_DEMO_MODE\n#include <WiFi.h>", FIRMWARE)
        self.assertIn('#include <HTTPClient.h>', FIRMWARE)
        self.assertIn('#include <WiFiClientSecure.h>', FIRMWARE)
        self.assertIn('#include "LocalCa.h"', FIRMWARE)
        self.assertIn('#include <ArduinoJson.h>', FIRMWARE)

    def test_https_only_and_no_tls_bypass(self):
        self.assertIn('base.startsWith("https://")', FIRMWARE)
        self.assertIn("client.setCACert(HT_CA_CERT)", FIRMWARE)
        self.assertIn("configTime(0, 0,", FIRMWARE)
        self.assertNotIn("setInsecure(", FIRMWARE)
        self.assertNotIn("WiFiClient client;", FIRMWARE)

    def test_four_touch_pages(self):
        self.assertIn("PAGE_COUNT = 4", FIRMWARE)
        for text in ('"STATUS"', '"GRAPH"', '"SYSTEM"', '"CHAT"'):
            self.assertIn(text, FIRMWARE)
        self.assertIn("lv_obj_add_event_cb(navBtns[i], onNav", FIRMWARE)

    def test_real_measurements_and_chart(self):
        self.assertIn("ESP.getFreeHeap()", FIRMWARE)
        self.assertIn("ESP.getPsramSize()", FIRMWARE)
        self.assertIn("lv_chart_set_next_value(", FIRMWARE)
        self.assertIn("Quelle: ESP32, nicht Raspberry Pi", FIRMWARE)

    def test_graph_reports_real_sample_count(self):
        self.assertIn("historySampleCount", FIRMWARE)
        self.assertIn("if (historySampleCount < GRAPH_SAMPLES)", FIRMWARE)
        self.assertIn("historySampleCount = 0;", FIRMWARE)
        self.assertIn("%u/%u Werte", FIRMWARE)
        self.assertNotIn("24 Punkte", FIRMWARE)

    def test_lvgl_float_values_are_preformatted_safely(self):
        # LVGL 8.x's built-in printf does not necessarily enable %f.
        # Without this guard the device shows "f C" and corrupts
        # subsequent variadic arguments (observed on real hardware).
        self.assertIn("static void decimalText(", FIRMWARE)
        self.assertIn("std::isfinite(value)", FIRMWARE)
        self.assertIn("snprintf(out, cap,", FIRMWARE)
        self.assertIn('lv_label_set_text_fmt(valueA, "%s C", numberText)', FIRMWARE)
        self.assertIn('lv_label_set_text_fmt(valueB, "%s %%", numberText)', FIRMWARE)
        self.assertIn('lv_label_set_text(valueC, numberText)', FIRMWARE)
        self.assertIn('lv_label_set_text_fmt(historyValue, "Pi: %s C | %u/%u Werte"', FIRMWARE)
        import re
        fmt_calls = re.findall(r'lv_label_set_text_fmt\\([^;]*?\\);', FIRMWARE, re.S)
        self.assertGreater(len(fmt_calls), 0)
        for call in fmt_calls:
            self.assertNotRegex(call, r'%(?:[0-9.+-]*)(?:f|e|g|F|E|G)')

    @unittest.skipUnless(shutil.which("g++"), "C++ host compiler unavailable")
    def test_fixed_decimal_renderer_host_cpp(self):
        """Compile and execute the ACTUAL Arduino float formatter with host C++.

        This isolates the LVGL-unfriendly printf formatting from board
        dependencies, and tests valid/invalid/fractional readings.
        """
        begin = FIRMWARE.index("static void decimalText(")
        end = FIRMWARE.index("\nstatic void sampleStatus()", begin)
        function_source = FIRMWARE[begin:end]
        source = (
            "#include <cmath>\n#include <cstdio>\n"
            "#include <cstdint>\n#include <cstring>\n"
            + function_source
            + r"""
int main() {
    struct Case { float value; unsigned digits; const char *expected; };
    const Case cases[] = {
        {51.2f, 1, "51.2"}, {62.8f, 1, "62.8"},
        {0.53f, 2, "0.53"}, {0.0f, 2, "0.00"},
        {-2.75f, 2, "-2.75"}, {100.0f, 1, "100.0"},
        {NAN, 1, "--"}, {INFINITY, 1, "--"},
        {10001.0f, 1, "--"}
    };
    for (const auto &entry : cases) {
        char buffer[24] = {};
        decimalText(buffer, sizeof(buffer), entry.value, entry.digits);
        if (strcmp(buffer, entry.expected) != 0) return 1;
    }
    char tiny[3] = {};
    decimalText(tiny, sizeof(tiny), 51.2f, 1);
    if (tiny[2] != '\0') return 2;
    return 0;
}
"""
        )
        with tempfile.TemporaryDirectory(prefix="hermes-decimal-test-") as work:
            executable = str(Path(work) / "test_formatter")
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra",
                 "-pedantic", "-x", "c++", "-", "-o", executable],
                input=source,
                text=True, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run([executable], check=True, timeout=10)

    def test_no_chat_or_agent_write_actions(self):
        self.assertIn("CHAT IST DEAKTIVIERT", FIRMWARE)
        self.assertNotIn("http.POST(", FIRMWARE)
        self.assertNotIn("http.PUT(", FIRMWARE)
        self.assertNotIn("http.DELETE(", FIRMWARE)
        self.assertNotIn("WiFiServer", FIRMWARE)

    def test_board_pins_unchanged(self):
        board = (ROOT / "firmware" / "HermesTouch" / "BoardConfig.h").read_text()
        for name, val in (
            ("LCD_SCLK_PIN", "5"),
            ("LCD_MOSI_PIN", "1"),
            ("LCD_DC_PIN", "3"),
            ("LCD_CS_PIN", "2"),
            ("LCD_BL_PIN", "6"),
            ("NEXTION_IIC_SCL_PIN", "7"),
            ("NEXTION_IIC_SDA_PIN", "8"),
        ):
            self.assertRegex(board, name + r"\s*=\s*" + val + r";")


if __name__ == "__main__":
    unittest.main()
