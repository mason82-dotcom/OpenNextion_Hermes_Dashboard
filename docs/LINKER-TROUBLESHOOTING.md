# Arduino ESP32-S3: undefined references to SPI, GPIO, PSRAM, UART

## Symptoms

On the Raspberry Pi 5 (aarch64), Arduino CLI 1.5.1 + esp32:esp32@3.3.2
has reached the **link** phase, but the linker reported for example:

- `undefined reference to spiStartBus`
- `undefined reference to spiWriteNL`
- `undefined reference to delay` or `pinMode`
- `undefined reference to psramFound`
- `undefined reference to uartGetEventQueue`
- `undefined reference to xTaskCreateUniversal`

These functions are provided by Arduino's ESP32 framework (not by the
project's LVGL widgets). The fact that several HAL families fail at once
**suggests** a missing/incomplete core archive, stale build objects, or
bad link configuration. It does not diagnose defective board hardware.

## Step 1: Clean rebuild (does not flash)

```bash
cd ~/Projekte/OpenNextion_Hermes_Dashboard
git status --short
git pull --ff-only
bash scripts/pi/firmware-build-offline.sh
```

The build now uses Arduino CLI `compile --clean` to force a fresh
compilation of the sketch, libraries, and core. Compiler output is
preserved at `build/logs/firmware-offline-build.log`, outside the
cleaned build directory.

If compilation fails, the script also audits `core/core.a` for key
Arduino HAL object files and definition symbols. Share the **short**
diagnostic summary and first 15 error lines. Do not upload secrets
or `Config.h`.

## Step 2: Isolated ESP32 core build (only if Step 1 still fails)

```bash
bash scripts/pi/firmware-core-smoke.sh
```

The tiny generated sketch has **no external LVGL/Arduino GFX
dependencies** and compiles against the exact same ESP32-S3 board
options.

- **Core smoke passes:** investigate dependencies, `build_opt.h`, and
  the full Hermes Touch sketch/build separately.
- **Core smoke fails with the same missing HAL symbols:** focus on
  ESP32 framework/core archive/toolchain rather than Hermes Touch source.
- **Different error:** diagnose that specific compiler or linker error
  from `build/logs/core-smoke-build.log`.

## Step 3: Confirm what's in core.a

Both build scripts can call this read-only command:

```bash
bash scripts/pi/diagnose-core-archive.sh
```

Look for archive members such as `esp32-hal-spi.c.o`,
`esp32-hal-misc.c.o`, `esp32-hal-gpio.c.o`, and `esp32-hal-psram.c.o`.
If absent, the archive is incomplete. If present and symbols are defined,
inspect link order and build recipe rather than reinstalling blindly.

## Safety

No `sudo`, deletion of Arduino installations, cache-wide cleanup,
firmware upload, UART interaction, network exposure, or Hermes service
changes are performed by these diagnostic scripts.

**Do not flash** until a binary has linked successfully and the
connected serial device has been positively identified.
