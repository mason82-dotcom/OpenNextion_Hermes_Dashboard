#!/usr/bin/env bash
# Compile offline demo only. No Wi-Fi, no Hermes key, NO FLASHING.
set -euo pipefail
# Discover user-installed Arduino CLI without changing shell dotfiles.
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH="$ROOT/firmware/HermesTouch"
if [[ -e "$SKETCH/Config.h" ]]; then
  printf 'REFUSED: Config.h exists. Remove/rename it only after securing its contents.\n' >&2
  printf 'Offline demo build must not contain any local Wi-Fi or API credentials.\n' >&2
  exit 3
fi
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'arduino-cli not found. First run: bash scripts/pi/firmware-preflight.sh\n' >&2
  exit 2
fi
if ! arduino-cli core list | grep -q 'esp32:esp32'; then
  printf 'ESP32 Arduino core missing. Install esp32:esp32@3.3.2 (see docs).\n' >&2
  exit 2
fi
BUILD="$ROOT/build/firmware-offline"
mkdir -p "$BUILD"
printf 'Building OFFLINE display/touch test only. Build folder: %s\n' "$BUILD"
arduino-cli compile \
  --fqbn 'esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB' \
  --build-path "$BUILD" \
  "$SKETCH"
printf '\nCompiled binaries (if any):\n'
find "$BUILD" -maxdepth 2 -type f \( -name '*.bin' -o -name '*.elf' \) -printf '%p (%s bytes)\n'
printf '\nCompilation complete. NOTHING FLASHED.\n'
