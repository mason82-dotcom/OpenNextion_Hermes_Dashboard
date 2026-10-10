#!/usr/bin/env bash
# Compile credential-free OpenNextion demo. NEVER flashes hardware.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH="$ROOT/firmware/HermesTouch"
BUILD="$ROOT/build/firmware-offline"
LOG_DIR="$ROOT/build/logs"
LOG="$LOG_DIR/firmware-offline-build.log"
FQBN="esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB"

if [[ -e "$SKETCH/Config.h" ]]; then
  printf 'REFUSED: Config.h exists; offline builds must not contain credentials.\n' >&2
  exit 3
fi
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'arduino-cli not found. Use scripts/pi/install-arduino-cli.sh.\n' >&2
  exit 2
fi
if ! arduino-cli core list | grep -q '^esp32:esp32 '; then
  printf 'ESP32 core missing. Use scripts/pi/setup-arduino-toolchain.sh.\n' >&2
  exit 2
fi

mkdir -p "$LOG_DIR"
printf 'Hermes Touch: CLEAN / OFFLINE build for ESP32-S3.\n'
printf 'Log: %s\n' "$LOG"
printf 'Build output: %s\n' "$BUILD"
printf 'Clean rebuild avoids stale core.a and object files.\n'

# Store the log OUTSIDE the cleanable build directory.
# Pipefail propagates the actual compiler status through tee.
if arduino-cli compile \
    --clean \
    --fqbn "$FQBN" \
    --build-path "$BUILD" \
    "$SKETCH" 2>&1 | tee "$LOG"; then
  printf '\nSUCCESS: clean offline firmware compile completed.\n'
  printf 'Binary artifacts:\n'
  find "$BUILD" -maxdepth 2 -type f -name '*.bin' -print
  find "$BUILD" -maxdepth 2 -type f -name '*.elf' -print
  printf 'NOTHING FLASHED.\n'
else
  printf '\nBUILD FAILED. No firmware uploaded.\n' >&2
  printf 'Saved compiler log: %s\n' "$LOG" >&2
  printf 'Checking missing ESP32 Arduino HAL symbols in core archive:\n'
  bash "$ROOT/scripts/pi/diagnose-core-archive.sh" "$BUILD" || true
  printf '\nFirst error lines (trimmed):\n'
  grep -m 15 -E '(undefined reference|fatal error:|error:|collect2:|exit status)' "$LOG" || true
  exit 1
fi
