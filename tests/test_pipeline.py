"""Deterministic unit tests; no network, API keys, or WebClaw binary required."""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_pipeline.agents import ApplicationAgent, MatchAnalystAgent, RecruiterAgent
from job_pipeline.application_history import (
    partition_previously_applied,
    record_applied_entries,
    record_applied_jobs,
)
from job_pipeline.cli import (
    _export,
    _transition_application,
    command_agent_b,
    command_agent_c,
    score_verified_jobs,
)
from job_pipeline.handoff import build_agent_c_handoff, validate_agent_c_handoff
from job_pipeline.discovery_fallback import (
    direct_application_domain,
    direct_ats_discovery,
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
from job_pipeline.geography import evaluate_geography, partition_by_geography
from job_pipeline.jobs import job_from_fixture, normalize_webclaw_job, validate_job
from job_pipeline.job_exclusions import partition_excluded_jobs
from job_pipeline.matching import score_job
from job_pipeline.posting_intelligence import (
    content_fingerprint,
    enrich_jobs_with_posting_intelligence,
    fingerprint_similarity,
)
from job_pipeline.report import export_reports
from job_pipeline.role_scope import evaluate_role_scope
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

    def test_liveness_detects_filled_role_without_form_false_positive(self) -> None:
        """Port Career Ops' filled-role guard while allowing form instructions."""
        closed = job_from_fixture({
            **self.fixtures[0],
            "description": (
                "The job you are trying to apply for has been filled. "
                + self.fixtures[0]["description"]
            ),
        })
        valid, reason = validate_job(closed)
        self.assertFalse(valid)
        self.assertIn("filled", reason)

        active = job_from_fixture({
            **self.fixtures[0],
            "description": (
                self.fixtures[0]["description"]
                + " Once the application form has been filled out, submit it for review."
            ),
        })
        self.assertTrue(validate_job(active)[0])

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

    def test_posting_intelligence_detects_reposts_and_cross_listings(self) -> None:
        """Add Career Ops pattern signals without modifying the resume-fit score."""
        verification = {
            "active": True,
            "verified_by": "webclaw",
            "direct_domain_verified": True,
        }
        now = datetime.now(timezone.utc)
        description = self.fixtures[0]["description"] * 3
        prior_repost = replace(
            job_from_fixture({
                **self.fixtures[0],
                "url": "https://jobs.ashbyhq.com/acme/old-role-id",
                "company": "Acme, Inc.",
                "title": "Recruiting Coordinator",
                "description": description,
            }),
            discovered_at=(now - timedelta(days=14)).isoformat(),
            raw={"verification": verification},
        )
        agency_copy = replace(
            job_from_fixture({
                **self.fixtures[0],
                "url": "https://jobs.lever.co/staffing-example/copied-role",
                "company": "Staffing Example",
                "title": "Talent Operations Specialist",
                "description": description,
            }),
            discovered_at=(now - timedelta(days=5)).isoformat(),
            raw={"verification": verification},
        )
        current = replace(
            job_from_fixture({
                **self.fixtures[0],
                "url": "https://jobs.ashbyhq.com/acme/new-role-id",
                "company": "Acme",
                "title": "Recruiting Coordinator",
                "description": description,
            }),
            raw={"verification": verification},
        )
        enriched = enrich_jobs_with_posting_intelligence(
            [current], [prior_repost, agency_copy]
        )[0]
        intelligence = enriched.raw["posting_intelligence"]
        self.assertEqual(intelligence["trust"]["level"], "high")
        self.assertTrue(intelligence["repost"]["detected"])
        self.assertEqual(intelligence["repost"]["appearance_count"], 2)
        self.assertEqual(len(intelligence["cross_listings"]), 1)
        self.assertFalse(intelligence["fit_score_affected"])
        self.assertEqual(
            score_job(current, self.profile).final_score,
            score_job(enriched, self.profile).final_score,
        )

    def test_posting_intelligence_ignores_legacy_string_verification(self) -> None:
        """Treat older text verification fields as unverified history, not a crash."""
        current = job_from_fixture(self.fixtures[0])
        legacy = replace(
            current,
            id="legacy-verification-record",
            url="https://jobs.example.test/legacy-verification-record",
            discovered_at=datetime.now(timezone.utc).isoformat(),
            raw={"verification": "verified"},
        )

        enriched = enrich_jobs_with_posting_intelligence([current], [legacy])[0]

        self.assertFalse(enriched.raw["posting_intelligence"]["repost"]["detected"])

    def test_posting_fingerprint_is_stable_and_local(self) -> None:
        """Fingerprint descriptions deterministically without an LLM or network call."""
        text = self.fixtures[0]["description"] * 3
        left = content_fingerprint(text)
        right = content_fingerprint("  " + text.replace("Responsibilities:", "Responsibilities: "))
        self.assertRegex(left, r"^[0-9a-f]{16}$")
        self.assertGreaterEqual(fingerprint_similarity(left, right), 0.92)
        self.assertEqual(content_fingerprint("too short"), "")

    def test_posting_intelligence_appears_in_reports(self) -> None:
        """Expose posting confidence separately from the original fit score."""
        job = replace(
            job_from_fixture(self.fixtures[0]),
            raw={
                "posting_intelligence": {
                    "trust": {"score": 75, "level": "medium", "flags": ["suspicious_domain"]},
                    "repost": {"detected": True, "appearance_count": 2},
                    "cross_listings": [],
                }
            },
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with JobStore(root / "jobs.sqlite3") as store:
                store.upsert_job(job)
                store.upsert_match(score_job(job, self.profile))
                records = store.ranked(0)
            html_path, csv_path = export_reports(records, root, 72)
            html_text = html_path.read_text(encoding="utf-8")
            csv_text = csv_path.read_text(encoding="utf-8-sig")
        self.assertIn("Posting confidence: Medium (75/100)", html_text)
        self.assertIn("Advisory only; resume score unchanged.", html_text)
        self.assertIn("posting_trust_level", csv_text)

    def test_agent_b_requires_review_for_conflicting_legitimacy_signals(self) -> None:
        """Keep legitimacy separate from fit but require a human on conflicting signals."""
        raw = {
            "posting_intelligence": {
                "trust": {"score": 45, "level": "low", "flags": ["invalid_url"]},
                "repost": {"detected": True, "appearance_count": 3, "window_days": 90},
                "cross_listings": [],
            }
        }
        job = replace(job_from_fixture(self.fixtures[0]), raw=raw)
        match = score_job(job, self.profile)
        finding = RecruiterAgent().inspect(job, fresh_days=30)
        analysis = MatchAnalystAgent().analyze(
            job, match, finding, threshold=72, fresh_days=30
        )
        self.assertEqual(analysis.recommendation, "review")
        self.assertEqual(analysis.score, match.final_score)
        self.assertTrue(any("Posting confidence" in item for item in analysis.insights))

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
    def test_closed_registry_excludes_cross_board_alias_without_identity_key(self) -> None:
        """Legacy company/title exclusions must suppress newly discovered URLs."""
        direct = job_from_fixture({
            "url": "https://jobs.example.test/recruiting-consultant-1",
            "title": "Recruiting Consultant 1",
            "company": "Example Company, Inc.",
            "location": "San Francisco, CA",
            "description": "Responsibilities and qualifications " * 20,
        })
        board_alias = job_from_fixture({
            "url": "https://www.linkedin.com/jobs/view/98765",
            "title": "Recruiting Consultant 1",
            "company": "Example Company",
            "location": "San Francisco, CA",
            "description": "Responsibilities and qualifications " * 20,
        })
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "job_exclusions.json"
            write_json(registry, {
                "schema_version": 1,
                "updated_at": "2026-08-11T00:00:00+00:00",
                "jobs": [{
                    "title": direct.title,
                    "company": direct.company,
                    "job_ids": [direct.id],
                    "urls": [direct.url],
                    "reason": "expired_redirect",
                }],
            })
            eligible, excluded = partition_excluded_jobs([board_alias], registry)
        self.assertEqual(eligible, [])
        self.assertEqual([item.id for item in excluded], [board_alias.id])


    def test_spreadsheet_applied_entries_become_durable_exclusions(self) -> None:
        """Importing a company/title row must exclude a newly discovered board alias."""
        job = job_from_fixture({
            "url": "https://boards.example.test/jobs/99",
            "title": "Recruiting Coordinator",
            "company": "Decagon",
            "location": "San Francisco, CA",
            "description": "Responsibilities and qualifications " * 20,
        })
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "applied_jobs.json"
            record_applied_entries(registry, [{
                "company": "Decagon", "title": "Recruiting Coordinator"
            }])
            new_jobs, applied_jobs = partition_previously_applied([job], registry)
        self.assertEqual(new_jobs, [])
        self.assertEqual([item.id for item in applied_jobs], [job.id])

    def test_applied_company_typo_alias_is_excluded(self) -> None:
        """Known workbook spelling variants must match the employer's canonical name."""
        job = job_from_fixture({
            "url": "https://boards.example.test/jobs/aston-carter",
            "title": "Recruiting Coordinator",
            "company": "Aston Carter",
            "location": "San Jose, CA",
            "description": "Responsibilities and qualifications " * 20,
        })
        with tempfile.TemporaryDirectory() as temp:
            registry = Path(temp) / "applied_jobs.json"
            record_applied_entries(registry, [{
                "company": "Ashton Carter", "title": "Recruiting Coordinator"
            }])
            new_jobs, applied_jobs = partition_previously_applied([job], registry)
        self.assertEqual(new_jobs, [])
        self.assertEqual([item.id for item in applied_jobs], [job.id])

    def test_exact_geography_gate(self) -> None:
        """Allow Bay Area assignments and broad US remote work, but reject unrelated cities."""
        base = dict(self.fixtures[0])
        bay = job_from_fixture({**base, "url": "https://example.test/bay", "location": "Mountain View, CA", "work_mode": "hybrid"})
        remote = job_from_fixture({**base, "url": "https://example.test/remote", "location": "Remote, United States", "work_mode": "remote"})
        new_york = job_from_fixture({**base, "url": "https://example.test/ny", "location": "New York, NY", "work_mode": "onsite"})
        unknown = job_from_fixture({**base, "url": "https://example.test/unknown", "location": "Unspecified", "work_mode": "hybrid"})
        kept, rejected = partition_by_geography(
            [bay, remote, new_york, unknown], ["San Francisco Bay Area", "San Jose, California"]
        )
        self.assertEqual({item.id for item in kept}, {bay.id, remote.id})
        self.assertEqual({item.id for item, _ in rejected}, {new_york.id, unknown.id})
        self.assertFalse(evaluate_geography(new_york, ["San Jose, California"]).eligible)

    def test_recruiting_coordinator_role_scope_rejects_generic_hr_title(self) -> None:
        """A fuzzy board result must not enter an exact coordinator search report."""
        recruiting = job_from_fixture({
            **self.fixtures[0], "title": "Talent Acquisition Coordinator"
        })
        generic_hr = job_from_fixture({
            **self.fixtures[0],
            "url": "https://example.test/people-culture",
            "title": "People and Culture Coordinator (HR)",
        })
        self.assertTrue(evaluate_role_scope(recruiting, "Recruiting Coordinator").eligible)
        self.assertFalse(evaluate_role_scope(generic_hr, "Recruiting Coordinator").eligible)

    def test_related_junior_titles_enter_broadened_search(self) -> None:
        """Coordinator, associate, specialist, and junior-recruiter titles are adjacent."""
        for title in (
            "Recruiting Assistant",
            "Recruiting Scheduler",
            "Talent Operations Coordinator",
            "Candidate Experience Coordinator",
            "People Operations Coordinator",
            "Technical Sourcing Coordinator",
            "Junior Recruiter",
            "Recruiter I",
            "Associate Recruiter",
            "Recruiting Associate",
            "Talent Acquisition Associate",
            "Talent Acquisition Specialist",
            "University Recruiter",
            "University Recruiting Coordinator",
        ):
            job = job_from_fixture({**self.fixtures[0], "title": title})
            self.assertTrue(
                evaluate_role_scope(job, "Recruiting Coordinator").eligible,
                title,
            )

    def test_expanded_recruiting_search_still_rejects_senior_titles(self) -> None:
        """Broad discovery must not admit senior, lead, manager, or director roles."""
        for title in (
            "Senior Recruiter", "Lead Recruiter", "Recruiting Manager",
            "Director of Talent Acquisition", "Principal Technical Recruiter",
            "Technical Recruiter",
        ):
            job = job_from_fixture({**self.fixtures[0], "title": title})
            self.assertFalse(
                evaluate_role_scope(job, "Junior Recruiter").eligible,
                title,
            )

    def test_current_run_report_is_capped_and_does_not_leak_history(self) -> None:
        """Agent A reports only selected current-run IDs and never more than ten."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current_ids = []
            with JobStore(root / "jobs.sqlite3") as store:
                for index in range(13):
                    job = job_from_fixture({
                        **self.fixtures[0],
                        "url": f"https://example.test/jobs/current-{index}",
                        "company": f"Current {index}",
                    })
                    store.upsert_job(job)
                    store.upsert_match(score_job(job, self.profile))
                    if index < 12:
                        current_ids.append(job.id)
                html_path, csv_path = _export(
                    store, self.profile, root, 0, job_ids=current_ids, limit=10
                )
            csv_rows = csv_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(csv_rows), 11)
            self.assertNotIn("Current 12", html_path.read_text(encoding="utf-8"))

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

    def test_direct_domain_accepts_joined_employer_name_and_trusted_ats(self) -> None:
        """Recognize legitimate joined company domains without weakening ATS suffix checks."""
        employer = direct_application_domain(
            "https://careers.spectrocloud.com/jobs/recruiting-coordinator",
            "Spectro Cloud",
        )
        hrmdirect = direct_application_domain(
            "https://spectrocloud.hrmdirect.com/employment/job-opening.php?id=123",
            "Different Display Name",
        )
        lookalike = direct_application_domain(
            "https://spectrocloud.com.evil.example/jobs/recruiting-coordinator",
            "Spectro Cloud",
        )

        self.assertTrue(employer["verified"])
        self.assertEqual(employer["kind"], "employer_domain")
        self.assertTrue(hrmdirect["verified"])
        self.assertEqual(hrmdirect["matched_domain"], "hrmdirect.com")
        self.assertFalse(lookalike["verified"])

    def test_direct_ats_discovery_queries_all_trusted_groups(self) -> None:
        """Search direct ATS groups even when all ordinary job boards are healthy."""
        ats_url = "https://jobs.ashbyhq.com/acme/123"
        description = "Recruiting coordination responsibilities and qualifications. " * 20

        class DirectAtsWebClaw:
            def search(self, query, num=8, country="us", language="en"):
                return [{"link": ats_url}]

            def scrape(self, url):
                return {
                    "metadata": {"title": "Recruiting Coordinator | Acme"},
                    "content": {"plain_text": description},
                    "structured_data": [{
                        "@type": "JobPosting",
                        "title": "Recruiting Coordinator",
                        "hiringOrganization": {"name": "Acme"},
                        "description": description,
                        "datePosted": "2026-08-11",
                        "jobLocation": {
                            "@type": "Place",
                            "address": {"addressLocality": "San Francisco"},
                        },
                    }],
                }

        jobs, diagnostics = direct_ats_discovery(
            DirectAtsWebClaw(),
            "Recruiting Coordinator",
            ["San Francisco, California", "Remote, United States"],
            168,
            10,
        )

        self.assertEqual(len(diagnostics["queries_by_group"]), 3)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].url, ats_url)
        self.assertTrue(is_webclaw_verified(jobs[0]))

    def test_resolution_follows_safe_redirect_to_final_ats_job(self) -> None:
        """Verify the final ATS page instead of rejecting a legitimate job redirect."""
        source_url = "https://careers.spectrocloud.com/jobs/recruiting-coordinator"
        final_url = "https://jobs.ashbyhq.com/spectrocloud/123"
        description = "Recruiting coordination responsibilities and qualifications. " * 20

        class RedirectingWebClaw:
            def scrape(self, url):
                company = "Spectro Cloud"
                return {
                    "metadata": {"title": f"Recruiting Coordinator | {company}"},
                    "content": {"plain_text": description},
                    "structured_data": [{
                        "@type": "JobPosting",
                        "title": "Recruiting Coordinator",
                        "hiringOrganization": {"name": company},
                        "description": description,
                    }],
                }

            def probe(self, url, max_bytes=524_288):
                return {
                    "status": 200,
                    "final_url": final_url,
                    "content_type": "text/html",
                    "body": description,
                }

        job, resolution = resolve_employer_application(
            RedirectingWebClaw(), source_url
        )

        self.assertEqual(job.url, final_url)
        self.assertTrue(resolution["followed_safe_redirect"])
        self.assertTrue(is_webclaw_verified(job))
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

    def test_resolution_rejects_board_country_domain_as_employer_page(self) -> None:
        """A Glassdoor country-domain result page is still a board, not an employer page."""
        source_url = (
            "https://www.glassdoor.co.uk/Job/london-recruiting-coordinator-jobs-"
            "SRCH_IL.0,6_IC2671300_KO7,29.htm"
        )
        description = "Recruiting responsibilities and qualifications. " * 20

        class CountryBoardWebClaw:
            def scrape(self, url):
                return {
                    "metadata": {"title": "42 recruiting coordinator jobs | Glassdoor"},
                    "content": {"plain_text": description},
                    "structured_data": [],
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        with self.assertRaises(WebClawError):
            resolve_employer_application(CountryBoardWebClaw(), source_url)

    def test_resolution_rejects_secondary_aggregator_as_employer_page(self) -> None:
        """Valid-looking BeBee content cannot satisfy the employer-controlled URL gate."""
        source_url = "https://bebee.com/us/jobs/recruiting-coordinator-example"
        description = "Recruiting responsibilities and qualifications. " * 20

        class AggregatorWebClaw:
            def scrape(self, url):
                return {
                    "metadata": {"title": "Recruiting Coordinator | Example"},
                    "content": {"plain_text": description},
                    "structured_data": [],
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        with self.assertRaises(WebClawError):
            resolve_employer_application(AggregatorWebClaw(), source_url)

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

    def test_fresh_probe_rejects_expired_redirect_after_cached_job_content(self) -> None:
        """Cached job text cannot override a live redirect to an expired shell."""
        source_url = "https://jobs.example.test/jobs/recruiting-coordinator-123"
        description = "Recruiting coordination responsibilities and qualifications. " * 20

        class CachedButExpiredWebClaw:
            def scrape(self, url):
                return {
                    "metadata": {"title": "Recruiting Coordinator | Example"},
                    "content": {"plain_text": description},
                    "structured_data": [{
                        "@type": "JobPosting",
                        "title": "Recruiting Coordinator",
                        "hiringOrganization": {"name": "Example"},
                        "description": description,
                    }],
                }

            def probe(self, url, max_bytes=524_288):
                return {
                    "status": 200,
                    "final_url": "https://jobs.example.test/jobs?error=true",
                    "content_type": "text/html",
                    "body": "Current openings",
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        with self.assertRaisesRegex(WebClawError, "expired-job redirect"):
            resolve_employer_application(CachedButExpiredWebClaw(), source_url)

    def test_live_verification_preserves_discovery_date_and_location_when_omitted(self) -> None:
        """Do not erase board evidence when an active employer page omits optional fields."""
        job = job_from_fixture({
            **self.fixtures[0],
            "url": "https://example.test/jobs/preserve-fields",
            "location": "San Jose, CA",
            "posted_date": "2026-08-05",
            "work_mode": "hybrid",
        })

        class EmployerWithoutOptionalFields:
            def scrape(self, url):
                return {
                    "metadata": {"title": "Recruiting Operations Coordinator | Example Robotics"},
                    "content": {"plain_text": job.description},
                    "structured_data": [{
                        "@type": "JobPosting",
                        "title": job.title,
                        "hiringOrganization": {"name": job.company},
                        "description": job.description,
                    }],
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        verified, errors = verify_discovered_jobs(
            EmployerWithoutOptionalFields(), [job], concurrency=1
        )
        self.assertEqual(errors, [])
        self.assertEqual(verified[0].posted_date, job.posted_date)
        self.assertEqual(verified[0].location, job.location)
        self.assertEqual(verified[0].work_mode, job.work_mode)

    def test_validation_rejects_job_not_found_and_removed_404_pages(self) -> None:
        """Reject the exact stale ATS shells that caused the July 29 false positives."""
        for message in (
            "Job not found. The job you requested was not found.",
            "The job posting you're looking for might have closed, or it has been removed. (404 error).",
        ):
            job = job_from_fixture({
                **self.fixtures[0],
                "description": (message + " Responsibilities and qualifications. ") * 12,
            })
            valid, reason = validate_job(job)
            self.assertFalse(valid)
            self.assertIn("closed", reason)

    def test_live_verification_does_not_reuse_old_receipt(self) -> None:
        """A previously verified role must still be rechecked on every Agent A run."""
        job = job_from_fixture(self.fixtures[0])
        job.raw["verification"] = {
            "active": True,
            "verified_by": "webclaw",
            "verified_at": "2026-07-28T12:00:00+00:00",
        }

        class NowClosedWebClaw:
            def scrape(self, url):
                return {
                    "metadata": {"title": "Job not found"},
                    "content": {
                        "plain_text": (
                            "Job not found. The job you requested was not found. "
                            "Responsibilities and qualifications. " * 12
                        )
                    },
                    "structured_data": [],
                }

            def search(self, query, num=8, country="us", language="en"):
                return []

        verified, errors = verify_discovered_jobs(NowClosedWebClaw(), [job], concurrency=1)
        self.assertEqual(verified, [])
        self.assertEqual(len(errors), 1)

    def test_browser_fallback_rejects_generic_job_shell_despite_job_hint(self) -> None:
        """Discovery metadata must not make a generic board shell look active."""
        job = job_from_fixture({
            **self.fixtures[0],
            "url": "https://www.ziprecruiter.com/jobs/example/closed-role-id",
        })

        class EmptyWebClaw:
            def scrape(self, url):
                raise WebClawError("dynamic page returned no readable job content")

            def search(self, query, num=8, country="us", language="en"):
                return []

        class GenericJobShell:
            def read_job_page(self, url, board):
                text = "Search jobs and explore current openings. " * 20
                return AgentWebBrowserPage(
                    url=url,
                    title="Jobs",
                    platform="ziprecruiter",
                    text=text,
                    text_length=len(text),
                )

        verified, errors = verify_discovered_jobs(
            EmptyWebClaw(),
            [job],
            concurrency=1,
            browser_client=GenericJobShell(),
        )
        self.assertEqual(verified, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Could not resolve", errors[0]["error"])

    def test_matching_gate_scores_only_verified_active_jobs(self) -> None:
        """Make the verified-only Agent B scoring rule executable and regression-safe."""
        verified = job_from_fixture(self.fixtures[0])
        verified.raw["verification"] = {
            "active": True,
            "verified_by": "webclaw",
            "verified_at": "2026-07-28T12:00:00+00:00",
            "direct_domain_verified": True,
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
        self.assertEqual(reviews["records"][0]["analysis"]["recommendation"], "review")
        self.assertEqual(reviews["agent_c_handoffs"], [])
        self.assertIn("service unavailable", reviews["records"][0]["resume_matcher_error"])

    def test_strict_hourly_recency_preserves_date_only_uncertainty(self) -> None:
        """Do not turn a boundary-crossing calendar date into a false 24-hour claim."""
        now = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        base = dict(self.fixtures[0])
        exact = job_from_fixture({**base, "posted_date": "2026-08-09T13:00:00+00:00"})
        stale = job_from_fixture({**base, "posted_date": "2026-08-09T11:00:00+00:00"})
        ambiguous = job_from_fixture({**base, "posted_date": "2026-08-09"})
        recruiter = RecruiterAgent()
        self.assertTrue(recruiter.inspect(exact, fresh_hours=24, now=now).fresh)
        self.assertFalse(recruiter.inspect(stale, fresh_hours=24, now=now).fresh)
        finding = recruiter.inspect(ambiguous, fresh_hours=24, now=now)
        self.assertIsNone(finding.fresh)
        self.assertEqual(finding.freshness_precision, "date")
        self.assertEqual(finding.freshness_window_hours, 24)

    def test_direct_application_domain_rejects_lookalike_hosts(self) -> None:
        """Require an exact ATS suffix or hostname evidence for the named employer."""
        ats_lookalike = direct_application_domain(
            "https://greenhouse.io.evil.example/jobs/123", "Acme"
        )
        employer_lookalike = direct_application_domain(
            "https://jobs.acme-careers.evil.com/jobs/123", "Acme"
        )
        employer = direct_application_domain(
            "https://jobs.acme.example/jobs/123", "Acme"
        )
        board = direct_application_domain(
            "https://www.linkedin.com/jobs/view/123", "Acme"
        )
        self.assertFalse(ats_lookalike["verified"])
        self.assertFalse(employer_lookalike["verified"])
        self.assertTrue(employer["verified"])
        self.assertEqual(employer["kind"], "employer_domain")
        self.assertFalse(board["verified"])

    def test_lifecycle_records_events_and_rejects_invalid_jump(self) -> None:
        """Keep current state plus an immutable audit of every agent/manual transition."""
        job = job_from_fixture(self.fixtures[0])
        with tempfile.TemporaryDirectory() as temp:
            with JobStore(Path(temp) / "jobs.sqlite3") as store:
                store.upsert_job(job)
                self.assertTrue(store.set_status(job.id, "saved", actor="manual"))
                self.assertTrue(
                    store.set_status(job.id, "ready_to_apply", actor="agent_c")
                )
                with self.assertRaises(ValueError):
                    store.set_status(job.id, "interviewing", actor="agent_c")
                state = store.application_state(job.id)
                events = store.application_events(job.id)
        self.assertEqual(state["status"], "ready_to_apply")
        self.assertEqual([item["to_status"] for item in events], [
            "new", "saved", "ready_to_apply"
        ])
        self.assertEqual(events[-1]["actor"], "agent_c")

    def test_agent_b_handoff_is_exact_fresh_and_integrity_bound(self) -> None:
        """Agent C must consume the reviewed role, URL, gates, and timestamp unchanged."""
        now = datetime.now(timezone.utc)
        job = job_from_fixture(self.fixtures[0])
        record = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "geography_eligible": True,
            "analysis": {
                "recommendation": "apply",
                "live_verified": True,
                "direct_domain_verified": True,
                "verified_at": now.isoformat(),
                "freshness": {"fresh": True, "freshness_window_hours": 24},
            },
        }
        handoff = build_agent_c_handoff(record, created_at=now.isoformat())
        review = {"records": [record], "agent_c_handoffs": [handoff]}
        analysis, validated = validate_agent_c_handoff(review, job, now=now)
        self.assertEqual(analysis["recommendation"], "apply")
        self.assertEqual(validated["job_id"], job.id)
        tampered = json.loads(json.dumps(review))
        tampered["agent_c_handoffs"][0]["job_url"] += "?changed=1"
        with self.assertRaises(ValueError):
            validate_agent_c_handoff(tampered, job, now=now)

    def test_applying_lifecycle_immediately_suppresses_aliases(self) -> None:
        """Synchronize SQLite lifecycle state with cross-board rediscovery suppression."""
        direct = job_from_fixture({
            **self.fixtures[0],
            "url": "https://jobs.example.test/jobs/recruiting-coordinator",
        })
        alias = job_from_fixture({
            **self.fixtures[0],
            "url": "https://www.linkedin.com/jobs/view/987654",
        })
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with JobStore(root / "jobs.sqlite3") as store:
                store.upsert_job(direct)
                _transition_application(
                    store, root, direct, "ready_to_apply", actor="agent_c"
                )
                _transition_application(store, root, direct, "applying", actor="agent_c")
                new_jobs, suppressed = partition_previously_applied(
                    [alias], root / "data" / "applied_jobs.json"
                )
                self.assertEqual(new_jobs, [])
                self.assertEqual([item.id for item in suppressed], [alias.id])
                _transition_application(
                    store, root, direct, "ready_to_apply", actor="agent_c"
                )
                new_jobs, suppressed = partition_previously_applied(
                    [alias], root / "data" / "applied_jobs.json"
                )
                state = store.application_state(direct.id)
        self.assertEqual([item.id for item in new_jobs], [alias.id])
        self.assertEqual(suppressed, [])
        self.assertEqual(state["status"], "ready_to_apply")

    def test_agent_c_consumes_persisted_handoff_without_recalculating_agent_b(self) -> None:
        """Exercise the CLI boundary from exact Agent B review to ready-to-apply packet."""
        now = datetime.now(timezone.utc)
        job = job_from_fixture(self.fixtures[0])
        match = score_job(job, self.profile)
        finding = RecruiterAgent().inspect(job, fresh_days=30)
        analysis = MatchAnalystAgent().analyze(
            job, match, finding, threshold=72, fresh_days=30
        ).to_dict()
        analysis.update({
            "recommendation": "apply",
            "live_verified": True,
            "direct_domain_verified": True,
            "verification_url": job.url,
            "verified_at": now.isoformat(),
            "freshness": {"fresh": True, "freshness_window_hours": 168},
        })
        record = {
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "geography_eligible": True,
            "analysis": analysis,
        }
        handoff = build_agent_c_handoff(record, created_at=now.isoformat())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "jobs.sqlite3"
            review = root / "reviews.json"
            application_profile = root / "application_profile.json"
            with JobStore(database) as store:
                store.upsert_job(job)
                store.upsert_match(match)
            write_json(review, {
                "schema_version": 2,
                "records": [record],
                "agent_c_handoffs": [handoff],
            })
            write_json(application_profile, {
                "contact": {
                    "first_name": "Demo", "last_name": "Candidate",
                    "email": "demo@example.test", "phone": "555-0100",
                    "city": "San Jose", "state": "CA", "country": "United States",
                },
                "links": {},
                "eligibility": {
                    "authorized_to_work_us": True, "requires_sponsorship": False,
                },
                "preferences": {}, "standard_answers": {},
                "consents": {"use_contact_for_applications": True},
            })
            args = SimpleNamespace(
                job_id=job.id,
                database=database,
                agent_b_review=review,
                handoff_max_age_hours=24,
                application_profile=application_profile,
                resume=ROOT / "README.md",
            )
            self.assertEqual(command_agent_c(args, root), 0)
            packet_path = root / "data" / "application_packets" / f"{job.id}.json"
            complete_packet = json.loads(packet_path.read_text(encoding="utf-8"))
            with JobStore(database) as store:
                ready_state = store.application_state(job.id)
            incomplete_profile = json.loads(application_profile.read_text(encoding="utf-8"))
            incomplete_profile["contact"]["phone"] = ""
            write_json(application_profile, incomplete_profile)
            self.assertEqual(command_agent_c(args, root), 0)
            incomplete_packet = json.loads(packet_path.read_text(encoding="utf-8"))
            with JobStore(database) as store:
                state = store.application_state(job.id)
                events = store.application_events(job.id)
        self.assertEqual(
            complete_packet["agent_b_handoff"]["handoff_sha256"],
            handoff["handoff_sha256"],
        )
        self.assertEqual(complete_packet["match"]["verified_at"], analysis["verified_at"])
        self.assertEqual(ready_state["status"], "ready_to_apply")
        self.assertIn("contact.phone", incomplete_packet["unresolved_questions"])
        self.assertEqual(state["status"], "saved")
        self.assertEqual(events[-1]["actor"], "agent_c")

    def test_tailoring_plan_separates_supported_and_unsupported_keywords(self) -> None:
        """Use resume evidence for tailoring and quarantine unsupported ATS suggestions."""
        job = job_from_fixture(self.fixtures[0])
        match = score_job(job, self.profile)
        finding = RecruiterAgent().inspect(job, fresh_days=30)
        analysis = MatchAnalystAgent().analyze(
            job,
            match,
            finding,
            threshold=72,
            fresh_days=30,
            resume_matcher={
                "overall_score": 80,
                "injectable_keywords": ["Greenhouse ATS", "Workday"],
                "missing_keywords": ["Workday"],
                "recommendations": ["Add one measurable outcome"],
            },
        )
        plan = analysis.tailoring
        self.assertIn("Greenhouse ATS", plan["priority_keywords_supported_by_resume"])
        self.assertIn("Workday", plan["do_not_add_without_resume_evidence"])
        self.assertFalse(plan["auto_edit_performed"])
        self.assertTrue(plan["required_human_review"])

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

    def test_browser_submit_is_blocked_for_unresolved_packet(self) -> None:
        """Reject incomplete fill-and-submit packets before browser or lifecycle changes."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            packet = root / "packet.json"
            approval = root / "approval.json"
            write_json(packet, {
                "job": {
                    "id": "job-incomplete",
                    "url": "https://jobs.example.test/apply/incomplete",
                    "title": "Recruiting Coordinator",
                },
                "candidate": {"resume_path": str(ROOT / "README.md")},
                "unresolved_questions": ["eligibility.requires_sponsorship"],
            })
            runner = BrowserUseRunner(packet)
            runner.write_approval_template(approval)
            receipt = json.loads(approval.read_text(encoding="utf-8"))
            receipt.update({
                "decision": "approved",
                "allowed_action": "fill_and_submit",
                "approved_by": "test reviewer",
                "approved_at": datetime.now(timezone.utc).isoformat(),
            })
            write_json(approval, receipt)
            plan = runner.plan("fill_and_submit", approval)
            self.assertEqual(plan.approval_status, "blocked")
            self.assertTrue(plan.blockers)
            with self.assertRaises(BrowserUseError):
                runner.validate_execution(approval, "fill_and_submit")

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
