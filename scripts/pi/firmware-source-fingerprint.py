#!/usr/bin/env python3
"""Stable fingerprint of local connected-firmware inputs.

Hash the *contents*, not modification times: git checkout and restored files
may preserve old timestamps. Output one SHA-256 digest; never print secrets.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SKETCH = Path("firmware/HermesTouch")
REQUIRED = (
    "HermesTouch.ino", "BoardConfig.h", "TelemetryWorker.h",
    "Config.h", "LocalCa.h",
)
SOURCE_EXTENSIONS = {".ino", ".h", ".hpp", ".c", ".cpp", ".cc"}


def connected_sources(root: Path) -> list[Path]:
    sketch = root / SKETCH
    for name in REQUIRED:
        path = sketch / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or symlinked firmware input: {name}")
    inputs = [
        path for path in sketch.iterdir()
        if path.suffix.lower() in SOURCE_EXTENSIONS
    ]
    inputs.extend((
        root / "scripts/pi/firmware-build-connected.sh",
        root / "scripts/pi/firmware-source-fingerprint.py",
    ))
    for path in inputs:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or symlinked firmware build input")
    return sorted(inputs, key=lambda path: path.relative_to(root).as_posix())


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"hermes-touch-connected-source-fingerprint-v1\0")
    for path in connected_sources(root):
        relative_name = path.relative_to(root).as_posix().encode("utf-8")
        contents = path.read_bytes()
        digest.update(len(relative_name).to_bytes(4, "big"))
        digest.update(relative_name)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


if __name__ == "__main__":
    try:
        print(fingerprint(ROOT))
    except (OSError, ValueError) as exc:
        print(f"Fingerprint failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
