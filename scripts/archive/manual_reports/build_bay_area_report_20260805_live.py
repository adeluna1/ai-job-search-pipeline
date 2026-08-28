"""Build the August 5 live-only Bay Area recruiting-coordinator report."""

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
        "company": "Vitalize",
        "title": "Recruiting Operations Coordinator",
        "url": "https://jobs.ashbyhq.com/vitalize/c781639e-28a0-4abe-b922-36e752596f2b",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "Full-time",
        "posted_date": "2026-08-04",
        "window": "Last 3 days",
        "verification": "Ashby published Aug 4; the live application displayed 20 inputs and Submit Application.",
        "scope": "Exact recruiting-operations coordinator match.",
    },
    {
        "company": "Factory",
        "title": "Recruiting Coordinator",
        "url": "https://jobs.ashbyhq.com/factory/62dc232f-34b7-4bc6-ab76-7b0d38e63e8d",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-03",
        "window": "Last 3 days",
        "verification": "Ashby published Aug 3; the live application displayed 12 inputs and Submit Application.",
        "scope": "Exact recruiting coordinator match; five office days are required.",
    },
    {
        "company": "Serval",
        "title": "Recruiting Coordinator",
        "url": "https://jobs.ashbyhq.com/Serval/e05ad60f-544d-4e04-99d0-586573ceac04",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-04",
        "salary": "$75,000-$100,000 + equity",
        "window": "Last 3 days",
        "verification": "Ashby published Aug 4; the live application displayed candidate inputs and Submit Application.",
        "scope": "Exact recruiting coordinator match.",
    },
    {
        "company": "Muon Space",
        "title": "Recruiting Coordinator",
        "url": "https://job-boards.greenhouse.io/muonspace/jobs/5204018007",
        "location": "San Jose, CA",
        "work_mode": "hybrid",
        "employment_type": "Full-time",
        "posted_date": "2026-08-03",
        "window": "Last 3 days",
        "verification": "Greenhouse marked the role New; its form displayed 20 inputs and Submit application.",
        "scope": "Exact recruiting coordinator match; three to four onsite days are required.",
    },
    {
        "company": "Roblox",
        "title": "Recruiting Operations Coordinator (Short Term)",
        "url": "https://careers.roblox.com/jobs/8099348",
        "location": "San Mateo, CA (Bay Area)",
        "work_mode": "hybrid",
        "employment_type": "Temporary",
        "posted_date": "2026-08-03",
        "window": "Last 3 days",
        "verification": "The current Roblox employer page displayed role ID 38747 and an enabled Apply Now control.",
        "scope": "Exact recruiting-operations coordinator match; this is a short-term role.",
    },
    {
        "company": "TikTok",
        "title": "TA Specialist - TAPM - San Jose (Third-party Associate)",
        "url": "https://lifeattiktok.com/search/7650290210814839093",
        "location": "San Jose, CA",
        "work_mode": "onsite",
        "employment_type": "12-month temporary assignment",
        "posted_date": "2026-08-04",
        "salary": "$32-$40/hour",
        "window": "Last 3 days",
        "verification": "The TikTok employer page displayed job code A187902 and an active Apply to this job link.",
        "scope": "Close recruiting-operations match; employment is through a third-party agency.",
    },
    {
        "company": "Rodan Builders",
        "title": "HR Coordinator",
        "url": "https://rodanbuilders.com/careers/construction-job-openings/hr-coordinator/",
        "location": "Hayward, CA (Bay Area)",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-03",
        "salary": "$32-$35/hour",
        "window": "Last 3 days",
        "verification": "The employer page displayed the full role, recruiting duties, and an active Apply Now control.",
        "scope": "Broader HR coordinator role with recruiting, interview, career-fair, and onboarding ownership.",
    },
    {
        "company": "Four Seasons",
        "title": "People and Culture Coordinator (HR)",
        "url": "https://careers.fourseasons.com/us/en/job/REQ10362500/People-and-Culture-Coordinator-HR",
        "location": "East Palo Alto, CA (Bay Area)",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-03",
        "window": "Last 3 days",
        "verification": "The employer page displayed requisition REQ10362500 and a direct Apply Now link.",
        "scope": "Broader people-and-culture coordinator role; less recruiting-focused than the top matches.",
    },
    {
        "company": "See's Candies",
        "title": "Human Resources Coordinator",
        "url": "https://sees.wd1.myworkdayjobs.com/en-US/Sees_Candies/job/Daly-City-CA/Human-Resources-Coordinator_JR105610",
        "location": "Daly City, CA (Bay Area)",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-05",
        "window": "Last 24h",
        "verification": "Workday showed Posted Today, requisition JR105610, and a direct Apply link.",
        "scope": "Broader HR coordinator role; verify how much recruiting work is included before prioritizing.",
    },
    {
        "company": "Clera",
        "title": "Recruiter",
        "url": "https://jobs.ashbyhq.com/Clera/4a88cad8-2c5a-41b7-8ed7-e5880483333c",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "2026-08-04",
        "window": "Last 3 days",
        "verification": "Ashby published Aug 4; the live application displayed candidate inputs and Submit Application.",
        "scope": "Adjacent full-cycle recruiter role rather than a coordinator title; treat as a stretch option.",
    },
]


