"""Static checks for the systemd user-unit autostart (no systemd needed)."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "deploy" / "systemd"
BRIDGE = (UNITS / "hermes-touch-bridge.service.in").read_text(encoding="utf-8")
TLS = (UNITS / "hermes-touch-tls.service.in").read_text(encoding="utf-8")
INSTALLER = (ROOT / "scripts/pi/install-autostart.sh").read_text(encoding="utf-8")


class AutostartTests(unittest.TestCase):
    def test_units_start_through_guarded_run_scripts(self):
        # The run scripts enforce loopback bridge and a separate device token.
        self.assertIn('ExecStart=/usr/bin/bash "@ROOT@/scripts/pi/run-local.sh"', BRIDGE)
        self.assertIn('ExecStart=/usr/bin/bash "@ROOT@/scripts/pi/run-tls.sh"', TLS)

    def test_no_secrets_or_privileges_in_units(self):
        for text in (BRIDGE, TLS):
            self.assertNotIn("TOKEN", text)
            self.assertNotIn("EnvironmentFile", text)
            self.assertNotIn("User=root", text)
            self.assertIn("NoNewPrivileges=yes", text)
            self.assertIn("UMask=0077", text)
            self.assertIn("WantedBy=default.target", text)

    def test_restart_policy(self):
        for text in (BRIDGE, TLS):
            self.assertIn("Restart=always", text)
            self.assertIn("StartLimitIntervalSec=0", text)
        # Refused/missing configuration must not loop forever.
        self.assertIn("RestartPreventExitStatus=2 3", TLS)
        self.assertIn("After=hermes-touch-bridge.service", TLS)

    def test_installer_is_user_level_and_never_touches_hermes_units(self):
        self.assertIn("systemctl --user", INSTALLER)
        self.assertNotIn("sudo systemctl", INSTALLER)
        self.assertNotIn("hermes-gateway.service", INSTALLER)
        self.assertNotIn("hermes-dashboard.service", INSTALLER)
        self.assertIn("sport = :8765", INSTALLER)  # refuses to fight a manual bridge

    @unittest.skipUnless(shutil.which("sed"), "sed required")
    def test_rendered_units_have_no_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("hermes-touch-bridge.service", "hermes-touch-tls.service"):
                out = subprocess.run(
                    ["sed", f"s|@ROOT@|{tmp}|g", str(UNITS / f"{name}.in")],
                    check=True, capture_output=True, text=True).stdout
                self.assertNotIn("@ROOT@", out)
                self.assertIn(f'"{tmp}/scripts/pi/', out)


if __name__ == "__main__":
    unittest.main()
