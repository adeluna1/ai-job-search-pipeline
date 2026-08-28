"""Deterministic large-scale acceptance checks for recruiting-job quality.

The suite uses synthetic employers and postings only. It exercises validation,
deduplication, role and geography gates, deterministic scoring, SQLite storage,
and ranked retrieval without contacting job boards or submitting applications.
Only aggregate metrics are written to the acceptance report.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_triage import deduplicate_candidates
from .geography import evaluate_geography
from .jobs import Job, job_from_fixture, validate_job
from .matching import score_job
from .role_scope import evaluate_role_scope
from .storage import JobStore
from .util import utc_now, write_json


@dataclass(frozen=True)
class AcceptanceThresholds:
    """Minimum scale and quality required from every synthetic trial."""

    minimum_outputs: int = 200
    minimum_top_50_precision: float = 0.98
    minimum_strong_fit_rate: float = 0.80
    minimum_duplicates: int = 40


@dataclass(frozen=True)
class TrialDefinition:
    """One deterministic mix of relevant, out-of-scope, and duplicate jobs."""

    name: str
    base_jobs: int
    eligible_ratio: float
    geography_pass_ratio: float
    duplicate_every: int


TRIALS = (
    TrialDefinition("coordinator_balanced", 640, 0.62, 0.86, 8),
    TrialDefinition("expanded_junior_titles", 720, 0.56, 0.82, 9),
    TrialDefinition("noise_heavy_discovery", 800, 0.43, 0.78, 10),
)

TARGET_TITLES = (
    "Recruiting Coordinator",
    "Recruitment Coordinator",
    "Talent Acquisition Coordinator",
    "Recruiting Operations Coordinator",
    "Talent Operations Coordinator",
    "Candidate Experience Coordinator",
    "Recruiting Program Coordinator",
    "Sourcing Coordinator",
    "Associate Recruiter",
    "Recruiting Associate",
    "Talent Acquisition Specialist",
    "University Recruiting Coordinator",
)

NOISE_TITLES = (
    "Senior Recruiting Manager",
    "Director of Talent Acquisition",
    "Technical Recruiter",
    "Software Engineer",
    "Human Resources Manager",
    "Account Executive",
    "Recruiting Career Overview",
    "Head of Recruiting",
)

IN_SCOPE_LOCATIONS = (
    ("San Jose, CA", "hybrid"),
    ("San Francisco, CA", "onsite"),
    ("Oakland, CA", "hybrid"),
    ("Sunnyvale, CA", "onsite"),
    ("Remote, United States", "remote"),
    ("Remote, California", "remote"),
)

OUT_OF_SCOPE_LOCATIONS = (
    ("New York, NY", "onsite"),
    ("Austin, TX", "hybrid"),
    ("Remote, Canada", "remote"),
)

REQUESTED_LOCATIONS = (
    "San Francisco Bay Area",
    "San Jose",
    "Oakland",
    "Remote United States",
    "Remote California",
)

QUERY = "Recruiting Coordinator OR Talent Acquisition Coordinator"


def _synthetic_profile() -> dict[str, Any]:
    """Return a contact-free profile rich enough to exercise real scoring."""
    return {
        "candidate": {
            "name": "Synthetic Candidate",
            "location": "California",
            "summary": "Recruiting operations specialist with ATS and scheduling experience.",
            "years_experience": 5,
            "target_roles": list(TARGET_TITLES[:8]),
            "preferred_locations": [
                "San Francisco",
                "San Jose",
                "Oakland",
                "Remote",
            ],
            "accepted_work_modes": ["remote", "hybrid", "onsite"],
            "skills": [
                "recruiting coordination",
                "recruiting operations",
                "candidate experience",
                "interview scheduling",
                "high-volume scheduling",
                "Greenhouse ATS",
                "Ashby ATS",
                "applicant tracking systems",
                "candidate communication",
                "onboarding",
                "data analysis and reporting",
                "project management",
            ],
            "responsibility_keywords": [
                "schedule interviews",
                "coordinate interviews",
                "candidate communication",
                "candidate experience",
                "maintain ATS data",
                "partner with recruiters",
                "support onboarding",
                "reporting and analytics",
            ],
            "evidence": [
                {
                    "skill": "interview scheduling",
                    "evidence": "Coordinated high-volume interview loops across time zones.",
                },
                {
                    "skill": "applicant tracking systems",
                    "evidence": "Maintained accurate candidate stages in an ATS.",
                },
            ],
            "exclude_title_terms": [
                "senior",
                "manager",
                "director",
                "head of",
                "software engineer",
                "account executive",
            ],
        },
        "scoring": {
            "strong_fit_threshold": 72,
            "weights": {
                "title": 0.35,
                "skills": 0.3,
                "experience": 0.15,
                "location": 0.1,
                "responsibilities": 0.1,
            },
            "ai_blend_weight": 0.3,
        },
        "source": {"contact_details_included": False},
    }


def _description(index: int) -> str:
    return (
        "Responsibilities include coordinating interviews and scheduling interviews across "
        "high-volume hiring teams. Qualifications include careful calendar management and "
        "Maintain ATS data in Greenhouse ATS and Ashby ATS, communicate with candidates, "
        "partner with recruiters and hiring teams, support onboarding, improve candidate "
        "experience, and prepare reporting and analytics. Manage calendar changes, document "
        "recruiting operations, protect candidate confidentiality, and deliver clear status "
        f"updates for synthetic requisition {index:04d}."
    )


def generate_trial_jobs(definition: TrialDefinition) -> list[Job]:
    """Generate a stable synthetic corpus plus canonical-URL duplicates."""
    target_count = int(definition.base_jobs * definition.eligible_ratio)
    geography_pass_count = int(target_count * definition.geography_pass_ratio)
    jobs: list[Job] = []
    for index in range(definition.base_jobs):
        target = index < target_count
        title = (
            TARGET_TITLES[index % len(TARGET_TITLES)]
            if target
            else NOISE_TITLES[index % len(NOISE_TITLES)]
        )
        location_pool = IN_SCOPE_LOCATIONS if index < geography_pass_count else OUT_OF_SCOPE_LOCATIONS
        location, work_mode = location_pool[index % len(location_pool)]
        slug = f"synthetic-employer-{index:04d}"
        fixture = {
            "url": f"https://jobs.ashbyhq.com/{slug}/requisition-{index:04d}",
            "title": title,
            "company": f"Synthetic Employer {index:04d}",
            "location": location,
            "work_mode": work_mode,
            "employment_type": "Full-time",
            "posted_date": "2026-08-24",
            "description": _description(index),
            "required_years": 2,
            "required_skills": [
                "interview scheduling",
                "applicant tracking systems",
                "candidate communication",
            ],
            "responsibilities": [
                "schedule interviews",
                "maintain ATS data",
                "candidate communication",
            ],
            "source": "synthetic-acceptance",
        }
        jobs.append(job_from_fixture(fixture))
        if index % definition.duplicate_every == 0:
            jobs.append(job_from_fixture({
                **fixture,
                "url": fixture["url"] + "?utm_source=synthetic-duplicate",
                "source": "synthetic-duplicate",
            }))
    return jobs


def _private_data_findings(records: list[dict[str, Any]]) -> int:
    """Count contact-shaped values in bounded output records without returning them."""
    address_like = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
    phone_like = re.compile(
        r"(?<!\d)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)"
    )
    findings = 0
    for record in records:
        for key, value in record.items():
            if key == "job_id" or not isinstance(value, str):
                continue
            findings += len(address_like.findall(value)) + len(phone_like.findall(value))
    return findings


def _run_trial(
    definition: TrialDefinition,
    thresholds: AcceptanceThresholds,
    database_path: Path,
) -> dict[str, Any]:
    profile = _synthetic_profile()
    generated = generate_trial_jobs(definition)
    valid_jobs = [job for job in generated if validate_job(job)[0]]
    unique_jobs, duplicate_rows = deduplicate_candidates(valid_jobs)
    role_jobs = [job for job in unique_jobs if evaluate_role_scope(job, QUERY).eligible]
    eligible_jobs = [
        job for job in role_jobs if evaluate_geography(job, REQUESTED_LOCATIONS).eligible
    ]
    scores = {job.id: score_job(job, profile) for job in eligible_jobs}

    with JobStore(database_path) as store:
        for job in eligible_jobs:
            store.upsert_job(job)
            store.upsert_match(scores[job.id])
        ranked = store.ranked(0)

    bounded_outputs = [
        {
            "job_id": record["id"],
            "title": record["title"],
            "company": record["company"],
            "score": record["final_score"],
            "fit_label": record["fit_label"],
        }
        for record in ranked
    ]
    top = bounded_outputs[:50]
    top_relevant = sum(
        1
        for record in top
        if any(marker.casefold() in record["title"].casefold() for marker in (
            "recruit", "talent", "candidate experience", "sourcing"
        ))
    )
    senior_markers = ("senior", "manager", "director", "head", "chief", "vice president")
    senior_outputs = sum(
        1
        for record in bounded_outputs
        if any(marker in record["title"].casefold() for marker in senior_markers)
    )
    strong_count = sum(record["fit_label"] in {"strong", "excellent"} for record in bounded_outputs)
    precision = round(top_relevant / max(1, len(top)), 3)
    strong_rate = round(strong_count / max(1, len(bounded_outputs)), 3)
    private_findings = _private_data_findings(bounded_outputs)

    failures: dict[str, dict[str, Any]] = {}
    checks = {
        "eligible_outputs": (len(bounded_outputs), thresholds.minimum_outputs, ">="),
        "top_50_precision": (precision, thresholds.minimum_top_50_precision, ">="),
        "strong_fit_rate": (strong_rate, thresholds.minimum_strong_fit_rate, ">="),
        "duplicates_removed": (len(duplicate_rows), thresholds.minimum_duplicates, ">="),
        "senior_roles_in_outputs": (senior_outputs, 0, "=="),
        "private_data_findings": (private_findings, 0, "=="),
    }
    for name, (actual, expected, operator) in checks.items():
        passed = actual >= expected if operator == ">=" else actual == expected
        if not passed:
            failures[name] = {"actual": actual, "expected": expected, "operator": operator}

    return {
        "name": definition.name,
        "input_jobs": len(generated),
        "valid_jobs": len(valid_jobs),
        "unique_jobs": len(unique_jobs),
        "duplicates_removed": len(duplicate_rows),
        "role_eligible": len(role_jobs),
        "eligible_outputs": len(bounded_outputs),
        "strong_fit_outputs": strong_count,
        "strong_fit_rate": strong_rate,
        "top_50_precision": precision,
        "senior_roles_in_outputs": senior_outputs,
        "private_data_findings": private_findings,
        "status": "passed" if not failures else "failed",
        "failures": failures,
    }


def run_acceptance_suite(
    *, thresholds: AcceptanceThresholds | None = None
) -> dict[str, Any]:
    """Run three offline scale trials and return aggregate-only evidence."""
    limits = thresholds or AcceptanceThresholds()
    with tempfile.TemporaryDirectory(prefix="expedient-acceptance-") as temp:
        trials = [
            _run_trial(definition, limits, Path(temp) / f"{definition.name}.sqlite3")
            for definition in TRIALS
        ]
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "mode": "synthetic_offline_no_external_actions",
        "status": "passed" if all(item["status"] == "passed" for item in trials) else "failed",
        "trial_count": len(trials),
        "total_input_jobs": sum(item["input_jobs"] for item in trials),
        "total_eligible_outputs": sum(item["eligible_outputs"] for item in trials),
        "trials": trials,
    }


def write_acceptance_report(report: dict[str, Any], path: Path) -> Path:
    """Write one aggregate-only JSON report and return its path."""
    write_json(path, report)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic recruiting acceptance checks.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports") / "recruiting_acceptance.json",
        help="Aggregate JSON report path.",
    )
    args = parser.parse_args(argv)
    report = run_acceptance_suite()
    output = write_acceptance_report(report, args.output)
    print(
        f"Acceptance {report['status']}: {report['total_input_jobs']} inputs, "
        f"{report['total_eligible_outputs']} eligible outputs across {report['trial_count']} trials."
    )
    print(f"Aggregate report: {output.resolve()}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
