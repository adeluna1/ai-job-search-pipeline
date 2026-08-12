"""Persistent Applications-dashboard outcome and Undo tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from job_pipeline.application_history import job_identity_from_fields
from job_pipeline.cli import command_application_flag, command_application_undo
from job_pipeline.jobs import Job
from job_pipeline.storage import JobStore


class ApplicationOutcomeTests(unittest.TestCase):
    def test_dropdown_flag_and_undo_persist_for_legacy_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = root / "data" / "applied_jobs.json"
            registry_path.parent.mkdir(parents=True)
            identity = job_identity_from_fields("Legacy Co", "Talent Coordinator")
            registry_path.write_text(json.dumps({
                "jobs": [{
                    "identity_key": identity,
                    "company": "Legacy Co",
                    "title": "Talent Coordinator",
                    "applied_at": "2026-07-20T10:00:00+00:00",
                    "job_ids": [],
                    "urls": [],
                }]
            }), encoding="utf-8")

            result = command_application_flag(SimpleNamespace(
                identity_key=identity,
                flag="denied",
                notes="Denied after review",
            ), root)

            self.assertEqual(result, 0)
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["jobs"][0]["status"], "rejected")
            self.assertEqual(payload["jobs"][0]["outcome_flag"], "denied")
            dashboard = json.loads(
                (root / "reports" / "applications_dashboard.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(dashboard["applications"][0]["outcome_label"], "Denied")
            self.assertEqual(dashboard["summary"]["closed"], 1)

            undo_result = command_application_undo(SimpleNamespace(
                identity_key=identity,
            ), root)
            self.assertEqual(undo_result, 0)
            restored = json.loads(registry_path.read_text(encoding="utf-8"))["jobs"][0]
            self.assertNotIn("status", restored)
            self.assertNotIn("outcome_flag", restored)
            dashboard = json.loads(
                (root / "reports" / "applications_dashboard.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(dashboard["applications"][0]["status_inferred"])
            self.assertEqual(dashboard["summary"]["status_not_recorded"], 1)

    def test_flag_and_undo_keep_sqlite_and_registry_statuses_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry_path = root / "data" / "applied_jobs.json"
            registry_path.parent.mkdir(parents=True)
            job = Job(
                id="job-1",
                url="https://jobs.example.com/1",
                title="Recruiting Coordinator",
                company="Acme",
                location="San Jose, CA",
                work_mode="hybrid",
                employment_type="full-time",
                posted_date="2026-08-01",
                salary="",
                description="Coordinate interviews.",
            )
            identity = job_identity_from_fields(job.company, job.title)
            registry_path.write_text(json.dumps({
                "jobs": [{
                    "identity_key": identity,
                    "company": job.company,
                    "title": job.title,
                    "status": "applied",
                    "notes": "Original note",
                    "applied_at": "2026-08-01T10:00:00+00:00",
                    "job_ids": [job.id],
                    "urls": [job.url],
                }]
            }), encoding="utf-8")
            with JobStore(root / "data" / "jobs.sqlite3") as store:
                store.upsert_job(job)
                store.set_status(job.id, "applied", notes="Original note")

            result = command_application_flag(SimpleNamespace(
                identity_key=identity,
                flag="interview",
                notes="Recruiter screen scheduled",
            ), root)
            self.assertEqual(result, 0)
            with JobStore(root / "data" / "jobs.sqlite3") as store:
                self.assertEqual(store.application_state(job.id)["status"], "interviewing")
            flagged = json.loads(registry_path.read_text(encoding="utf-8"))["jobs"][0]
            self.assertEqual(flagged["status"], "interviewing")
            self.assertEqual(flagged["outcome_flag"], "interview")

            undo_result = command_application_undo(SimpleNamespace(
                identity_key=identity,
            ), root)
            self.assertEqual(undo_result, 0)
            with JobStore(root / "data" / "jobs.sqlite3") as store:
                state = store.application_state(job.id)
                self.assertEqual(state["status"], "applied")
                self.assertEqual(state["notes"], "Original note")
            restored = json.loads(registry_path.read_text(encoding="utf-8"))["jobs"][0]
            self.assertEqual(restored["status"], "applied")
            self.assertNotIn("outcome_flag", restored)
            self.assertEqual(restored["notes"], "Original note")


if __name__ == "__main__":
    unittest.main()