def _source_jobs() -> list[dict]:
    jobs: list[dict] = []
    for path in sorted((ROOT / "data").glob("raw_20260805_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        jobs.extend(payload.get("jobs", []))
    return jobs


def _find_source_item(items: list[dict], company: str, title: str) -> dict:
    company_key = company.casefold().replace(" hotels limited", "")
    title_key = title.casefold()
    for item in items:
        source_company = str(item.get("company", "")).casefold().replace(" hotels limited", "")
        if source_company == company_key and str(item.get("title", "")).casefold() == title_key:
            return item
    raise RuntimeError(f"No Agent A source record found for {company} - {title}")


def build() -> tuple[Path, Path]:
    profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    resume_text = extract_docx_text(Path(r"C:\path\to\resume.docx"))
    source_items = _source_jobs()
    records: list[dict] = []

    for selected in SELECTED:
        source = _find_source_item(source_items, selected["company"], selected["title"])
        job = Job.from_dict(source)
        job.id = stable_id(selected["url"])
        job.url = selected["url"]
        job.company = selected["company"]
        job.location = selected["location"]
        job.work_mode = selected["work_mode"]
        job.employment_type = selected["employment_type"]
        job.posted_date = selected["posted_date"]
        job.salary = selected.get("salary") or job.salary
        job.source = "agent-a-jobspy; live-employer-form-verified-2026-08-05"
        job.raw["verification"] = selected["verification"]

        match = score_job(job, profile, resume_text)
        record = {**job.to_dict(), **match.to_dict()}
        record["id"] = job.id
        record["status"] = "new"
        record["recommendation"] = (
            f"{selected['window']} | {selected['scope']} {selected['verification']}"
        )
        record["notes"] = (
            "Weighted against the candidate's corrected resume. Excluded if previously applied, "
            "previously sent, closed, stale, or lacking a live employer application control."
        )
        records.append(record)

    records.sort(key=lambda record: (-float(record["final_score"]), record["company"].casefold()))
    return export_reports(
        records,
        ROOT / "reports",
        threshold=72,
        prefix="recruiting_coordinator_bay_area_live_24h_3d_2026-08-05",
        title="10 live-verified Bay Area recruiting matches",
        subtitle=(
            "Posted within the last 24 hours or three days, not present in the applied/closed "
            "registries, and rechecked on the employer site on Aug. 5, 2026. Ranked against "
            "the candidate's corrected resume. The lower-ranked cards are adjacent HR or "
            "full-cycle recruiting options, clearly labeled in each recommendation."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
