"""Regression tests for connected firmware source fingerprinting, no device needed."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/pi/firmware-source-fingerprint.py"
spec = importlib.util.spec_from_file_location("hermes_touch_fingerprint", HELPER)
fingerprints = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fingerprints)


class TestConnectedSourceFingerprint(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="hermes-fingerprint-")
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.sketch = self.root / "firmware/HermesTouch"
        scripts = self.root / "scripts/pi"
        self.sketch.mkdir(parents=True)
        scripts.mkdir(parents=True)
        for name in fingerprints.REQUIRED:
            (self.sketch / name).write_text(f"// {name} initial bytes\n")
        (scripts / "firmware-build-connected.sh").write_text("# build script\n")
        (scripts / "firmware-source-fingerprint.py").write_text("# fingerprint implementation\n")

    def test_digest_is_stable_and_64_hex_chars(self):
        first = fingerprints.fingerprint(self.root)
        second = fingerprints.fingerprint(self.root)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

    def test_telemetry_worker_change_invalidates_previous_build(self):
        old = fingerprints.fingerprint(self.root)
        path = self.sketch / "TelemetryWorker.h"
        before = path.stat()
        path.write_text("COMPLETELY DIFFERENT HEADER\n")
        # Simulate an old or restored modification timestamp.
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertNotEqual(fingerprints.fingerprint(self.root), old)

    def test_secret_config_or_ca_change_invalidates_previous_build(self):
        for name in ("Config.h", "LocalCa.h"):
            with self.subTest(name=name):
                path = self.sketch / name
                old = fingerprints.fingerprint(self.root)
                path.write_bytes(path.read_bytes() + b"changed\n")
                self.assertNotEqual(fingerprints.fingerprint(self.root), old)

    def test_new_header_or_extra_translation_unit_is_included(self):
        original = fingerprints.fingerprint(self.root)
        (self.sketch / "Additional.h").write_text("#pragma once\n")
        added_header = fingerprints.fingerprint(self.root)
        self.assertNotEqual(original, added_header)
        (self.sketch / "More.cpp").write_text("// source\n")
        self.assertNotEqual(added_header, fingerprints.fingerprint(self.root))

    def test_deleted_mandatory_file_is_refused(self):
        (self.sketch / "TelemetryWorker.h").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or symlinked"):
            fingerprints.fingerprint(self.root)

    def test_symlinked_private_header_is_refused(self):
        header = self.sketch / "Config.h"
        elsewhere = self.root / "private.h"
        elsewhere.write_text("secret\n")
        header.unlink()
        header.symlink_to(elsewhere)
        with self.assertRaises(ValueError):
            fingerprints.fingerprint(self.root)

    def test_build_script_changes_invalidate_fingerprint(self):
        before = fingerprints.fingerprint(self.root)
        with (self.root / "scripts/pi/firmware-build-connected.sh").open("a") as out:
            out.write("# modified compile options\n")
        self.assertNotEqual(before, fingerprints.fingerprint(self.root))

    def test_build_and_upload_scripts_enforce_matching_manifest(self):
        build = (ROOT / "scripts/pi/firmware-build-connected.sh").read_text()
        upload = (ROOT / "scripts/pi/firmware-upload-connected.sh").read_text()
        self.assertIn('MANIFEST="$BUILD/.connected-sources.sha256"', build)
        self.assertIn('rm -f -- "$MANIFEST"', build)
        self.assertIn('INPUT_HASH_BEFORE="$(python3 "$ROOT/scripts/pi/firmware-source-fingerprint.py")"', build)
        self.assertIn('INPUT_HASH_AFTER="$(python3 "$ROOT/scripts/pi/firmware-source-fingerprint.py")"', build)
        self.assertIn('if [[ "$INPUT_HASH_BEFORE" != "$INPUT_HASH_AFTER" ]]', build)
        self.assertIn('mv -f -- "$MANIFEST.tmp" "$MANIFEST"', build)
        self.assertIn('CURRENT_HASH="$(python3 "$ROOT/scripts/pi/firmware-source-fingerprint.py")"', upload)
        self.assertIn('if [[ "$CURRENT_HASH" != "$BUILD_HASH" ]]', upload)
        self.assertLess(upload.index('if [[ "$CURRENT_HASH" != "$BUILD_HASH" ]]'),
                        upload.index('arduino-cli upload'))
        self.assertNotIn("--clean", build)
        self.assertNotIn("FLASH-OPENNEXTION", upload)


if __name__ == "__main__":
    unittest.main()
