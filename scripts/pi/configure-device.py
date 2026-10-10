#!/usr/bin/env python3
"""Create credential-bearing Config.h locally without leaking it to stdout/history.

Uses already-present read-only bridge token and project TLS bind address.
Never copies Hermes API credentials to the ESP32.
"""
from __future__ import annotations

import getpass
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "firmware" / "HermesTouch" / "Config.h"
ANCHOR = ROOT / "firmware" / "HermesTouch" / "LocalCa.h"


def read_config(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ValueError(f"invalid local configuration line in {path.name}")
        result[key.strip()] = value.strip()
    return result


def main():
    if OUT.exists():
        raise SystemExit("Config.h already exists: refusing to overwrite credentials")
    if not ANCHOR.is_file() or "-----BEGIN CERTIFICATE-----" not in ANCHOR.read_text():
        raise SystemExit("Real LocalCa.h missing; first run export-ca-header.sh")
    bridge = read_config(ROOT / "config" / "bridge.env")
    tls = read_config(ROOT / "config" / "tls.env")
    if bridge.get("HERMES_TOUCH_BIND", "127.0.0.1") != "127.0.0.1":
        raise SystemExit("The unencrypted local bridge must bind only to 127.0.0.1")
    token = tls.get("HERMES_TOUCH_DEVICE_TOKEN", "")
    host = tls.get("HERMES_TOUCH_TLS_BIND", "")
    port = tls.get("HERMES_TOUCH_TLS_PORT", "8766")
    if len(token) < 24 or not host or not port.isdigit():
        raise SystemExit("Bridge token/TLS address incomplete")
    ssid = input("WLAN SSID (2.4 GHz): ")
    password = getpass.getpass("WLAN password (not echoed): ")
    if not ssid or not password:
        raise SystemExit("SSID and WLAN password required")
    for name, value in (("ssid", ssid), ("password", password), ("token", token)):
        if any(ch in value for ch in ("\x00", "\r", "\n")):
            raise SystemExit(f"Invalid control character in {name}")
    config = (
        "#pragma once\n"
        "// PRIVATE local file, never commit or share. Read-only Pi bridge token only.\n"
        "#define HT_DEMO_MODE 0\n"
        f"#define HT_WIFI_SSID {json.dumps(ssid, ensure_ascii=True)}\n"
        f"#define HT_WIFI_PASSWORD {json.dumps(password, ensure_ascii=True)}\n"
        f'#define HT_BRIDGE_URL "https://{host}:{port}"\n'
        f"#define HT_DEVICE_TOKEN {json.dumps(token, ensure_ascii=True)}\n"
    )
    fd = os.open(str(OUT), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fp:
        fp.write(config)
    print("Created local Config.h (mode 0600), containing the read-only HTTPS device token.")
    print("No credentials printed or uploaded. This token will be embedded in device flash.")
    print("Next: bash scripts/pi/firmware-build-connected.sh")


if __name__ == "__main__":
    main()
