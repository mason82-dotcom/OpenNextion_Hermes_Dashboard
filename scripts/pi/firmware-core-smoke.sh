#!/usr/bin/env bash
# Isolate the Arduino ESP32-S3 toolchain from LVGL and project libraries.
# Generates a tiny sketch under build/, compiles with --clean. Never flashes.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT="$ROOT/build/core-smoke"
SKETCH="$TEST_ROOT/CoreSmoke"
OUT="$TEST_ROOT/output"
LOG="$ROOT/build/logs/core-smoke-build.log"
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'Arduino CLI missing.\n' >&2
  exit 2
fi
mkdir -p "$SKETCH" "$ROOT/build/logs"
cat > "$SKETCH/CoreSmoke.ino" <<'INO'
#include <Arduino.h>
// Compile/link sanity test only; no board upload.
void setup() { pinMode(2, OUTPUT); }
void loop() { digitalWrite(2, LOW); delay(1000); digitalWrite(2, HIGH); delay(1000); }
INO
printf 'Compiling minimal ESP32-S3 sketch in a separate CLEAN build folder...\n'
if arduino-cli compile \
    --clean \
    --fqbn 'esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB' \
    --build-path "$OUT" "$SKETCH" > "$LOG" 2>&1; then
  printf 'CORE SMOKE PASS: ESP32 Core and linker work in isolation.\n'
  printf 'Detailed output: %s\n' "$LOG"
else
  printf 'CORE SMOKE FAIL: ESP32 core/toolchain itself fails independently of LVGL.\n' >&2
  printf 'First linker/compile errors:\n' >&2
  grep -m 14 -E '(undefined reference|fatal error:|error:|collect2:|exit status)' "$LOG" || true
  bash "$ROOT/scripts/pi/diagnose-core-archive.sh" "$OUT" || true
  printf 'Detailed output: %s\n' "$LOG"
  exit 1
fi
printf 'No firmware flashed. No Hermes settings changed.\n'
