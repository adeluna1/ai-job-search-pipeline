"""Build the August 5 live-only nationwide remote recruiting report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_pipeline.jobs import Job
from job_pipeline.matching import score_job
from job_pipeline.report import export_reports
from job_pipeline.resume import extract_docx_text
from job_pipeline.util import stable_id


SELECTED = [
    {
        "company": "Mercury Insurance",
        "title": "Talent Acquisition Coordinator",
        "url": "https://careers-mercuryinsurance.icims.com/jobs/6471/talent-acquisition-coordinator/job?in_iframe=1",
        "location": "United States (Remote)",
        "work_mode": "remote",
        "employment_type": "Full-time",
        "posted_date": "2026-07-30",
        "salary": "$36,381-$77,881/year; CA typical range $55,056-$77,290",
        "required_years": 1.0,
        "description": """
        The Talent Acquisition Coordinator supports administration, coordination, and logistics
        across the recruiting process and creates a positive candidate experience. Responsibilities
        include scheduling phone screens, assessments, and interviews; coordinating background
        checks, references, onboarding, new-hire paperwork, and I-9 verification; maintaining
        recruiting documents and vendor invoices; supporting employer branding; reviewing resumes;
        and sourcing for entry-level and support roles. The role requires strong communication,
        customer service, follow-up, organization, Microsoft Office 365, and experience with an
        applicant tracking system. Prior interview scheduling and coordination experience is
        preferred. The position is US-Remote and works Monday through Friday, 8am-5pm Pacific.
        """,
        "verification": (
            "Employer iCIMS page showed the full requisition, US-Remote location, Remote position "
            "type, nationwide state pay bands, and an active Apply control on Aug. 5, 2026."
        ),
        "freshness": (
            "LinkedIn showed the opening as six days old; CareerBuilder showed a two-day repost."
        ),
        "caution": "An in-person interview may be required during the hiring process.",
    },
    {
        "company": "Tarpon Health",
        "title": "Recruiting Coordinator",
        "url": "https://jobs.gusto.com/postings/tarpon-health-inc-recruiting-coordinator-07a179a0-a2f4-4e26-b0e6-800a269d20a8",
        "location": "United States (Remote)",
        "work_mode": "remote",
        "employment_type": "Full-time",
        "posted_date": "2026-07-30",
        "salary": "$60,000-$80,000/year",
        "required_years": 3.0,
        "description": """
        The Recruiting Coordinator owns full-cycle recruiting across corporate, technical, and
        operations teams from sourcing and screening through interview coordination and offer
        acceptance. Responsibilities include managing multiple requisitions, partnering with hiring
        managers, sourcing passive candidates with LinkedIn Recruiter, conducting phone interviews,
        coordinating interviews end-to-end, maintaining accurate ATS data and dashboards, supporting
        offers and onboarding, improving recruiting processes, tracking hiring metrics, and providing
        an organized candidate experience. Requirements include three or more years of full-cycle
        recruiting, technical or corporate recruiting, strong sourcing, ATS experience, communication,
        relationship building, and organization. Startup, high-growth, engineering, AI, or revenue-cycle
        recruiting experience is preferred. This is a remote full-time role.
        """,
        "verification": (
            "Employer Gusto page showed the complete posting, Remote and Full time labels, salary, "
            "and an active Apply for Recruiting Coordinator control on Aug. 5, 2026."
        ),
        "freshness": "Indeed discovered the employer posting with a July 30 date.",
        "caution": (
            "Despite the coordinator title, this is a full-cycle recruiter role with meaningful "
            "passive sourcing and closing ownership."
        ),
    },
]


def build() -> tuple[Path, Path]:
    profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    resume_text = extract_docx_text(Path(r"C:\path\to\resume.docx"))
    records: list[dict] = []

    for selected in SELECTED:
        job = Job(
            id=stable_id(selected["url"]),
            url=selected["url"],
            title=selected["title"],
            company=selected["company"],
            location=selected["location"],
            work_mode=selected["work_mode"],
            employment_type=selected["employment_type"],
            posted_date=selected["posted_date"],
            salary=selected["salary"],
            description=" ".join(selected["description"].split()),
            source="agent-a-jobspy; webclaw-search-fallback; live-employer-verified-2026-08-05",
            required_years=selected["required_years"],
            raw={
                "verification": selected["verification"],
                "freshness": selected["freshness"],
            },
        )
        match = score_job(job, profile, resume_text)
        record = {**job.to_dict(), **match.to_dict()}
        record["status"] = "new"
        record["recommendation"] = (
            f"{selected['freshness']} {selected['verification']} "
            f"Watch-out: {selected['caution']}"
        )
        record["notes"] = (
            "Weighted against Albert Deluna's corrected resume. This fail-closed report excludes "
            "previously applied/sent roles, closed employer pages, stale posts, hybrid roles, and "
            "remote jobs limited to a single state or region."
        )
        records.append(record)

    records.sort(key=lambda item: (-float(item["final_score"]), item["company"].casefold()))
    return export_reports(
        records,
        ROOT / "reports",
        threshold=72,
        prefix="recruiting_coordinator_remote_us_live_7d_2026-08-05",
        title="Live nationwide-remote recruiting coordinator matches",
        subtitle=(
            "Only employer-verified, fully remote US roles discovered or reposted within the last "
            "seven days. Ranked against Albert Deluna's corrected resume on Aug. 5, 2026. The "
            "search intentionally returns fewer results instead of including stale or restricted jobs."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
