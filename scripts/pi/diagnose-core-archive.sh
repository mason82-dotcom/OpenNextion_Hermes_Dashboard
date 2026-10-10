#!/usr/bin/env bash
# Read-only investigation of an Arduino ESP32 core archive after linker failure.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="${1:-$ROOT/build/firmware-offline}"
case "$BUILD" in
  "$ROOT"/build/*) ;;
  *) printf 'Refusing to inspect outside project build folder.\n' >&2; exit 2 ;;
esac
CORE="$BUILD/core/core.a"
if [[ ! -f "$CORE" ]]; then
  printf 'No core archive at: %s\n' "$CORE"
  exit 0
fi

# Use cross-binutils installed by the Arduino ESP32 platform.
AR=""
NM=""
TOOL_DIR="$HOME/.arduino15/packages/esp32/tools/esp-x32/2507/bin"
if [[ -x "$TOOL_DIR/xtensa-esp-elf-ar" ]]; then
  AR="$TOOL_DIR/xtensa-esp-elf-ar"
  NM="$TOOL_DIR/xtensa-esp-elf-nm"
fi
if [[ ! -x "$AR" || ! -x "$NM" ]]; then
  printf 'Cross binutils not found in %s\n' "$TOOL_DIR"
  exit 0
fi
printf '\n=== Arduino core.a link audit (read-only) ===\n'
printf 'Core archive: %s\n' "$CORE"
printf 'Archive size: '; stat -c '%s bytes' "$CORE"
printf 'Arduino HAL archive members:\n'
"$AR" t "$CORE" | grep -E 'esp32-hal-(spi|misc|gpio|uart|psram)' || true

printf '\nDefined core symbols (only expected names):\n'
"$NM" --defined-only "$CORE" 2>/dev/null |
  grep -E '[[:space:]][TtWw][[:space:]](delay|pinMode|digitalWrite|spiStartBus|psramFound|uartGetEventQueue|xTaskCreateUniversal)$' || true

printf '\nObject file presence in build/core:\n'
for name in esp32-hal-misc.c.o esp32-hal-spi.c.o esp32-hal-gpio.c.o esp32-hal-uart.c.o esp32-hal-psram.c.o; do
  if [[ -f "$BUILD/core/$name" ]]; then
    printf 'present %s\n' "$name"
  else
    printf 'absent  %s\n' "$name"
  fi
done
printf 'No changes made. No credentials printed.\n'
