#!/usr/bin/env bash
# Explicitly confirmed upload of an already-built OFFLINE demo only.
# Does not compile, install packages, or alter Hermes services.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH="$ROOT/firmware/HermesTouch"
BUILD="$ROOT/build/firmware-offline"
FQBN='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'

if [[ $# -ne 1 ]]; then
  printf 'Usage: bash scripts/pi/firmware-upload-offline.sh /dev/serial/by-id/<device>\n' >&2
  printf 'List candidate serial ports: ls -l /dev/serial/by-id/\n' >&2
  exit 2
fi

if [[ -e "$SKETCH/Config.h" ]]; then
  printf 'REFUSED: local Config.h exists; test the credential-free firmware first.\n' >&2
  exit 3
fi

for filename in HermesTouch.ino.bin HermesTouch.ino.bootloader.bin HermesTouch.ino.partitions.bin; do
  if [[ ! -s "$BUILD/$filename" ]]; then
    printf 'Missing firmware file: %s\nRebuild with firmware-build-offline.sh\n' "$filename" >&2
    exit 3
  fi
done
if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'arduino-cli is not installed.\n' >&2
  exit 2
fi
PORT="$1"
DEVICE="$(readlink -f -- "$PORT" || true)"
case "$DEVICE" in
  /dev/ttyUSB[0-9]*|/dev/ttyACM[0-9]*) ;;
  *)
    printf 'Unsupported or unresolved serial port: %s\n' "$PORT" >&2
    exit 2
    ;;
esac
if [[ ! -c "$DEVICE" ]]; then
  printf 'Serial port does not exist as a character device: %s\n' "$DEVICE" >&2
  exit 2
fi
if [[ ! -r "$DEVICE" || ! -w "$DEVICE" ]]; then
  printf 'No read/write permission for: %s\n' "$DEVICE" >&2
  printf 'Check: ls -l %s; id -nG\n' "$DEVICE" >&2
  exit 2
fi

printf '\n=== OpenNextion OFFLINE firmware upload ===\n'
printf 'Port: %s -> %s\n' "$PORT" "$DEVICE"
printf 'Firmware: %s\n' "$BUILD/HermesTouch.ino.bin"
printf 'FQBN: %s\n' "$FQBN"
printf 'Board identity is NOT confirmed by USB vendor ID alone.\n'
if command -v udevadm >/dev/null 2>&1; then
  printf 'USB identification (verify this is YOUR OpenNextion):\n'
  udevadm info --query=property --name="$DEVICE" 2>/dev/null |
    grep -E '^(ID_VENDOR_ID|ID_MODEL_ID|ID_VENDOR=|ID_MODEL=|ID_SERIAL_SHORT=)' || true
fi
printf '\nWARNING: this operation REPLACES THE CURRENT FIRMWARE on the attached device.\n'
printf 'Disconnect/reconnect the OpenNextion first and confirm this exact port belongs to it.\n'
printf 'To authorize flashing this device, type: FLASH-OPENNEXTION\n'
if [[ ! -t 0 ]]; then
  printf 'REFUSED: interactive terminal required.\n' >&2
  exit 4
fi
read -r -p 'Confirmation: ' confirm
if [[ "$confirm" != 'FLASH-OPENNEXTION' ]]; then
  printf 'Cancelled. No device modified.\n'
  exit 4
fi

printf '\nUploading offline demo (no WiFi credentials, no Hermes API key)...\n'
arduino-cli upload \
  --fqbn "$FQBN" \
  --port "$DEVICE" \
  --input-dir "$BUILD" \
  "$SKETCH"
printf '\nUpload command succeeded. Verify actual boot/display/touch on hardware.\n'
