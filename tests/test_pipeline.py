"""Deterministic unit tests; no network, API keys, or WebClaw binary required."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_pipeline.agents import ApplicationAgent, MatchAnalystAgent, RecruiterAgent
from job_pipeline.application_history import (
    partition_previously_applied,
    record_applied_jobs,
)
from job_pipeline.cli import command_agent_b, score_verified_jobs
from job_pipeline.discovery_fallback import (
    is_webclaw_verified,
    resolve_employer_application,
    verify_discovered_jobs,
    webclaw_fallback_discovery,
)
from job_pipeline.integrations.browser_use_runner import (
    BrowserUseError,
    BrowserUseRunner,
    build_form_answer_catalog,
)
from job_pipeline.integrations.agent_web_browser import (
    AgentWebBrowserClient,
    AgentWebBrowserError,
    AgentWebBrowserPage,
)
from job_pipeline.integrations.jobspy_source import JobSpySource
from job_pipeline.integrations.resume_matcher import ResumeMatcherClient
from job_pipeline.integrations.resume_matcher import ResumeMatcherError
from job_pipeline.jobs import job_from_fixture, normalize_webclaw_job, validate_job
from job_pipeline.matching import score_job
from job_pipeline.report import export_reports
from job_pipeline.resume import redact_contact_details, resume_terms
from job_pipeline.storage import JobStore
from job_pipeline.util import canonical_url
from job_pipeline.util import write_json
from job_pipeline.webclaw import WebClawError


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

    def test_corrected_resume_profile_evidences_ashby(self) -> None:
        """Keep the corrected resume's Ashby skill in the matching profile."""
        item = dict(self.fixtures[0])
        item["description"] += " Hands-on Ashby ATS administration is required."
        result = score_job(job_from_fixture(item), self.profile)
        self.assertIn("Ashby ATS", result.matched_skills)
        self.assertFalse(any("Ashby ATS" in gap for gap in result.gaps))

    def test_resume_terms_normalize_ashby_label(self) -> None:
        """Recognize the resume's compact 'Greenhouse ATS, Ashby' formatting."""
        terms = resume_terms("Technical Skills: Greenhouse ATS, Ashby")
        self.assertIn("Ashby ATS", terms)

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

    def test_applied_registry_excludes_board_aliases(self) -> None:
        """Keep an applied employer role out when another board uses a different URL."""
        direct = job_from_fixture({
            "url": "https://jobs.example.test/recruiting-coordinator",
            "title": "Recruiting Coordinator",
            "company": "Example Company, Inc.",
            "location": "Remote",
            "description": "Responsibilities and qualifications " * 20,
        })
        linkedin = job_from_fixture({
            "url": "https://www.linkedin.com/jobs/view/12345",
            "title": "Recruiting Coordinator",
            "company": "Example Company",
            "location": "Remote",
            "description": "Responsibilities and qualifications " * 20,
        })
        other = job_from_fixture({
            "url": "https://jobs.other.test/talent-coordinator",
            "title": "Talent Coordinator",
            "company": "Other Employer",
            "location": "San Francisco, CA",
            "description": "Responsibilities and qualifications " * 20,
        })
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "applied_jobs.json"
            record_applied_jobs(registry, [direct])
            new_jobs, applied_jobs = partition_previously_applied([linkedin, other], registry)
        self.assertEqual([job.id for job in applied_jobs], [linkedin.id])
        self.assertEqual([job.id for job in new_jobs], [other.id])

    def test_three_specialist_contracts_stop_at_review(self) -> None:
        """Exercise A/B/C offline and ensure Agent C cannot claim external submission."""
        job = job_from_fixture(self.fixtures[0])
        match = score_job(job, self.profile)
        finding = RecruiterAgent().inspect(job, fresh_days=30)
        analysis = MatchAnalystAgent().analyze(job, match, finding, threshold=72, fresh_days=30)
        self.assertTrue(finding.active)
        self.assertEqual(analysis.recommendation, "apply")
        application_profile = {
            "contact": {
                "first_name": "Demo",
                "last_name": "Candidate",
                "email": "demo@example.test",
                "phone": "555-0100",
                "city": "San Jose",
                "state": "CA",
                "country": "United States",
            },
            "links": {},
            "eligibility": {"authorized_to_work_us": True, "requires_sponsorship": False},
            "preferences": {},
            "standard_answers": {},
            "consents": {"use_contact_for_applications": True},
        }
        with tempfile.TemporaryDirectory() as temp:
            draft = ApplicationAgent().prepare(
                job,
                analysis,
                application_profile,
                ROOT / "README.md",
                Path(temp),
            )
            packet = json.loads(Path(draft.packet_path).read_text(encoding="utf-8"))
        self.assertEqual(draft.status, "awaiting_review")
        self.assertTrue(packet["review_required"])
        self.assertEqual(packet["approval"], "pending")

    def test_jobspy_provider_is_replaceable_and_normalizes_rows(self) -> None:
        """Keep JobSpy parameters and dataframe details behind Agent A's adapter."""
        calls = []

        class FakeFrame:
            def to_dict(self, orient: str):
                self.orient = orient
                return [{
                    "site": "indeed",
                    "title": "Recruiting Coordinator",
                    "company": "Acme",
                    "job_url": "https://www.indeed.com/viewjob?jk=123&utm_source=test",
                    "job_url_direct": "https://jobs.acme.test/recruiting-coordinator",
                    "location": "San Jose, CA",
                    "description": "About the role. Responsibilities and qualifications. " * 8,
                    "date_posted": "2026-07-20",
                    "is_remote": False,
                    "job_type": "fulltime",
                }]

        def fake_scrape(**kwargs):
            calls.append(kwargs)
            return FakeFrame()

        source = JobSpySource(scraper=fake_scrape)
        jobs = source.search(
            "Recruiting Coordinator", "San Jose, CA", 168, 5, ["indeed"]
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "jobspy:indeed")
        self.assertEqual(jobs[0].url, "https://jobs.acme.test/recruiting-coordinator")
        self.assertEqual(calls[0]["hours_old"], 168)
        self.assertEqual(calls[0]["site_name"], ["indeed"])
        self.assertEqual(source.last_diagnostics["result_counts_by_site"], {"indeed": 1})
        self.assertFalse(source.last_diagnostics["fallback_recommended"])

    def test_jobspy_uses_provider_safe_glassdoor_location(self) -> None:
        """Give Glassdoor a parseable city while preserving other board scope."""
        calls = []

        class FakeFrame:
            def __init__(self, site: str):
                self.site = site

            def to_dict(self, orient: str):
                return [{
                    "site": self.site,
                    "title": "Recruiting Coordinator",
                    "company": f"{self.site.title()} Company",
                    "job_url": f"https://jobs.example.test/{self.site}",
                    "location": "San Francisco, CA",
                    "description": "Coordinate interviews and candidate communication.",
                    "date_posted": "2026-07-23",
                    "is_remote": False,
                }]

        def fake_scrape(**kwargs):
            calls.append(kwargs)
            return FakeFrame(kwargs["site_name"][0])

        source = JobSpySource(scraper=fake_scrape)
        jobs = source.search(
            "Recruiting Coordinator",
            "San Francisco Bay Area",
            24,
            5,
            ["indeed", "glassdoor"],
        )

        self.assertEqual(len(jobs), 2)
        self.assertEqual(calls[0]["site_name"], ["indeed"])
        self.assertEqual(calls[0]["location"], "San Francisco, California")
        self.assertEqual(calls[0]["country_indeed"], "USA")
        self.assertEqual(calls[1]["site_name"], ["glassdoor"])
        self.assertEqual(calls[1]["location"], "San Francisco, California")
        self.assertEqual(calls[1]["country_indeed"], "USA")
        self.assertEqual(
            source.last_diagnostics["query_locations_by_site"]["glassdoor"],
            "San Francisco, California",
        )
        self.assertEqual(
            source.last_diagnostics["parameter_strategy_by_site"]["indeed"],
            "country_indeed_plus_full_city_state",
        )
        self.assertEqual(
            source.last_diagnostics["parameter_strategy_by_site"]["glassdoor"],
            "country_indeed_plus_full_city_state",
        )

    def test_jobspy_ziprecruiter_uses_only_full_city_location(self) -> None:
        """Avoid sending Indeed-only country parameters to ZipRecruiter."""
        calls = []

        class EmptyFrame:
            def to_dict(self, orient: str):
                return []

        def fake_scrape(**kwargs):
            calls.append(kwargs)
            return EmptyFrame()

        source = JobSpySource(scraper=fake_scrape)
        source.search(
            "Recruiting Coordinator",
            "San Jose, CA",
            24,
            5,
            ["zip_recruiter"],
        )

        self.assertEqual(calls[0]["site_name"], ["zip_recruiter"])
        self.assertEqual(calls[0]["location"], "San Jose, California")
        self.assertNotIn("country_indeed", calls[0])
        self.assertEqual(
            source.last_diagnostics["parameter_strategy_by_site"]["zip_recruiter"],
            "location_only_full_city_state",
        )

    def test_jobspy_opens_run_circuit_breaker_on_http_400(self) -> None:
        """Capture swallowed provider errors and never retry a blocked board in-run."""
        calls = []

        class EmptyFrame:
            def to_dict(self, orient: str):
                return []

        def fake_scrape(**kwargs):
            calls.append(kwargs)
            logging.getLogger("JobSpy:Glassdoor").error(
                "Glassdoor response status code 400"
            )
            return EmptyFrame()

        source = JobSpySource(scraper=fake_scrape)
        source.search(
            "Recruiting Coordinator",
            "San Francisco, California",
            24,
            5,
            ["glassdoor"],
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(source.last_diagnostics["attempts_by_site"]["glassdoor"], 1)
        self.assertEqual(
            source.last_diagnostics["status_by_site"]["glassdoor"], "blocked_400"
        )
        self.assertTrue(
            source.last_diagnostics["circuit_breakers"]["glassdoor"]["open"]
        )
        self.assertFalse(
            source.last_diagnostics["circuit_breakers"]["glassdoor"][
                "retry_in_current_run"
            ]
        )

    def test_webclaw_fallback_resolves_and_verifies_employer_page(self) -> None:
        """Turn an indexed board result into a validated direct ATS posting."""
        board_url = "https://www.glassdoor.com/job-listing/recruiting-coordinator-acme"
        employer_url = "https://job-boards.greenhouse.io/acme/jobs/123"
        description = "About the role. Responsibilities and qualifications. " * 12
        board_payload = {
            "metadata": {"title": "Recruiting Coordinator | Acme"},
            "content": {
                "plain_text": description,
                "links": [{"text": "Apply", "url": employer_url}],
            },
            "structured_data": [],
        }
        employer_payload = {
            "metadata": {"title": "Recruiting Coordinator | Acme"},
            "content": {"plain_text": description},
            "structured_data": [{
                "@type": "JobPosting",
                "title": "Recruiting Coordinator",
                "hiringOrganization": {"name": "Acme"},
                "description": description,
                "datePosted": "2026-07-28",
            }],
        }

        class FakeWebClaw:
            def search(self, query, num=8, country="us", language="en"):
                return [{"link": board_url}]

            def scrape(self, url):
                return employer_payload if url == employer_url else board_payload

        jobs, diagnostics = webclaw_fallback_discovery(
            FakeWebClaw(),
            "Recruiting Coordinator",
            "San Francisco, California",
            72,
            ["glassdoor"],
            5,
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].url, employer_url)
        self.assertTrue(is_webclaw_verified(jobs[0]))
        self.assertEqual(diagnostics["resolved_active_jobs"], 1)
        self.assertEqual(
            diagnostics["resolution_records"][0]["resolution"],
            "employer_application_page",
        )

    def test_live_verification_rejects_closed_posting(self) -> None:
        """Do not allow a closed employer page into Agent B's scoreable set."""
        job = job_from_fixture(self.fixtures[0])

        class ClosedWebClaw:
            def scrape(self, url):
                return {
                    "metadata": {"title": "Recruiting Coordinator | Example"},
                    "content": {
                        "plain_text": (
                            "This job is no longer available. Responsibilities and "
                            "qualifications. " * 12
                        )
                    },
                    "structured_data": [],
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        verified, errors = verify_discovered_jobs(ClosedWebClaw(), [job], concurrency=1)
        self.assertEqual(verified, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("closed", errors[0]["error"])

    def test_matching_gate_scores_only_verified_active_jobs(self) -> None:
        """Make the verified-only Agent B scoring rule executable and regression-safe."""
        verified = job_from_fixture(self.fixtures[0])
        verified.raw["verification"] = {
            "active": True,
            "verified_by": "webclaw",
            "verified_at": "2026-07-28T12:00:00+00:00",
        }
        unverified = job_from_fixture(self.fixtures[1])
        with tempfile.TemporaryDirectory() as temp:
            with JobStore(Path(temp) / "jobs.sqlite3") as store:
                store.upsert_jobs([verified, unverified])
                scored = score_verified_jobs(store, [verified, unverified], self.profile, "")
                verified_match = store.match(verified.id)
                unverified_match = store.match(unverified.id)
        self.assertEqual(scored, 1)
        self.assertIsNotNone(verified_match)
        self.assertIsNone(unverified_match)

    def test_agent_web_browser_uses_authenticated_read_only_routes(self) -> None:
        """Navigate an exact board tab and retrieve sanitized visible text."""
        calls = []
        description = "About the role. Responsibilities and qualifications. " * 12

        def transport(method, path, body, headers):
            calls.append((method, path, body, headers))
            if path == "/health":
                return {"ok": True, "port": 7896}
            if path == "/status":
                return {
                    "ok": True,
                    "activeTab": 7,
                    "tabs": [{
                        "id": 7,
                        "platform": "glassdoor",
                        "url": "https://www.glassdoor.com/job-listing/123",
                        "title": "Recruiting Coordinator | Acme",
                    }],
                }
            if path == "/page/text":
                return {"ok": True, "result": {"text": description, "len": len(description)}}
            return {"ok": True}

        client = AgentWebBrowserClient(
            token="a" * 64,
            transport=transport,
        )
        self.assertTrue(client.available())
        page = client.read_job_page(
            "https://www.glassdoor.com/job-listing/123",
            "glassdoor",
            poll_attempts=1,
        )

        self.assertIn("Responsibilities", page.text)
        self.assertEqual(page.platform, "glassdoor")
        health_call = next(call for call in calls if call[1] == "/health")
        protected_call = next(call for call in calls if call[1] == "/status")
        self.assertNotIn("Authorization", health_call[3])
        self.assertEqual(protected_call[3]["Authorization"], "Bearer " + ("a" * 64))
        self.assertTrue(any(call[1] == "/tabs/navigate" for call in calls))
        self.assertFalse(any(call[1] in {"/eval", "/action/post"} for call in calls))

    def test_agent_web_browser_rejects_lookalikes_and_unsafe_mode(self) -> None:
        """Keep the integration on exact first-party hosts with all write gates off."""
        client = AgentWebBrowserClient(token="b" * 64, transport=lambda *args: {"ok": True})
        with self.assertRaises(AgentWebBrowserError):
            client.read_job_page(
                "https://glassdoor.com.evil.example/job/123",
                "glassdoor",
                poll_attempts=1,
            )
        with patch.dict("os.environ", {"SMAB_ALLOW_WRITES": "1"}):
            with self.assertRaises(AgentWebBrowserError):
                AgentWebBrowserClient(token="b" * 64, transport=lambda *args: {"ok": True})
        unicode_token_client = AgentWebBrowserClient(
            token="é" * 64,
            transport=lambda *args: {"ok": True},
        )
        with self.assertRaises(AgentWebBrowserError):
            unicode_token_client.status()

    def test_agent_web_browser_recovers_blocked_board_for_employer_resolution(self) -> None:
        """Use AWB visible text when WebClaw cannot read a board, then resolve the ATS page."""
        board_url = "https://www.ziprecruiter.com/jobs/recruiting-coordinator-123"
        employer_url = "https://job-boards.greenhouse.io/acme/jobs/123"
        description = "About the role. Responsibilities and qualifications. " * 12

        class BlockedBoardWebClaw:
            def scrape(self, url):
                if url == board_url:
                    raise WebClawError("HTTP 403")
                return {
                    "metadata": {"title": "Recruiting Coordinator | Acme"},
                    "content": {"plain_text": description},
                    "structured_data": [{
                        "@type": "JobPosting",
                        "title": "Recruiting Coordinator",
                        "hiringOrganization": {"name": "Acme"},
                        "description": description,
                    }],
                }

            def search(self, query, num=8, country="us", language="en"):
                return [{"link": employer_url}]

        class VisibleBoard:
            def read_job_page(self, url, board):
                return AgentWebBrowserPage(
                    url=url,
                    title="Recruiting Coordinator | Acme",
                    platform="ziprecruiter",
                    text=description,
                    text_length=len(description),
                )

        job, resolution = resolve_employer_application(
            BlockedBoardWebClaw(),
            board_url,
            browser_client=VisibleBoard(),
        )
        self.assertEqual(job.url, employer_url)
        self.assertTrue(is_webclaw_verified(job))
        self.assertEqual(resolution["source_reader"], "agent_web_browser")

    def test_resume_matcher_client_projects_ats_evidence(self) -> None:
        """Verify Agent B's adapter calls the documented API contract only."""
        calls = []

        def transport(method, path, body, headers):
            calls.append((method, path, body, headers))
            if path == "/health":
                return {"status": "healthy"}
            if path == "/resumes/upload":
                return {"resume_id": "resume-1", "processing_status": "ready"}
            if path == "/jobs/upload":
                return {"job_id": ["job-1"]}
            return {"data": {"ats_score": {
                "overall_score": 84.5,
                "sub_scores": {"keyword_match": 80, "skills_coverage": 90},
                "missing_keywords": ["Workday"],
                "injectable_keywords": ["Ashby"],
                "recommendations": ["Add one measurable outcome"],
            }}}

        with tempfile.TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"test resume")
            client = ResumeMatcherClient(transport=transport)
            self.assertTrue(client.health())
            resume_id = client.upload_resume(resume)
            external_id = client.upload_jobs(["Responsibilities and qualifications"], resume_id)[0]
            assessment = client.preview(resume_id, external_id)
        self.assertEqual(assessment.overall_score, 84.5)
        self.assertEqual(assessment.missing_keywords, ["Workday"])
        self.assertEqual([call[1] for call in calls], [
            "/health", "/resumes/upload", "/jobs/upload", "/resumes/improve/preview"
        ])
        with self.assertRaises(ResumeMatcherError):
            ResumeMatcherClient("file:///tmp/untrusted")

    def test_low_resume_matcher_preview_routes_agent_b_to_review(self) -> None:
        """Use weak external ATS evidence as a review gate, never as a silent rejection."""
        job = job_from_fixture(self.fixtures[0])
        match = score_job(job, self.profile)
        finding = RecruiterAgent().inspect(job, fresh_days=30)
        analysis = MatchAnalystAgent().analyze(
            job,
            match,
            finding,
            threshold=72,
            fresh_days=30,
            resume_matcher={"overall_score": 45, "missing_keywords": ["Workday"]},
        )
        self.assertEqual(analysis.recommendation, "review")
        self.assertIn("Resume-Matcher missing keyword: Workday", analysis.gaps)

    def test_resume_matcher_outage_preserves_agent_b_review(self) -> None:
        """Do not let optional ATS-service downtime erase deterministic decisions."""
        job = job_from_fixture(self.fixtures[0])
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            database = temp_path / "jobs.sqlite3"
            output = temp_path / "reviews.json"
            with JobStore(database) as store:
                store.upsert_job(job)
                store.upsert_match(score_job(job, self.profile))

            class DownMatcher:
                def health(self):
                    raise ResumeMatcherError("service unavailable")

            args = SimpleNamespace(
                min_score=None,
                live=False,
                database=database,
                job_id=[job.id],
                fresh_days=30,
                resume_matcher=True,
                resume=ROOT / "README.md",
                allow_resume_upload=True,
                resume_matcher_url="http://127.0.0.1:3000/api/v1",
                output=output,
            )
            with patch("job_pipeline.cli.ResumeMatcherClient", return_value=DownMatcher()):
                self.assertEqual(command_agent_b(args, ROOT), 0)
            reviews = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(reviews["records"]), 1)
        self.assertEqual(reviews["records"][0]["analysis"]["recommendation"], "apply")
        self.assertIn("service unavailable", reviews["records"][0]["resume_matcher_error"])

    def test_browser_use_requires_exact_packet_approval(self) -> None:
        """Bind Agent C authority to an exact packet hash, URL, job, and action."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = root / "packet.json"
            approval = root / "approval.json"
            write_json(packet, {
                "job": {
                    "id": "job-123",
                    "url": "https://jobs.example.test/apply/123",
                    "title": "Recruiting Coordinator",
                },
                "candidate": {"resume_path": str(ROOT / "README.md")},
            })
            runner = BrowserUseRunner(packet)
            runner.write_approval_template(approval)
            self.assertEqual(runner.plan("fill_only", approval).approval_status, "pending")
            receipt = json.loads(approval.read_text(encoding="utf-8"))
            receipt.update({
                "decision": "approved",
                "allowed_action": "fill_only",
                "approved_by": "test reviewer",
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            })
            write_json(approval, receipt)
            self.assertEqual(runner.plan("fill_only", approval).approval_status, "approved")
            self.assertIn("click", runner.tool_exclusions("fill_only"))
            self.assertNotIn("click", runner.tool_exclusions("fill_and_submit"))
            with self.assertRaises(BrowserUseError):
                runner._validate_approval(approval, "fill_and_submit")

    def test_form_catalog_never_guesses_sensitive_disclosures(self) -> None:
        """Keep common form mappings explicit and route sensitive unknowns to a human."""
        catalog = build_form_answer_catalog({
            "contact": {"first_name": "Albert", "last_name": "Deluna"},
            "eligibility": {"authorized_to_work_us": True},
        })
        self.assertEqual(catalog["known_fields"]["full_name"], "Albert Deluna")
        self.assertIn("disability_status", catalog["manual_only_topics"])
        self.assertEqual(catalog["unknown_field_policy"], "pause_and_request_human_answer")


if __name__ == "__main__":
    unittest.main()
