#!/usr/bin/env bash
# Read-only preflight for compiling ONX3248G035 firmware on Raspberry Pi 5.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
printf '\n=== Hermes Touch / Firmware preflight (read-only) ===\n'
printf 'Host: '; hostname
printf 'Architecture: '; uname -m
printf 'Kernel: '; uname -sr
printf '\nRepo: %s\n' "$ROOT"
if [[ -e "$ROOT/firmware/HermesTouch/Config.h" ]]; then
  printf 'WARNING: private firmware Config.h exists. Build script refuses it.\n'
else
  printf 'Offline demo mode: active (Config.h absent).\n'
fi
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf '\narduino-cli: NOT INSTALLED\n'
  printf 'See docs/BOARD-BRINGUP.md for setup instructions.\n'
  exit 2
fi
printf '\n== Arduino CLI ==\n'
arduino-cli version
printf '\n== Installed cores ==\n'
arduino-cli core list
printf '\n== Installed libraries (relevant) ==\n'
arduino-cli lib list | grep -Ei '(^Name|GFX Library for Arduino|Adafruit CST8XX|Adafruit PCF8574|^ArduinoJson|^lvgl)' || true
printf '\n== Serial devices ==\n'
if [[ -d /dev/serial/by-id ]]; then ls -l /dev/serial/by-id; else printf 'No /dev/serial/by-id directory yet.\n'; fi
printf '\n== Disk free ==\n'
df -h "$HOME" | tail -n 1
printf '\nPreflight complete. No packages installed, nothing flashed.\n'
