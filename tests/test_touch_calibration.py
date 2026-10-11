"""v0.8.4 hardware-specific CST826 touch diagnosis without speculative rotation.

Pure coordinate profiles are host-compiled. User-supplied real CST826
corner measurements selected T1 as the permanent production mapping.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/HermesTouch/HermesTouch.ino"
FIRMWARE = SKETCH.read_text(encoding="utf-8")
TOUCH = (SKETCH.parent / "LandscapeTouch.h").read_text(encoding="utf-8")
CONFIG_EXAMPLE = (SKETCH.parent / "Config.h.example").read_text(encoding="utf-8")
WORKER = (SKETCH.parent / "TelemetryWorker.h").read_text(encoding="utf-8")


class TouchCalibrationTests(unittest.TestCase):
    def test_usb_calibration_is_disabled_unless_explicitly_enabled(self):
        self.assertIn("#define HT_TOUCH_CALIBRATION_ENABLED 0", CONFIG_EXAMPLE)
        self.assertIn("#ifndef HT_TOUCH_CALIBRATION_ENABLED\n#define HT_TOUCH_CALIBRATION_ENABLED 0", FIRMWARE)
        self.assertIn('#error "HT_TOUCH_CALIBRATION_ENABLED must be 0 or 1"', FIRMWARE)
        self.assertIn("static uint8_t touchCalibProfile = 1", FIRMWARE)
        self.assertIn("#if HT_TOUCH_CALIBRATION_ENABLED", FIRMWARE)

    def test_diagnostic_reports_raw_and_mapped_coordinates_only_on_usb(self):
        self.assertIn('"TOUCH_RAW x=%d y=%d -> LVGL x=%d y=%d profile=%u', FIRMWARE)
        self.assertIn("(int)point.x, (int)point.y", FIRMWARE)
        self.assertIn("(int)rotated.x, (int)rotated.y", FIRMWARE)
        self.assertIn("static void touchCalibHandleUsb()", FIRMWARE)
        self.assertIn("touchCalibHandleUsb(); // local calibration", FIRMWARE)
        self.assertIn("wasTouching = false", FIRMWARE)
        self.assertNotIn("Serial", WORKER)

    def test_serial_profile_is_bounded_and_volatile(self):
        self.assertIn("byte >= '0' && byte <= '7'", FIRMWARE)
        self.assertIn("touchCalibProfile = static_cast<uint8_t>(byte - '0')", FIRMWARE)
        self.assertIn("touchCalibCommandOpen = (byte == 'T')", FIRMWARE)
        self.assertIn('TOUCH: PROFIL 1', FIRMWARE)
        for forbidden in ("Preferences", "EEPROM", "NVS", "nvs_set_", "fwrite(", "SD.open("):
            self.assertNotIn(forbidden, TOUCH)
        for forbidden in ("WiFi", "HTTP", "lv_", "Serial"):
            self.assertNotIn(forbidden, TOUCH)

    def test_production_math_uses_t1_and_t0_remains_diagnostic(self):
        self.assertIn("mapNativeTouchToLandscape(rawX, rawY, nativeWidth, nativeHeight)", TOUCH)
        self.assertIn("return mapNativeTouchToLandscape(rawX, rawY,", TOUCH)
        self.assertIn("mapTouchWithProfile(", TOUCH)
        self.assertIn("if (profile == 1)", TOUCH)
        self.assertIn("if (profile == 0 || profile == 6 || profile == 7)", TOUCH)
        self.assertIn("static_cast<int16_t>(py)", TOUCH)
        self.assertIn("nativeWidth - 1 - px", TOUCH)
        self.assertIn("SCREEN_W = LCD_V_RES", FIRMWARE)
        self.assertIn("gfx->setRotation(1)", FIRMWARE)

    @unittest.skipUnless(shutil.which("g++"), "host g++ not installed")
    def test_actual_cpp_eight_profiles_boundaries_and_clamping(self):
        source = r"""
#include <cassert>
#include "LandscapeTouch.h"
static void eq(int x,int y,unsigned mode,int expectedX,int expectedY) {
  auto p=mapTouchWithProfile(x,y,mode);
  assert(p.x==expectedX && p.y==expectedY);
}
int main() {
  eq(50,100,0,379,50);
  eq(50,100,1,100,269);
  eq(400,80,2,400,80);
  eq(400,80,3,79,80);
  eq(400,80,4,400,239);
  eq(400,80,5,79,239);
  eq(50,100,6,100,50);
  eq(50,100,7,379,269);
  eq(0,0,0,479,0);
  eq(319,479,0,0,319);
  eq(-1,10000,0,0,0);
  eq(500,500,2,479,319);
  eq(-1,-1,2,0,0);
  eq(50,100,255,100,269); // unknown profiles fall back to production T1
  auto p=mapNativeTouchToLandscape(319,31);
  assert(p.x==31 && p.y==0);
  p=mapNativeTouchToLandscape(12,462);
  assert(p.x==462 && p.y==307);
  p=mapTouchWithProfile(319,31,1);
  assert(p.x==31 && p.y==0);
  p=mapTouchWithProfile(12,462,1);
  assert(p.x==462 && p.y==307);
  return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="touch-cst826-") as work:
            executable = Path(work) / "profiles"
            subprocess.run(
                ["g++", "-std=c++17", "-Wall", "-Wextra", "-pedantic",
                 "-I", str(SKETCH.parent), "-x", "c++", "-", "-o",
                 str(executable)],
                input=source, text=True, check=True, timeout=30,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run([str(executable)], check=True, timeout=10,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
