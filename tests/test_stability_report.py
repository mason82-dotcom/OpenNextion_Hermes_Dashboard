"""Read-only Pi HTTPS stability assessment tests; no network or secrets."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts/pi/stability_report.py"
spec = importlib.util.spec_from_file_location("ht_stability_report", SOURCE)
assessment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assessment)


def healthy_run():
    return {
        "total": 360,
        "success": 360,
        "failed": 0,
        "success_pct": 100.0,
        "max_consecutive_failures": 0,
        "result_counts": {"ok": 360},
        "latency_ms": {"avg": 20.0, "p50": 17.0, "p95": 25.0, "max": 154.0},
        "pi_metrics": {},
        "hermes_unhealthy_samples": 0,
        "gateway_off_samples": 0,
        "dashboard_unavailable_samples": 0,
        "configured_minutes": 30.0,
        "actual_seconds": 1800.1,
        "interval_seconds": 5.0,
    }


class TestPiStabilityAssessment(unittest.TestCase):
    def test_complete_clean_30_minute_run_passes(self):
        verdict, reasons = assessment.evaluate(healthy_run())
        self.assertEqual(verdict, "PASS")
        self.assertTrue(reasons)

    def test_short_smoke_test_is_not_endurance_pass(self):
        run = healthy_run()
        run.update(total=3, success=3, result_counts={"ok": 3},
                   actual_seconds=10.1)
        verdict, _ = assessment.evaluate(run)
        self.assertEqual(verdict, "INCOMPLETE")

    def test_interrupted_run_is_not_endurance_pass(self):
        run = healthy_run()
        run["actual_seconds"] = 660.0
        self.assertEqual(assessment.evaluate(run)[0], "INCOMPLETE")

    def test_insufficient_sampling_is_not_full_coverage(self):
        run = healthy_run()
        run.update(total=300, success=300, result_counts={"ok": 300})
        self.assertEqual(assessment.evaluate(run)[0], "INCOMPLETE")

    def test_single_transport_failure_warns_without_hiding_it(self):
        run = healthy_run()
        run.update(success=359, failed=1, success_pct=99.72,
                   result_counts={"ok": 359, "http_error": 1},
                   max_consecutive_failures=1)
        outcome, reasons = assessment.evaluate(run)
        self.assertEqual(outcome, "WARN")
        self.assertTrue(any("HTTPS-Fehler" in reason for reason in reasons))

    def test_three_consecutive_failures_fail(self):
        run = healthy_run()
        run.update(success=357, failed=3, success_pct=99.17,
                   result_counts={"ok": 357, "http_error": 3},
                   max_consecutive_failures=3)
        self.assertEqual(assessment.evaluate(run)[0], "FAIL")

    def test_hermes_unhealthy_warning_and_repeated_failure(self):
        run = healthy_run()
        run["hermes_unhealthy_samples"] = 1
        self.assertEqual(assessment.evaluate(run)[0], "WARN")
        run["hermes_unhealthy_samples"] = 3
        self.assertEqual(assessment.evaluate(run)[0], "FAIL")

    def test_latency_p95_warns_and_critical_p95_fails(self):
        run = healthy_run()
        run["latency_ms"]["p95"] = 300.0
        run["latency_ms"]["max"] = 500.0
        self.assertEqual(assessment.evaluate(run)[0], "WARN")
        run["latency_ms"]["p95"] = 1200.0
        run["latency_ms"]["max"] = 1300.0
        self.assertEqual(assessment.evaluate(run)[0], "FAIL")

    def test_malformed_counts_or_nonfinite_metrics_are_rejected(self):
        fields = (
            ("success", 361), ("failed", True), ("success_pct", float("nan")),
            ("max_consecutive_failures", 100),
            ("hermes_unhealthy_samples", 361),
        )
        for name, value in fields:
            with self.subTest(field=name):
                run = healthy_run()
                run[name] = value
                with self.assertRaises(ValueError):
                    assessment.validate(run)

    def test_invalid_result_category_totals_rejected(self):
        run = healthy_run()
        run["result_counts"] = {"ok": 359}
        with self.assertRaises(ValueError):
            assessment.validate(run)

    def test_latest_result_selects_complete_json_not_live_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pi-tls-20261011T095818Z.csv").write_text("utc,result\n")
            first = root / "pi-tls-20261011T095818Z.summary.json"
            last = root / "pi-tls-20261011T103000Z.summary.json"
            for file in (first, last):
                file.write_text(json.dumps(healthy_run()))
            self.assertEqual(assessment.latest_summary(root), last)

    def test_read_rejects_symlink_or_oversized_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "good.summary.json"
            target.write_text(json.dumps(healthy_run()))
            self.assertEqual(assessment.read_summary(target)["success"], 360)
            symbolic = root / "alias.summary.json"
            symbolic.symlink_to(target)
            with self.assertRaises(ValueError):
                assessment.read_summary(symbolic)
            huge = root / "huge.summary.json"
            huge.write_text("x" * (assessment.MAX_JSON_BYTES + 1))
            with self.assertRaises(ValueError):
                assessment.read_summary(huge)

    def test_cli_prints_only_approved_statistics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "pi-tls-20261011T095818Z.summary.json"
            run = healthy_run()
            run["secret_key"] = "NEVER-ECHO-SECRET"
            target.write_text(json.dumps(run))
            with patch.object(assessment, "STABILITY", root):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = assessment.main(["--latest"])
            self.assertEqual(result, 0)
            self.assertIn("Result: PASS", output.getvalue())
            self.assertNotIn("NEVER-ECHO-SECRET", output.getvalue())
            self.assertIn("Pi TLS checks do NOT measure ESP32", output.getvalue())


if __name__ == "__main__":
    unittest.main()
