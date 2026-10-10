#!/usr/bin/env bash
# Compile connected HTTPS-only firmware locally; does NOT upload it.
# Contains WLAN credentials and a read-only device token -> private build.
set -euo pipefail
umask 077
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH="$ROOT/firmware/HermesTouch"
BUILD="$ROOT/build/firmware-connected"
LOG_DIR="$ROOT/build/logs"
LOG="$LOG_DIR/firmware-connected-build.log"
FQBN="esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB"

if [[ ! -s "$SKETCH/Config.h" || ! -s "$SKETCH/LocalCa.h" ]]; then
  printf 'Missing local Config.h or LocalCa.h. See docs/TLS-LIVE-SETUP.md\n' >&2
  exit 2
fi
if ! grep -Eq '^#define HT_DEMO_MODE[[:space:]]+0[[:space:]]*$' "$SKETCH/Config.h"; then
  printf 'REFUSED: not configured for live mode.\n' >&2
  exit 2
fi
if ! grep -Eq '^#define HT_BRIDGE_URL "https://' "$SKETCH/Config.h"; then
  printf 'REFUSED: HTTPS-only config required.\n' >&2
  exit 2
fi
if ! grep -q -- '-----BEGIN CERTIFICATE-----' "$SKETCH/LocalCa.h"; then
  printf 'REFUSED: missing trusted CA PEM.\n' >&2
  exit 2
fi
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'Arduino CLI not found.\n' >&2
  exit 2
fi
mkdir -p "$BUILD" "$LOG_DIR"
chmod 700 "$BUILD" "$LOG_DIR"
printf 'Compiling connected TLS firmware with a clean build...\n'
printf 'No passwords, tokens or private certificates will be printed.\n'
if arduino-cli compile --clean --fqbn "$FQBN" \
     --build-path "$BUILD" "$SKETCH" > "$LOG" 2>&1; then
  printf 'CONNECTED COMPILE OK. Artifacts kept private in build/firmware-connected.\n'
  printf 'Application binary: %s\n' "$BUILD/HermesTouch.ino.bin"
  printf 'NOTHING FLASHED.\n'
else
  printf 'BUILD FAILED (see local log: build/logs/firmware-connected-build.log).\n' >&2
  grep -m 12 -E '(error:|undefined reference|collect2:|exit status)' "$LOG" || true
  exit 1
fi
