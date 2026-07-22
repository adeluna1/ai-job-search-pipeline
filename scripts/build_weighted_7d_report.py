"""Build a seven-day Bay Area report excluding locally tracked applications."""

from __future__ import annotations

import json
import re
from pathlib import Path

import build_weighted_24h_report as report


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


ROLE_SNAPSHOTS = [
    {
        "title": "Recruiting Coordinator",
        "company": "SPAN",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "Listed about 2 hours ago",
        "age_hours": 2,
        "freshness": "fresh",
        "freshness_label": "New — about 2h",
        "freshness_note": "The direct Ashby application is active; LinkedIn showed the role at about two hours old.",
        "salary": "$65,000–$85,000 + equity",
        "url": "https://jobs.ashbyhq.com/span/e8f22888-8ac3-41d3-9298-d13a2a23c502/",
        "source_name": "SPAN / Ashby",
        "required_years": None,
        "required_skills": [
            "recruiting coordination", "interview scheduling", "candidate communication",
            "candidate experience", "applicant tracking systems",
        ],
        "responsibilities": [
            "Coordinate interviews and recruiting logistics across hiring teams.",
            "Communicate with candidates and deliver an organized candidate experience.",
            "Maintain accurate recruiting data and support process improvements.",
        ],
        "description": (
            "Recruiting Coordinator supporting interview scheduling, candidate communication, recruiting logistics, "
            "candidate experience, applicant tracking systems, recruiters, hiring managers, and recruiting process "
            "improvement for SPAN's San Francisco recruiting team."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Maven Clinic",
        "location": "Remote, United States (Bay Area eligible)",
        "work_mode": "remote",
        "employment_type": "6-month contract",
        "posted_date": "Listed about 1 day ago; active form verified",
        "age_hours": 24,
        "freshness": "fresh",
        "freshness_label": "New — about 1d",
        "freshness_note": "Maven's direct Greenhouse application is active and accepting applications.",
        "salary": "$25.00–$37.50/hour",
        "url": "https://job-boards.greenhouse.io/mavenclinic/jobs/8561262002",
        "source_name": "Maven Clinic / Greenhouse",
        "required_years": 1,
        "required_skills": [
            "high-volume scheduling", "candidate communication", "Greenhouse ATS",
            "ModernLoop", "candidate experience",
        ],
        "responsibilities": [
            "Coordinate more than 75 interviews per week and candidate travel logistics.",
            "Maintain accurate Greenhouse and ModernLoop records.",
            "Partner with recruiters and hiring managers and improve recruiting processes.",
        ],
        "description": (
            "Schedule 75+ interviews weekly across time zones, coordinate travel and logistics, maintain Greenhouse "
            "and ModernLoop, communicate with candidates, partner with recruiters and hiring managers, and improve "
            "recruiting processes. Requires at least one year of recruiting support experience."
        ),
    },
    {
        "title": "Recruiting Coordinator - AI Startup",
        "company": "BURKE + CO.",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "Listed about 3 days ago",
        "age_hours": 72,
        "freshness": "fresh",
        "freshness_label": "New — about 3d",
        "freshness_note": "The LinkedIn listing is active and displayed an Apply option when verified.",
        "salary": "$75,000–$100,000 + equity",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-ai-startup-at-burke-%2B-co-4408931551",
        "source_name": "BURKE + CO. / LinkedIn",
        "required_years": 2,
        "required_skills": [
            "interview scheduling", "candidate communication", "Ashby ATS",
            "AI and LLM tools", "candidate experience",
        ],
        "responsibilities": [
            "Own end-to-end interview scheduling and complex calendars.",
            "Serve as the Ashby ATS expert and maintain accurate hiring pipelines.",
            "Use AI tools to streamline coordination and partner with recruiters and hiring managers.",
        ],
        "description": (
            "Own interview scheduling across roles and stages, manage complex calendars, provide candidate "
            "communication, administer Ashby, use AI tools, maintain pipeline data, and partner with recruiters and "
            "hiring managers. Requires two or more years of recruiting coordinator experience."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Rippling",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "Contract",
        "posted_date": "Listed within the past 2–6 days",
        "age_hours": 48,
        "freshness": "fresh",
        "freshness_label": "Current — 2–6d",
        "freshness_note": "The active LinkedIn application appeared between two and six days old across current listings.",
        "salary": "Not listed",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-contract-at-rippling-4401584514",
        "source_name": "Rippling / LinkedIn",
        "required_years": None,
        "required_skills": [
            "high-volume scheduling", "candidate communication", "candidate experience",
            "applicant tracking systems", "cross-functional collaboration",
        ],
        "responsibilities": [
            "Schedule high-volume virtual and onsite interviews for technical and nontechnical roles.",
            "Support recruiting teams in North America, Europe, and Australia.",
            "Partner across functions and maintain accurate ATS and ticketing data.",
        ],
        "description": (
            "Schedule a high volume of virtual and in-person interviews, support global recruiting teams, communicate "
            "with candidates and stakeholders, partner with recruiters and hiring managers, deliver candidate "
            "experience, and use applicant tracking and ticketing tools accurately."
        ),
    },
    {
        "title": "Recruiting and Workplace Experience Coordinator",
        "company": "Opal Security",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "Full-time",
        "posted_date": "Listed within the past 5–7 days",
        "age_hours": 120,
        "freshness": "fresh",
        "freshness_label": "Current — 5–7d",
        "freshness_note": "Opal's official careers page lists the role, and recent job results place it within one week.",
        "salary": "Not listed",
        "url": "https://jobs.ashbyhq.com/Opal/dc0ed84d-2528-47d9-a6a8-25a467ad56ff",
        "source_name": "Opal Security / Ashby",
        "required_years": 1,
        "required_skills": [
            "candidate experience", "candidate communication", "onboarding",
            "recruiting coordination", "cross-functional collaboration",
        ],
        "responsibilities": [
            "Source and manage candidates from first message through onsite interviews.",
            "Coordinate onsite logistics, events, visitors, and new-hire onboarding.",
            "Support people operations, HRIS updates, benefits questions, and policy documentation.",
        ],
        "description": (
            "Support recruiting, workplace experience, and people operations. Source candidates, manage candidate "
            "communication and onsite logistics, partner with hiring managers, support onboarding, events, HRIS "
            "updates, benefits questions, and policy documentation. Requires one to four years of relevant experience."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Snowflake",
        "location": "Menlo Park, CA",
        "work_mode": "hybrid",
        "employment_type": "12-month contract",
        "posted_date": "Relisted within about 1 day; original listing is older",
        "age_hours": 19,
        "freshness": "repost",
        "freshness_label": "Recent relist — ~1d",
        "freshness_note": "Current search results showed a fresh relist; the detailed LinkedIn record is older, so verify availability before investing time.",
        "salary": "$35–$40/hour",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-contract-at-snowflake-4406734097",
        "source_name": "Snowflake / LinkedIn",
        "required_years": 2,
        "required_skills": [
            "high-volume scheduling", "candidate communication", "Ashby ATS",
            "onboarding", "candidate experience",
        ],
        "responsibilities": [
            "Schedule high-volume global interviews and communicate interview logistics.",
            "Support onboarding and maintain accurate Ashby workflows.",
            "Partner with recruiters and hiring managers and improve recruiting operations.",
        ],
        "description": (
            "Twelve-month Recruiting Coordinator contract requiring four days per week in Menlo Park. Coordinate "
            "high-volume global interviews, candidate logistics and onboarding, maintain Ashby data, partner with "
            "recruiters and hiring managers, and improve recruiting processes. Requires two or more years."
        ),
    },
    {
        "title": "Founding Recruiting Coordinator",
        "company": "Gimlet Labs",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "Relisted within about 2 days; original listing is older",
        "age_hours": 48,
        "freshness": "repost",
        "freshness_label": "Recent relist — ~2d",
        "freshness_note": "The direct Ashby role is active, but indexed posting ages conflict, indicating a recent relist.",
        "salary": "$100,000–$130,000",
        "url": "https://jobs.ashbyhq.com/gimlet/01cffefa-c9f1-4729-96d6-faff0f41d8fc/",
        "source_name": "Gimlet Labs / Ashby",
        "required_years": 1,
        "required_skills": [
            "interview scheduling", "candidate communication", "Ashby ATS",
            "candidate experience", "recruiting operations",
        ],
        "responsibilities": [
            "Coordinate complex interviews across time zones and functions.",
            "Maintain Ashby data and improve scheduling efficiency and process integrity.",
            "Support recruiting events, sourcing coordination, and pipeline tracking.",
        ],
        "description": (
            "Own candidate experience, coordinate complex interviews, partner with recruiters and hiring managers, "
            "maintain Ashby data, support events and sourcing, track pipelines, and improve recruiting operations. "
            "Requires one to three years of recruiting coordination or similar operations experience."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Netic",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "posted_date": "Relisted within about 15 hours; original listing is older",
        "age_hours": 15,
        "freshness": "repost",
        "freshness_label": "Recent relist — ~15h",
        "freshness_note": "The direct Ashby role is active; LinkedIn showed a fresh relist while the original posting is older.",
        "salary": "Not listed",
        "url": "https://jobs.ashbyhq.com/netic/f3d462f9-ffad-4fa7-bb35-913956c7acca",
        "source_name": "Netic / Ashby",
        "required_years": 1,
        "required_skills": [
            "interview scheduling", "candidate communication", "candidate experience",
            "recruiting coordination", "applicant tracking systems",
        ],
        "responsibilities": [
            "Coordinate recruiting activity in a fast-paced AI company.",
            "Deliver candidate communication and an organized candidate experience.",
            "Maintain recruiting systems and support operational hiring workflows.",
        ],
        "description": (
            "Detail-oriented Recruiting Coordinator supporting scheduling, candidate communication, candidate "
            "experience, recruiting systems, recruiters, and hiring operations in a fast-paced onsite San Francisco "
            "environment. Requires one to three years in recruiting or HR coordination."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Samsara",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "Full-time",
        "posted_date": "Relisted within about 1 day; direct role remains active",
        "age_hours": 24,
        "freshness": "repost",
        "freshness_label": "Recent relist — ~1d",
        "freshness_note": "Samsara's direct application is active, but other boards show an older original posting date.",
        "salary": "$71,485–$84,100",
        "url": "https://www.samsara.com/company/careers/roles/7732679?gh_jid=7732679",
        "source_name": "Samsara careers",
        "required_years": 1,
        "required_skills": [
            "interview scheduling", "candidate communication", "Greenhouse ATS",
            "candidate experience", "high-volume scheduling",
        ],
        "responsibilities": [
            "Manage complex interview operations and calendars with executives and recruiters.",
            "Host onsite technical candidates three days per week in San Francisco.",
            "Use Greenhouse, Slack, and Google Calendar and improve recruiting processes.",
        ],
        "description": (
            "Manage complex scheduling and interview logistics, partner with executives and remote recruiters, host "
            "onsite software engineering candidates, and use Greenhouse, Slack, and Google Calendar. Requires one to "
            "three years in recruiting, HR, or executive support and process-improvement experience."
        ),
    },
]


def load_excluded_companies() -> set[str]:
    """Load ignored, local-only application registries without publishing them."""
    excluded: set[str] = set()
    registry_path = report.DATA_DIR / "applied_jobs.json"
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        excluded.update(
            normalized(item["company"])
            for item in registry.get("jobs", [])
            if item.get("company")
        )

    exclusions_path = report.DATA_DIR / "application_exclusions.local.json"
    if exclusions_path.is_file():
        payload = json.loads(exclusions_path.read_text(encoding="utf-8"))
        companies = payload if isinstance(payload, list) else payload.get("companies", [])
        excluded.update(normalized(company) for company in companies if company)
    return excluded


def check_exclusions() -> None:
    excluded = load_excluded_companies()
    overlap = sorted(item["company"] for item in ROLE_SNAPSHOTS if normalized(item["company"]) in excluded)
    if overlap:
        raise RuntimeError("Applied companies leaked into report: " + ", ".join(overlap))


def build() -> tuple[Path, Path, Path]:
    check_exclusions()
    report.ROLE_SNAPSHOTS = ROLE_SNAPSHOTS
    report.REPORT_STEM = "recruiting_coordinator_7d_resume_weighted_2026-07-22"
    report.DATA_STEM = "resume_weighted_matches_7d_2026-07-22"
    report.PAGE_TITLE = "Bay Area recruiting roles from the last seven days"
    report.PAGE_SUBTITLE = (
        "Previously applied companies excluded · corrected resume weighted into every fit score · "
        "active postings and recent relists checked 2026-07-22."
    )
    report.COVERAGE_NOTE = (
        "Nine verified matches remain after excluding companies from the local application registries. "
        "Recent relists are separated from clearly new listings. Career Group was excluded because its job URL "
        "redirects as expired; Grocery Outlet was excluded because the direct page shows nine days old."
    )
    report.FRESH_SUMMARY_LABEL = "New / current ≤7d"
    report.FRESH_FILTER_LABEL = "New / current ≤7d only"
    return report.build()


if __name__ == "__main__":
    for output in build():
        print(output)
