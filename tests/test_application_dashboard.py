"""Application dashboard merge and export tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from job_pipeline.application_dashboard import (
    application_summary,
    collect_application_records,
    export_application_dashboard,
)
from job_pipeline.application_history import job_identity_from_fields
from job_pipeline.jobs import Job
from job_pipeline.storage import JobStore


class ApplicationDashboardTests(unittest.TestCase):
    def test_merges_legacy_registry_with_lifecycle_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = root / "data" / "applied_jobs.json"
            registry_path.parent.mkdir(parents=True)
            registry_path.write_text(json.dumps({
                "jobs": [
                    {
                        "identity_key": job_identity_from_fields("Acme", "Recruiting Coordinator"),
                        "company": "Acme",
                        "title": "Recruiting Coordinator",
                        "applied_at": "2026-08-01T10:00:00+00:00",
                        "job_ids": [],
                        "urls": [],
                    },
                    {
                        "identity_key": job_identity_from_fields("Legacy Co", "Talent Coordinator"),
                        "company": "Legacy Co",
                        "title": "Talent Coordinator",
                        "applied_at": "2026-07-20T10:00:00+00:00",
                        "job_ids": [],
                        "urls": [],
                    },
                ]
            }), encoding="utf-8")

            job = Job(
                id="job-1",
                url="https://jobs.example.com/1",
                title="Recruiting Coordinator",
                company="Acme",
                location="San Jose, CA",
                work_mode="hybrid",
                employment_type="full-time",
                posted_date="2026-08-01",
                salary="$80,000",
                description="Coordinate recruiting.",
            )
            with JobStore(root / "data" / "jobs.sqlite3") as store:
                store.upsert_job(job)
                store.set_status(job.id, "applied", notes="Applied on company site")
                store.set_status(job.id, "interviewing", notes="Recruiter screen")
                records = collect_application_records(store, registry_path)
                paths = export_application_dashboard(store, registry_path, root / "reports")

            self.assertEqual(len(records), 2)
            acme = next(item for item in records if item["company"] == "Acme")
            legacy = next(item for item in records if item["company"] == "Legacy Co")
            self.assertEqual(acme["status"], "interviewing")
            self.assertFalse(acme["status_inferred"])
            self.assertEqual(acme["location"], "San Jose, CA")
            self.assertEqual(legacy["status"], "applied")
            self.assertTrue(legacy["status_inferred"])
            summary = application_summary(records)
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["active"], 1)
            self.assertEqual(summary["interviewing"], 1)
            self.assertEqual(summary["status_not_recorded"], 1)

            html_path, csv_path, json_path, exported_summary = paths
            self.assertTrue(html_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(json_path.exists())
            self.assertEqual(exported_summary["total"], 2)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["applications"]), 2)
            page = html_path.read_text(encoding="utf-8")
            self.assertIn("Applications dashboard", page)
            self.assertIn("Legacy Co", page)


if __name__ == "__main__":
    unittest.main()
