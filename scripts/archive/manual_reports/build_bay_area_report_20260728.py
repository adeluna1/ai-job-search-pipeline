"""Build the verified July 28 Bay Area recruiting and people-operations report."""

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
from job_pipeline.storage import JobStore
from job_pipeline.util import stable_id


SELECTIONS = [
    {
        "database": "search_20260728_rerun_tac_sf_24h.sqlite3",
        "id": "f44d724a2dd404b2",
        "window": "Last 24h",
        "verification": (
            "returned by the 24-hour LinkedIn filter; the application page is active, "
            "although LinkedIn did not expose an exact timestamp"
        ),
        "overrides": {
            "location": "Brisbane, CA",
            "work_mode": "onsite",
            "employment_type": "contract",
            "posted_date": "Last 24h — exact timestamp unavailable",
        },
    },
    {
        "database": "jobs.sqlite3",
        "id": "ae462dfe244c8b58",
        "window": "Last 24h",
        "verification": (
            "indexed at 17 hours and verified on Render's active employer application"
        ),
        "overrides": {
            "location": "San Francisco, CA",
            "work_mode": "hybrid",
            "posted_date": "Last 24h — indexed at 17 hours",
            "salary": "$100,000–$150,000 + equity",
        },
    },
    {
        "database": "jobs.sqlite3",
        "id": "f5e70ed651cfea17",
        "window": "Last 24h",
        "verification": (
            "indexed at 15 hours and verified on Cursor's active employer application"
        ),
        "location_score": 100.0,
        "overrides": {
            "title": "People Operations Coordinator",
            "location": "San Francisco, CA",
            "work_mode": "onsite",
            "posted_date": "Last 24h — indexed at 15 hours",
        },
    },
    {
        "database": "search_20260728_rerun_tac_sf_24h.sqlite3",
        "id": "96b62c09520af79e",
        "window": "Last 24h",
        "verification": (
            "returned by the 24-hour LinkedIn filter and independently verified as "
            "an active application; confirm the branch-based schedule"
        ),
        "overrides": {
            "work_mode": "onsite",
            "posted_date": "Last 24h — exact timestamp unavailable",
        },
    },
    {
        "database": "jobs.sqlite3",
        "id": "b7986a98a7107a49",
        "window": "Last 24h",
        "verification": (
            "indexed at 17 hours and verified on Beautylish's active employer application"
        ),
        "overrides": {
            "work_mode": "hybrid",
            "posted_date": "Last 24h — indexed at 17 hours",
            "salary": "$25–$30/hour",
        },
    },
    {
        "database": "jobs.sqlite3",
        "id": "fee56f6254bb3eca",
        "window": "Last 3 days",
        "verification": (
            "indexed at 2 days and verified on Stafl Systems' active employer application"
        ),
        "location_score": 100.0,
        "overrides": {
            "company": "Stafl Systems",
            "location": "South San Francisco, CA",
            "work_mode": "onsite",
            "posted_date": "Last 3 days — indexed at 2 days",
            "salary": "$79,000–$105,000",
        },
    },
    {
        "database": "search_20260728_rerun_tac_sf_72h.sqlite3",
        "id": "b989722bb54a7648",
        "window": "Last 3 days",
        "verification": (
            "dated July 26 by the board and verified on Ford's active employer application"
        ),
        "overrides": {
            "work_mode": "onsite",
            "employment_type": "contract",
            "posted_date": "Last 3 days — 2026-07-26",
            "url": (
                "https://www.careers.ford.com/job/palo-alto/"
                "talent-acquisition-specialist/48560/96320302752"
            ),
        },
    },
]


def _update_location_score(record: dict, target: float) -> None:
    """Apply a corrected Bay Area location component and update the total score."""
    components = dict(record.get("components", {}))
    original = float(components.get("location", 0))
    components["location"] = target
    record["components"] = components
    delta = (target - original) * 0.1
    record["deterministic_score"] = round(
        float(record["deterministic_score"]) + delta, 1
    )
    record["final_score"] = round(float(record["final_score"]) + delta, 1)
    record["gaps"] = [
        gap
        for gap in record.get("gaps", [])
        if not gap.startswith("Location does not match")
        and not gap.startswith("Location is not stated")
    ]
    if record["final_score"] >= 82:
        record["fit_label"] = "excellent"
    elif record["final_score"] >= 72:
        record["fit_label"] = "strong"
    elif record["final_score"] >= 60:
        record["fit_label"] = "possible"
    else:
        record["fit_label"] = "weak"


def _pearl_record() -> dict:
    """Score the current fully remote Pearl role through the standard matcher."""
    url = "https://www.linkedin.com/jobs/view/4440580466"
    description = (
        "Support onboarding and offboarding processes and employee lifecycle activities. "
        "Maintain employee records and HR systems, including data accuracy and reporting. "
        "Assist with employee engagement programs, surveys, feedback, internal documentation, "
        "and day-to-day People Operations support. Collaborate with a global People team, "
        "identify process improvements, and learn AI-powered workflows. The role asks for "
        "zero to two years in HR, People Operations, recruiting coordination, operations, "
        "customer support, or administration, plus excellent communication, organization, "
        "attention to detail, Microsoft Office or Google Workspace. HR systems such as HiBob "
        "or Lattice are preferred."
    )
    job = Job(
        id=stable_id(url),
        url=url,
        title="People Operations Associate",
        company="Pearl",
        location="Remote; California",
        work_mode="remote",
        employment_type="fulltime",
        posted_date="Last 24h — indexed at 15 hours",
        salary="",
        description=description,
        source="public-search-fallback",
        required_years=2,
    )
    profile = json.loads(
        (ROOT / "config" / "profile.json").read_text(encoding="utf-8")
    )
    resume_text = extract_docx_text(
        ROOT.parent / "resume.docx"
    )
    record = {**job.to_dict(), **score_job(job, profile, resume_text).to_dict()}
    record["id"] = job.id
    record["status"] = "new"
    verification = (
        "indexed at 15 hours, fully remote from California, and verified on the "
        "active LinkedIn application"
    )
    record["recommendation"] = f"Last 24h • {verification}."
    record["notes"] = (
        "Resume-weighted against the candidate's corrected resume. "
        f"{verification}."
    )
    return record


def build() -> tuple[Path, Path]:
    """Load, correct, annotate, deduplicate, and export the verified shortlist."""
    records: list[dict] = []
    stores: dict[str, JobStore] = {}
    try:
        for selection in SELECTIONS:
            database = selection["database"]
            store = stores.setdefault(database, JobStore(ROOT / "data" / database))
            ranked = {record["id"]: record for record in store.ranked()}
            record = ranked.get(selection["id"])
            if record is None:
                raise RuntimeError(
                    f"Selected job {selection['id']} is missing from {database}."
                )
            record = dict(record)
            record.update(selection["overrides"])
            if "location_score" in selection:
                _update_location_score(record, float(selection["location_score"]))
            verification = selection["verification"]
            record["recommendation"] = f"{selection['window']} • {verification}."
            record["notes"] = (
                "Resume-weighted against the candidate's corrected resume. "
                f"{verification}."
            )
            record["status"] = "new"
            records.append(record)
    finally:
        for store in stores.values():
            store.close()

    records.append(_pearl_record())
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
        prefix="recruiting_people_operations_bay_area_24h_3d_2026-07-28",
        title="Bay Area recruiting & people operations matches",
        subtitle=(
            "New onsite, hybrid, and remote roles from the last 24 hours or 3 days, "
            "weighted against the candidate's corrected resume. Previously sent and "
            "applied roles are excluded; exact-timestamp limitations are labeled."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
