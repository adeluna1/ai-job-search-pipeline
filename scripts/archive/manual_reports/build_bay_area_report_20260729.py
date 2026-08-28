"""Build the July 29 Bay Area and San Jose recruiting-role report."""

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
        "title": "Recruiting & Workplace Experience Coordinator",
        "company": "Cooper AI",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "",
        "url": "https://jobs.ashbyhq.com/cooper-ai/b6ff1f2c-c0b1-4753-b48a-a4fdce50f81a",
        "window": "Last 24h",
        "posted_date": "Last 24h - board reports 1 calendar day",
        "verification": "Direct Ashby application is active; Agent A reports the posting as 1 calendar day old.",
        "required_years": 2,
        "description": (
            "Coordinate recruiting and workplace experience in a fast-paced startup. "
            "Own interview scheduling, candidate communication, onsite logistics, and a "
            "high-touch candidate experience. Maintain accurate applicant tracking system "
            "records, partner with recruiters and hiring managers, support onboarding, "
            "document workflows, and improve recruiting operations and office programs."
        ),
    },
    {
        "title": "Go to Market Recruiting Coordinator",
        "company": "Decagon",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "$90,000-$110,000 + equity",
        "url": "https://jobs.ashbyhq.com/decagon/ac6bb765-99b9-47d0-9347-7e3493652f9f/",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Direct Ashby application is active and the current LinkedIn listing displays 1 day ago.",
        "required_years": 0,
        "description": (
            "Own end-to-end high-volume interview coordination across candidates, "
            "interviewers, recruiters, and go-to-market leaders. Deliver white-glove "
            "candidate communication, maintain ATS and scheduling data, track service "
            "levels, improve recruiting workflows, and use AI tools to reduce manual work. "
            "Ashby or another applicant tracking system and recruiting coordination are preferred."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Nudge",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "",
        "url": "https://jobs.ashbyhq.com/nudge/ce3b887e-67f8-4ab5-9ec2-9acf484c0c77",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Direct Ashby application is active and the current LinkedIn listing displays 1 day ago.",
        "required_years": 2,
        "description": (
            "Coordinate candidate interview logistics including scheduling, travel, meals, "
            "materials, and onsite hosting. Serve as the primary candidate contact, support "
            "referrals, maintain accurate ATS records and feedback, and assist with onboarding "
            "paperwork, systems access, and first-day coordination. Requires recruiting or HR "
            "coordination, calendar management, Google Workspace, and applicant tracking systems."
        ),
    },
    {
        "title": "Recruiting Coordinator - Contract",
        "company": "BetterUp",
        "location": "Remote - United States",
        "work_mode": "remote",
        "employment_type": "12-week contract",
        "salary": "",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-contract-at-betterup-4407944987",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Current LinkedIn posting is active, complete, and states this is a US-remote position.",
        "required_years": 2,
        "description": (
            "Schedule high-volume phone, video, and remote onsite interviews and debriefs. "
            "Manage candidate communication, recruiter and hiring-manager calendars, and "
            "candidate experience. Create scheduling templates in Ashby, manage interviewer "
            "pools and capacity, and use AI assistants to streamline repetitive workflows. "
            "Requires at least two years of recruiting coordination experience."
        ),
    },
    {
        "title": "Recruiting Coordinator / Talent Operations Specialist",
        "company": "Another Source",
        "location": "Remote - California eligible",
        "work_mode": "remote",
        "employment_type": "Full-time",
        "salary": "$65,000-$75,000",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-another-source-at-another-source-4417194560",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Current LinkedIn posting is active and explicitly permits California residents.",
        "required_years": 2,
        "description": (
            "Support recruiting operations for a fully remote team, coordinate interviews, "
            "communicate with candidates and clients, maintain recruiting systems and job "
            "postings, and improve documentation and processes. Balance multiple priorities "
            "with strong candidate experience, cross-functional collaboration, and attention "
            "to detail. A short cover letter answering three role-specific questions is required."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Figure",
        "location": "San Jose, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinatornew-at-figure-4378247820",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Current LinkedIn job page is active and identifies the San Jose headquarters.",
        "required_years": 1,
        "description": (
            "Support the People team and scale hiring across engineering, operations, and "
            "manufacturing. Coordinate complex interview schedules, manage candidate "
            "communication, maintain accurate applicant tracking data, partner with recruiters "
            "and hiring managers, improve recruiting processes, and deliver a strong candidate "
            "experience in a fast-growing AI robotics company."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Career Group",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Temporary to permanent",
        "salary": "$35-$45/hour",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-at-career-group-4428716858",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "This is a new LinkedIn listing ID; the current page is active and separate from the previously expired Career Group URL.",
        "required_years": 0,
        "description": (
            "Coordinate interview stages, complex calendars, reschedules, and candidate "
            "communication for a high-growth startup. Maintain Ashby or similar ATS data, "
            "pipeline stages, tags, and reporting. Support offers, onboarding logistics, "
            "recruiting events, documentation, templates, process improvement, recruiters, "
            "and hiring managers. The posting requests zero to two years of experience."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Pyramid Consulting Group",
        "location": "San Francisco or Mountain View, CA",
        "work_mode": "onsite",
        "employment_type": "Temporary",
        "salary": "$40/hour",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-at-pyramid-consulting-group-llc-4424459396",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Current LinkedIn posting is active and offers either San Francisco or Mountain View.",
        "required_years": 2,
        "description": (
            "Coordinate interviews between candidates and hiring managers, maintain and update "
            "the applicant tracking system, provide timely candidate communication, and support "
            "new-hire onboarding materials and orientation. Requires two or more years of "
            "recruiting coordination, ATS proficiency, G Suite, organization, and time management."
        ),
    },
    {
        "title": "People Services Coordinator",
        "company": "Chime",
        "location": "San Francisco, CA",
        "work_mode": "onsite",
        "employment_type": "Full-time",
        "salary": "$31.25-$43.27/hour",
        "url": "https://job-boards.greenhouse.io/chime/jobs/8396647002",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Direct Greenhouse application is active; the current LinkedIn listing displays 1 day ago.",
        "required_years": 2,
        "description": (
            "Support both recruiting coordination and People Services in San Francisco. "
            "Schedule interviews with GoodTime and Google Calendar, manage job postings in "
            "Greenhouse, greet and escort onsite candidates, deliver candidate and employee "
            "support, maintain documentation and accurate people data, and partner across the "
            "People team with a service-oriented communication style."
        ),
    },
    {
        "title": "Recruiting Coordinator",
        "company": "Aston Carter",
        "location": "Mountain View, CA",
        "work_mode": "onsite",
        "employment_type": "Contract",
        "salary": "$28/hour",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-at-aston-carter-4438601160",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Current LinkedIn posting is active and specifies five onsite days in Mountain View.",
        "required_years": 3,
        "description": (
            "Deliver onsite recruiting and onboarding support for a Silicon Valley AI-focused "
            "business group. Coordinate candidate visits, interviews, campus tours, new-hire "
            "onboarding, case management, scheduling, documentation, Excel reporting, Slack "
            "communication, and high-volume workflows. Requires three to four years of related "
            "recruiting, HR, customer service, or administrative experience and regular physical setup."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "Applied Intuition",
        "location": "Sunnyvale, CA",
        "work_mode": "onsite",
        "employment_type": "Contract",
        "salary": "$60,000-$120,000",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-contract-at-applied-intuition-4440606261",
        "window": "Last 24h",
        "posted_date": "Last 24h - LinkedIn displays 1 day ago",
        "verification": "Agent B saved and scored the active LinkedIn posting; occasional schedule flexibility is noted.",
        "required_years": 1.5,
        "description": (
            "Coordinate and analyze recruiting operations for an in-office physical AI company. "
            "Review applications, schedule and conduct candidate interviews, maintain candidate "
            "records, build recruiting coordination goals and KPIs, report recruiting metrics "
            "and return on investment, and partner across technical teams. Requires at least "
            "18 months of recruiting coordination or HR specialist experience."
        ),
    },
    {
        "title": "Embedded Recruiting Coordinator",
        "company": "Horus Recruiting",
        "location": "Remote - United States; Bay Area listing",
        "work_mode": "remote",
        "employment_type": "1099 contract",
        "salary": "$23.25-$31.25/hour estimated",
        "url": "https://www.ziprecruiter.com/c/Horus-Recruiting/Job/Embedded-Recruiting-Coordinator/-in-Santa-Clara%2CCA?jid=0a8c2679be74cb6e",
        "window": "Last 3 days",
        "posted_date": "Last 3 days - ZipRecruiter displays 3 days ago",
        "verification": "ZipRecruiter page is active; description says US-remote although the location card shows Santa Clara.",
        "required_years": 2,
        "description": (
            "Provide embedded recruiting coordination across fast-growing client teams. "
            "Schedule interviews, manage calendars, communicate with candidates, maintain "
            "accurate records in Ashby, Greenhouse, or Lever, prepare interview materials, "
            "organize onsite loops and recruiting events, partner with recruiters and hiring "
            "managers, and improve recruiting documentation and processes."
        ),
    },
    {
        "title": "Recruiting Coordinator - USDS (Third-Party Associate)",
        "company": "TikTok USDS JV",
        "location": "San Jose, CA",
        "work_mode": "onsite",
        "employment_type": "6-month temporary assignment",
        "salary": "$29-$40/hour",
        "url": "https://www.indeed.com/viewjob?jk=98b0364908d89d83",
        "window": "Last 3 days",
        "posted_date": "Last 3 days - LinkedIn displays 2 days ago",
        "verification": "Indeed posting is active and LinkedIn displays 2 days ago; the employer is moving to up to five onsite days.",
        "required_years": 1,
        "description": (
            "Coordinate high-volume interviews and serve as the central contact for candidates, "
            "interviewers, recruiters, hiring managers, and business leaders. Improve candidate "
            "experience and hiring workflows, analyze interview volume and time-to-hire metrics, "
            "support recruiting events, and use ATS, Google Workspace, or Microsoft Office. "
            "Requires one or more years in recruiting coordination, HR operations, or a related role."
        ),
    },
    {
        "title": "Recruiting Coordinator (Contract)",
        "company": "SK hynix America",
        "location": "San Jose, CA",
        "work_mode": "onsite",
        "employment_type": "18-month contract",
        "salary": "$69,000-$95,000",
        "url": "https://www.linkedin.com/jobs/view/recruiting-coordinator-contract-at-sk-hynix-america-4438006974",
        "window": "Last 3 days",
        "posted_date": "Last 3 days - LinkedIn displays 2 days ago",
        "verification": "Agent B saved and scored the active LinkedIn posting; the role states an onsite San Jose work model.",
        "required_years": 2,
        "description": (
            "Provide coordination support through the full-cycle recruitment process. Manage "
            "interview scheduling, candidate communication, recruiting data tracking, applicant "
            "tracking system accuracy, onboarding support, recruiter and hiring-manager "
            "partnership, and compliance documentation while delivering a positive candidate experience."
        ),
    },
    {
        "title": "Recruiting Systems Specialist",
        "company": "Swoon",
        "location": "San Francisco, CA",
        "work_mode": "hybrid",
        "employment_type": "12-month contract",
        "salary": "",
        "url": "https://www.linkedin.com/jobs/view/recruiting-systems-specialist-97567-at-swoon-4426965980",
        "window": "Last 3 days",
        "posted_date": "Last 3 days - LinkedIn displays 2 days ago",
        "verification": "Current LinkedIn posting is active and states hybrid work three days per week onsite.",
        "required_years": 3,
        "description": (
            "Support recruiting operations systems for an AI research organization. Own "
            "day-to-day recruiting operations tickets in Jira and Slack, maintain accurate "
            "workflow and ATS data, troubleshoot user issues, document processes, partner with "
            "recruiters and coordinators, improve recruiting tools, analyze trends, and support "
            "a world-class candidate experience across people, process, and technology."
        ),
    },
]


def build() -> tuple[Path, Path]:
    """Score the verified shortlist and export dated interactive reports."""
    profile = json.loads((ROOT / "config" / "profile.json").read_text(encoding="utf-8"))
    resume_text = extract_docx_text(
        Path(r"C:\path\to\resume.docx")
    )
    records: list[dict] = []
    for item in JOBS:
        url = item["url"]
        job = Job(
            id=stable_id(url),
            url=url,
            title=item["title"],
            company=item["company"],
            location=item["location"],
            work_mode=item["work_mode"],
            employment_type=item["employment_type"],
            posted_date=item["posted_date"],
            salary=item["salary"],
            description=item["description"],
            source="verified-multi-board-2026-07-29",
            required_years=item["required_years"],
        )
        score = score_job(job, profile, resume_text)
        record = {**job.to_dict(), **score.to_dict()}
        record["id"] = job.id
        record["status"] = "new"
        record["recommendation"] = (
            f"{item['window']} - {item['verification']}"
        )
        record["notes"] = (
            "Resume-weighted against the candidate's corrected resume. "
            f"{item['verification']}"
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
        prefix="recruiting_roles_bay_area_san_jose_24h_3d_2026-07-29",
        title="Fresh Bay Area & San Jose recruiting roles",
        subtitle=(
            "New onsite, hybrid, and remote recruiting roles shown within the last "
            "24 hours or 3 days, weighted against the candidate's corrected resume. "
            "Previously sent and applied roles are excluded. JobSpy attempted LinkedIn, "
            "Indeed, Glassdoor, and ZipRecruiter; protected-board gaps were routed through "
            "WebClaw and authenticated browser coverage. Relative board ages are labeled."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
