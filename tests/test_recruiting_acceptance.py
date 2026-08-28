"""Large deterministic acceptance tests for recruiting-position processing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from job_pipeline.recruiting_acceptance import (
    AcceptanceThresholds,
    run_acceptance_suite,
    write_acceptance_report,
)


class RecruitingAcceptanceTests(unittest.TestCase):
    def test_three_large_synthetic_trials_produce_hundreds_of_quality_outputs(self) -> None:
        report = run_acceptance_suite()
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["trials"]), 3)
        for trial in report["trials"]:
            self.assertGreaterEqual(trial["input_jobs"], 600)
            self.assertGreaterEqual(trial["eligible_outputs"], 200)
            self.assertGreaterEqual(trial["top_50_precision"], 0.98)
            self.assertEqual(trial["senior_roles_in_outputs"], 0)
            self.assertEqual(trial["private_data_findings"], 0)

    def test_threshold_failure_is_explicit_and_machine_readable(self) -> None:
        thresholds = AcceptanceThresholds(minimum_outputs=10_000)
        report = run_acceptance_suite(thresholds=thresholds)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(all("eligible_outputs" in item["failures"] for item in report["trials"]))

    def test_report_contains_metrics_not_candidate_content(self) -> None:
        report = run_acceptance_suite()
        with tempfile.TemporaryDirectory() as temp:
            path = write_acceptance_report(report, Path(temp) / "acceptance.json")
            serialized = path.read_text(encoding="utf-8")
        parsed = json.loads(serialized)
        self.assertEqual(parsed["status"], "passed")
        self.assertNotIn("description", serialized.casefold())
        self.assertNotIn("resume", serialized.casefold())
        self.assertNotIn("@", serialized)


if __name__ == "__main__":
    unittest.main()
