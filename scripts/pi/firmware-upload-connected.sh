#!/usr/bin/env bash
# Manual upload for the already-built HTTPS-only Hermes Touch firmware.
# NEVER compiles or uploads automatically. Requires live TLS smoke test and
# an explicit confirmation before replacing the working offline firmware.
set -euo pipefail
umask 077
export PATH="$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKETCH="$ROOT/firmware/HermesTouch"
BUILD="$ROOT/build/firmware-connected"
FQBN='esp32:esp32:esp32s3:FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB'

if [[ $# -ne 1 ]]; then
  printf 'Usage: bash scripts/pi/firmware-upload-connected.sh /dev/serial/by-id/<verified-board>\n' >&2
  exit 2
fi

for file in "$SKETCH/Config.h" "$SKETCH/LocalCa.h"; do
  [[ -s "$file" ]] || { printf 'REFUSED: missing private TLS device configuration.\n' >&2; exit 3; }
done
grep -Eq '^#define HT_DEMO_MODE[[:space:]]+0[[:space:]]*$' "$SKETCH/Config.h" ||
  { printf 'REFUSED: not in HTTPS live mode.\n' >&2; exit 3; }
grep -Eq '^#define HT_BRIDGE_URL "https://' "$SKETCH/Config.h" ||
  { printf 'REFUSED: HTTPS-only device URL required.\n' >&2; exit 3; }
grep -q -- '-----BEGIN CERTIFICATE-----' "$SKETCH/LocalCa.h" ||
  { printf 'REFUSED: no real TLS trust anchor.\n' >&2; exit 3; }

for name in HermesTouch.ino.bin HermesTouch.ino.bootloader.bin HermesTouch.ino.partitions.bin; do
  [[ -s "$BUILD/$name" ]] ||
    { printf 'REFUSED: missing connected firmware artifacts. Run firmware-build-connected.sh.\n' >&2; exit 3; }
done
for source in "$SKETCH/Config.h" "$SKETCH/LocalCa.h" "$SKETCH/HermesTouch.ino" "$SKETCH/BoardConfig.h"; do
  if [[ "$source" -nt "$BUILD/HermesTouch.ino.bin" ]]; then
    printf 'REFUSED: source/config newer than binary; rebuild connected firmware.\n' >&2
    exit 3
  fi
done

if ! command -v arduino-cli >/dev/null 2>&1; then
  printf 'Arduino CLI not installed.\n' >&2
  exit 2
fi
PORT="$1"
DEVICE="$(readlink -f -- "$PORT" || true)"
case "$DEVICE" in
  /dev/ttyUSB[0-9]*|/dev/ttyACM[0-9]*) ;;
  *) printf 'Unsupported or unresolved serial port.\n' >&2; exit 2 ;;
esac
if [[ ! -c "$DEVICE" || ! -r "$DEVICE" || ! -w "$DEVICE" ]]; then
  printf 'Serial port missing or insufficient permissions.\n' >&2
  exit 2
fi

printf '\n=== Hermes Touch HTTPS-only firmware upload preflight ===\n'
printf 'Connected build: %s\n' "$BUILD/HermesTouch.ino.bin"
printf 'Port: %s -> %s\n' "$PORT" "$DEVICE"
printf 'Checking direct, certificate-verified HTTPS status before upload...\n'
bash "$ROOT/scripts/pi/tls-smoke.sh" ||
  { printf 'REFUSED: TLS smoke test failed; leave working offline firmware untouched.\n' >&2; exit 3; }
printf '\nWARNING: this replaces the working offline firmware on the selected board.\n'
printf 'Do not continue unless you physically confirmed this serial device is the OpenNextion.\n'
printf 'The connected image embeds WiFi credentials and a read-only HTTPS device token.\n'
printf 'To authorize, type exactly: FLASH-HERMES-TLS\n'
if [[ ! -t 0 ]]; then
  printf 'REFUSED: interactive terminal required.\n' >&2
  exit 4
fi
read -r -p 'Confirmation: ' answer
if [[ "$answer" != "FLASH-HERMES-TLS" ]]; then
  printf 'Cancelled; no device modified.\n'
  exit 4
fi
arduino-cli upload \
  --fqbn "$FQBN" \
  --port "$DEVICE" \
  --input-dir "$BUILD" \
  "$SKETCH"
printf '\nUpload completed. Verify HTTPS telemetry on hardware.\n'
