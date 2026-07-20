"""Deterministic unit tests; no network, API keys, or WebClaw binary required."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from job_pipeline.jobs import job_from_fixture, normalize_webclaw_job, validate_job
from job_pipeline.matching import score_job
from job_pipeline.report import export_reports
from job_pipeline.resume import redact_contact_details
from job_pipeline.storage import JobStore
from job_pipeline.util import canonical_url


ROOT = Path(__file__).resolve().parent.parent


class PipelineTests(unittest.TestCase):
    """Exercise URL cleaning, extraction, scoring, privacy, storage, and reporting."""

    def setUp(self) -> None:
        """Load the shipped configuration and deterministic fixtures."""
        self.profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
        self.fixtures = json.loads((ROOT / "tests" / "fixtures" / "sample_jobs.json").read_text(encoding="utf-8"))["jobs"]

    def test_contact_redaction(self) -> None:
        """Ensure phone, email, and LinkedIn URLs do not reach model context."""
        value = "Call (212) 555-1212 or me@example.com https://linkedin.com/in/example"
        redacted = redact_contact_details(value)
        self.assertNotIn("555-1212", redacted)
        self.assertNotIn("me@example.com", redacted)
        self.assertNotIn("linkedin.com", redacted)

    def test_canonical_url_removes_tracking(self) -> None:
        """Ensure tracking parameters and fragments cannot create duplicate jobs."""
        cleaned = canonical_url("https://Jobs.Example.com/role/?utm_source=x&id=42#apply")
        self.assertEqual(cleaned, "https://jobs.example.com/role?id=42")

    def test_jsonld_job_normalization(self) -> None:
        """Prefer Schema.org JobPosting facts over ambiguous page-title fallbacks."""
        payload = {
            "metadata": {"title": "Fallback title | Fallback company"},
            "content": {"plain_text": "Job content " * 20},
            "structured_data": [{
                "@type": "JobPosting",
                "title": "Recruiting Coordinator",
                "hiringOrganization": {"name": "Acme"},
                "jobLocation": {"address": {"addressLocality": "San Jose", "addressRegion": "CA"}},
                "datePosted": "2026-07-18"
            }],
        }
        job = normalize_webclaw_job("https://example.test/job/1", payload)
        self.assertEqual(job.title, "Recruiting Coordinator")
        self.assertEqual(job.company, "Acme")
        self.assertIn("San Jose", job.location)

    def test_greenhouse_fallbacks_recover_company_and_location(self) -> None:
        """Use employer-controlled logo text and metadata when JSON-LD is absent."""
        payload = {
            "metadata": {"title": "Recruiting Coordinator", "description": "Long Beach, California"},
            "content": {"plain_text": "Responsibilities and qualifications " * 20, "markdown": "![Vast Logo](logo.png)"},
            "structured_data": [],
        }
        job = normalize_webclaw_job("https://job-boards.greenhouse.io/vast/jobs/123", payload)
        self.assertEqual(job.company, "Vast")
        self.assertEqual(job.location, "Long Beach, California")

    def test_generic_job_index_is_rejected(self) -> None:
        """Keep expired redirects and empty career indexes out of the shortlist."""
        job = job_from_fixture({
            "url": "https://example.test/jobs",
            "title": "Jobs",
            "company": "Unknown company",
            "location": "Unspecified",
            "description": "Current openings " * 30,
        })
        valid, reason = validate_job(job)
        self.assertFalse(valid)
        self.assertIn("generic", reason)

    def test_recruiting_role_outranks_engineering_role(self) -> None:
        """Protect the core product promise: resume-aligned work ranks first."""
        scored = [score_job(job_from_fixture(item), self.profile) for item in self.fixtures]
        by_id = {item.job_id: item for item in scored}
        recruiting = job_from_fixture(self.fixtures[0])
        engineering = job_from_fixture(self.fixtures[2])
        self.assertGreater(by_id[recruiting.id].final_score, by_id[engineering.id].final_score + 30)
        self.assertIn(by_id[recruiting.id].fit_label, {"excellent", "strong"})

    def test_named_ats_gap_is_explained(self) -> None:
        """Do not treat general Greenhouse experience as evidence of required Ashby admin work."""
        item = dict(self.fixtures[0])
        item["description"] += " Hands-on Ashby ATS administration is required."
        result = score_job(job_from_fixture(item), self.profile)
        self.assertTrue(any("Ashby ATS" in gap for gap in result.gaps))

    def test_storage_and_reports(self) -> None:
        """Verify the full offline data path produces both user-facing exports."""
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            with JobStore(temp_path / "jobs.sqlite3") as store:
                for item in self.fixtures:
                    job = job_from_fixture(item)
                    store.upsert_job(job)
                    store.upsert_match(score_job(job, self.profile))
                records = store.ranked(0)
            html_path, csv_path = export_reports(records, temp_path, 72)
            self.assertTrue(html_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertIn("Recruiting Operations Coordinator", html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
