"""Build the July 27 Bay Area-only Recruiting Coordinator report."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_pipeline.report import export_reports
from job_pipeline.storage import JobStore


SELECTIONS = [
    {
        "database": "search_20260727_bay_sf_24h_rerun.sqlite3",
        "id": "f03f04ab445f04db",
        "window": "Last 24h",
        "verification": (
            "LinkedIn listed the repost 10 hours ago; the content and compensation "
            "match OpenAI's active employer page"
        ),
        "overrides": {
            "title": "Recruiting Coordinator",
            "company": "OpenAI",
            "location": "San Francisco, CA",
            "work_mode": "hybrid",
            "employment_type": "fulltime",
            "posted_date": "Last 24h — LinkedIn repost",
            "salary": "$105,000–$125,000 + equity",
            "url": "https://openai.com/careers/recruiting-coordinator-san-francisco/",
        },
    },
    {
        "database": "search_20260727_bay_sf_72h_rerun.sqlite3",
        "id": "70e83a7375481726",
        "window": "Last 24h relist",
        "verification": (
            "LinkedIn returned a July 26 relist; an older board snapshot shows the "
            "original posting predates the relist"
        ),
        "bay_area_location": True,
        "overrides": {
            "work_mode": "onsite",
            "posted_date": "Last 24h — board relist",
            "salary": "$27–$31/hour",
        },
    },
    {
        "database": "search_20260727_bay_sf_72h_rerun.sqlite3",
        "id": "337090fd3f925114",
        "window": "Last 3 days",
        "verification": "Built In lists the active role as reposted 2 days ago",
        "overrides": {
            "posted_date": "Last 3 days — reposted 2 days ago",
            "salary": "$77,000–$102,000",
            "work_mode": "onsite",
        },
    },
    {
        "database": "search_20260727_bay_sj_72h_rerun.sqlite3",
        "id": "d25a6cc68a6d7e7d",
        "window": "Last 3 days",
        "verification": "OpenAI employer page and application are active",
        "overrides": {
            "location": "San Francisco, CA",
            "work_mode": "hybrid",
            "posted_date": "Last 3 days — 2026-07-25",
            "salary": "$170,000–$190,000 + equity",
            "url": (
                "https://openai.com/careers/"
                "recruiting-coordinator-lead-applied-san-francisco/"
            ),
        },
    },
    {
        "database": "search_20260727_bay_sf_24h_rerun.sqlite3",
        "id": "2c2e6f399b09d009",
        "window": "Last 3 days",
        "verification": (
            "Thinking Machines employer board is active; Built In lists the role "
            "as posted 2 days ago"
        ),
        "overrides": {
            "work_mode": "onsite",
            "posted_date": "Last 3 days — posted 2 days ago",
            "salary": "$140,000–$200,000",
            "url": (
                "https://job-boards.greenhouse.io/thinkingmachines/"
                "jobs/5290764008"
            ),
        },
    },
    {
        "database": "search_20260727_rc_bay_72h.sqlite3",
        "id": "2fffe285fcddb9d1",
        "window": "Last 3 days",
        "verification": (
            "Cursor employer application is active and LinkedIn lists the role "
            "at 2 days"
        ),
        "overrides": {
            "work_mode": "onsite",
            "posted_date": "Last 3 days — listed 2 days ago",
            "url": "https://cursor.com/careers/recruiting-coordinator",
        },
    },
]


def build() -> tuple[Path, Path]:
    """Load selected scored jobs, apply verification metadata, and export."""
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
            if selection.get("bay_area_location"):
                components = dict(record.get("components", {}))
                location_score = float(components.get("location", 0))
                components["location"] = 100.0
                record["components"] = components
                score_delta = (100.0 - location_score) * 0.1
                record["deterministic_score"] = round(
                    float(record["deterministic_score"]) + score_delta, 1
                )
                record["final_score"] = round(
                    float(record["final_score"]) + score_delta, 1
                )
                record["gaps"] = [
                    gap
                    for gap in record.get("gaps", [])
                    if not gap.startswith("Location does not match")
                ]
            verification = selection["verification"]
            record["recommendation"] = (
                f"{selection['window']} • {verification}."
            )
            record["notes"] = (
                "Resume-weighted against the candidate's corrected resume. "
                f"{verification}."
            )
            records.append(record)
    finally:
        for store in stores.values():
            store.close()

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
        prefix="recruiting_coordinator_bay_area_24h_3d_2026-07-27",
        title="Bay Area recruiting coordinator matches",
        subtitle=(
            "Recruiting coordination roles found in the last 24 hours or 3 days, "
            "ranked against the candidate's corrected resume. Reposts are labeled."
        ),
    )


if __name__ == "__main__":
    for path in build():
        print(path)
