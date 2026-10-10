#!/usr/bin/env bash
# Explicit opt-in to install the ESP32-S3 Arduino build dependencies.
# Writes only to Arduino CLI's user data directories; no flash/sudo/Hermes edits.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  printf 'Expected a Linux ARM64 Raspberry Pi; got %s\n' "$(uname -m)" >&2
  exit 2
fi
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'arduino-cli not found. First run: bash scripts/pi/install-arduino-cli.sh\n' >&2
  exit 2
fi
if [[ -e "$ROOT/firmware/HermesTouch/Config.h" ]]; then
  printf 'WARNING: Local Config.h exists. Keep it uncommitted and offline during first board bring-up.\n'
fi
printf 'Arduino CLI: '; arduino-cli version
printf 'Free disk space: '; df -h "$HOME" | tail -n 1
printf '\nInstalling ESP32 Arduino core 3.3.2 and pinned firmware libraries.\n'
printf 'This downloads large toolchains into user Arduino directories.\n'
printf 'It does NOT upload firmware or change running Hermes services.\n\n'

ESP32_URL='https://espressif.github.io/arduino-esp32/package_esp32_index.json'
arduino-cli core update-index --additional-urls "$ESP32_URL"
arduino-cli core install 'esp32:esp32@3.3.2' --additional-urls "$ESP32_URL"

arduino-cli lib install 'GFX Library for Arduino'
arduino-cli lib install 'Adafruit CST8XX Library'
arduino-cli lib install 'Adafruit PCF8574'
arduino-cli lib install 'ArduinoJson@7.4.2'
arduino-cli lib install 'lvgl@8.3.11'

printf '\n== Installed ESP32 core ==\n'
arduino-cli core list
printf '\nSetup completed. Next: bash scripts/pi/firmware-build-offline.sh\n'
