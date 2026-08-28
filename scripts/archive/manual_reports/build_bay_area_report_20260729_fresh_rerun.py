"""Build the strict fresh rerun of the July 29 Bay Area recruiting report."""

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


JOBS = [
    {
        "title": "Recruitment Coordinator (Contract)",
        "company": "Private Company",
        "location": "San Francisco, CA (potential remote)",
        "work_mode": "hybrid",
        "employment_type": "6-month contract",
        "salary": "$70/hour",
        "url": "https://www.linkedin.com/jobs/view/recruitment-coordinator-at-private-company-4434786557",
        "window": "Last 24h",
        "posted_date": "9 hours ago",
        "verification": (
            "LinkedIn currently shows Apply and 9 hours ago. The confidential client is "
            "an AI technology company; the posting says San Francisco with potential remote work."
        ),
        "required_years": 2,
        "description": (
            "Coordinate high-volume interviews, debriefs, and reference checks across complex "
            "calendars. Serve as the primary candidate contact, partner with recruiters and "
            "hiring managers, improve recruiting operations workflows, support scaling projects, "
            "and use AI tools to improve efficiency. Requires two or more years of recruiting "
            "coordination, scheduling, or talent acquisition operations experience."
        ),
    },
    {
        "title": "Recruiting Coordinator - Contract",
        "company": "Hinge Health",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "Contract",
        "salary": "$23.50-$27.00/hour",
        "url": "https://jobs.ashbyhq.com/hinge-health/66a7a845-a001-4dcf-a514-012af9d6f61a/",
        "window": "Last 24h",
        "posted_date": "18 hours ago",
        "verification": (
            "The current LinkedIn result shows 18 hours ago, and the employer's Ashby page "
            "still displays its full application form."
        ),
        "required_years": 1,
        "description": (
            "Own high-volume interview scheduling, candidate communication, calendar changes, "
            "and interview-panel readiness. Maintain accurate candidate records, stages, and "
            "feedback forms in Ashby. Partner with Talent Partners and hiring managers and "
            "deliver an inclusive candidate experience. Requires one or more years in "
            "administration, coordination, or a customer-facing role plus Google Workspace."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "IXL Learning",
        "location": "San Mateo, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "$25-$31/hour",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-at-ixl-learning-4434348415",
        "window": "Last 24h",
        "posted_date": "19 hours ago",
        "verification": (
            "LinkedIn's current IXL company-results page shows 19 hours ago and the job page "
            "still displays Apply with the complete position description."
        ),
        "required_years": 1,
        "description": (
            "Host onsite candidates, schedule a high volume of interviews, answer candidate "
            "questions, manage the recruiting pipeline, maintain organized ATS records, and "
            "partner with recruiters and hiring managers to refine recruiting processes. "
            "Recruiting, HR, or administrative coordination experience is preferred, together "
            "with Greenhouse and Google Workspace."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Handshake",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Contract",
        "salary": "$35-$40/hour",
        "url": "https://jobs.ashbyhq.com/handshake/378de96b-1d65-4b94-8312-ecb14083d879/",
        "window": "Last 3 days",
        "posted_date": "2 days ago",
        "verification": (
            "LinkedIn shows 2 days ago, and Handshake's employer-hosted Ashby page still "
            "displays the full application."
        ),
        "required_years": 1,
        "description": (
            "Schedule and coordinate interviews, deliver a people-first candidate experience, "
            "maintain accurate recruiting-tool data, communicate professionally with candidates, "
            "and support strategic coordination projects. Requires at least one year of "
            "scheduling or coordination experience; Ashby experience is a bonus."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Normal Computing",
        "location": "Palo Alto, CA",
        "work_mode": "hybrid",
        "employment_type": "Full-time",
        "salary": "$100,000-$120,000 + equity",
        "url": "https://jobs.ashbyhq.com/NormalComputing/db59c5a4-0630-4b69-9590-a8b44c39c8aa",
        "window": "Last 3 days",
        "posted_date": "2 days ago",
        "verification": (
            "Monster shows Posted 2 days ago, and Normal Computing's employer-hosted Ashby "
            "application remains open."
        ),
        "required_years": 2,
        "description": (
            "Own interview scheduling and candidate movement across global offices, maintain "
            "Ashby pipelines, stages, templates, offers, and reporting, publish job postings, "
            "document recruiting processes, and use automation and AI tools to improve workflows. "
            "Requires recruiting coordination or operations experience, ATS ownership, strong "
            "organization, proactive communication, Slack, Notion, and Google Workspace."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Luma AI",
        "location": "Palo Alto, CA",
        "work_mode": "onsite",
        "employment_type": "Contract-to-hire",
        "salary": "$45-$60/hour",
        "url": "https://jobs.lever.co/LumaAi/75564f95-15c3-4363-acf3-3b14fefe109b/apply",
        "window": "Last 3 days",
        "posted_date": "2 days ago",
        "verification": (
            "LinkedIn shows 2 days ago, and Luma AI's employer-hosted Lever application "
            "still accepts a resume and candidate details."
        ),
        "required_years": 3,
        "description": (
            "Own complex interview scheduling across time zones, candidate communications, and "
            "onsite and virtual interview logistics in Palo Alto. Maintain recruiting operations "
            "and ATS accuracy, create high-touch candidate experiences, implement new workflows, "
            "and use technology and automation to improve processes. Requires three or more years "
            "of recruiting coordination in a high-growth startup and hands-on ATS experience."
        ),
    },
]

VERIFIED_ACTIVE_URLS = {
    "https://jobs.ashbyhq.com/NormalComputing/db59c5a4-0630-4b69-9590-a8b44c39c8aa",
}


def build() -> tuple[Path, Path]:
    """Score only roles whose live application form passed the final browser check."""
    profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    resume_text = extract_docx_text(
        Path(r"C:\path\to\resume.docx")
    )
    records: list[dict] = []

    for item in JOBS:
        if item["url"].rstrip("/") not in VERIFIED_ACTIVE_URLS:
            continue
        job = Job(
            id=stable_id(item["url"]),
            url=item["url"],
            title=item["title"],
            company=item["company"],
            location=item["location"],
            work_mode=item["work_mode"],
            employment_type=item["employment_type"],
            posted_date=item["posted_date"],
            salary=item["salary"],
            description=item["description"],
            source="live-application-form-verified-2026-07-29",
            required_years=item["required_years"],
        )
        score = score_job(job, profile, resume_text)
        record = {**job.to_dict(), **score.to_dict()}
        record["id"] = job.id
        record["status"] = "new"
        record["recommendation"] = f"{item['window']} - {item['verification']}"
        record["notes"] = (
            "Resume-weighted against the candidate's corrected resume. "
            "A live browser check reached the enabled application form and displayed "
            "candidate inputs plus Submit Application."
        )
        records.append(record)

    records.sort(
        key=lambda record: (
            0 if record["recommendation"].startswith("Last 24h") else 1,
            -float(record["final_score"]),
            record["company"].casefold(),
        )
    )
    return export_reports(
        records,
        ROOT / "reports",
        threshold=72,
        prefix="recruiting_roles_bay_area_san_jose_fresh_rerun_2026-07-29",
        title="Corrected live-only Bay Area recruiting report",
        subtitle=(
            "Fail-closed report: a role appears only after its live employer application "
            "opens an enabled form. Hinge Health, Handshake, Luma AI, IXL Learning, and the "
            "confidential LinkedIn listing were removed after live verification failed. "
            "The remaining role is weighted against the candidate's corrected resume."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
