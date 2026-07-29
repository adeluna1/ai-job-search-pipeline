"""Build the July 27 Recruiting Coordinator shortlist from live search databases."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from job_pipeline.report import export_reports
from job_pipeline.storage import JobStore


SELECTIONS = [
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "a44ac877dd5e5e9b",
        "window": "Last 24h",
        "verification": "Agent B verified employer page active",
        "url": "https://jobs.lever.co/protolabs/981409d9-584b-4635-8d77-a8344ae2667d",
    },
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "f80b06eca1383735",
        "window": "Last 24h",
        "verification": "Agent B verified direct posting; title metadata differs slightly",
        "work_mode": "remote",
    },
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "a6f17c1348e2e5ee",
        "window": "Last 24h relist",
        "verification": "Agent B verified employer page active; older age appears on some boards",
    },
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "042526a0a5685024",
        "window": "Last 24h",
        "verification": "Agent B verified live LinkedIn posting",
    },
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "785b374bb3a230fa",
        "window": "Last 24h",
        "verification": "Agent B verified live LinkedIn posting",
    },
    {
        "database": "search_20260727_rc_us_24h.sqlite3",
        "id": "3649bf86a63e6209",
        "window": "Last 3 days",
        "verification": "LinkedIn company page lists the role at 3 days",
    },
    {
        "database": "search_20260727_rc_bay_24h.sqlite3",
        "id": "2c2e6f399b09d009",
        "window": "Last 3 days",
        "verification": "Employer Greenhouse form active; Built In lists 2 days",
        "url": "https://job-boards.greenhouse.io/thinkingmachines/jobs/5290764008",
        "work_mode": "onsite",
        "posted_date": "Last 3 days — verified active",
        "salary": "$140,000–$200,000",
    },
    {
        "database": "search_20260727_rc_bay_72h.sqlite3",
        "id": "2fffe285fcddb9d1",
        "window": "Last 3 days",
        "verification": "Employer application active",
        "url": "https://cursor.com/careers/recruiting-coordinator",
        "work_mode": "onsite",
    },
    {
        "database": "search_20260727_rc_us_72h.sqlite3",
        "id": "be3b9655057e4dbb",
        "window": "Last 3 days",
        "verification": "Marriott employer page active through 2026-08-07",
        "url": "https://careers.marriott.com/flex-recruiting-coordinator-luxury/job/37372F61FBD70A4E255E2359E6D6731C",
        "salary": "$22.64–$39.71/hour",
    },
    {
        "database": "search_20260727_rc_us_72h.sqlite3",
        "id": "7d3cb1f82db10c29",
        "window": "Last 3 days",
        "verification": "Agent B verified live LinkedIn posting",
    },
    {
        "database": "search_20260727_rc_us_72h.sqlite3",
        "id": "e3721628bb28a204",
        "window": "Last 3 days",
        "verification": "Agent B verified live LinkedIn posting",
    },
    {
        "database": "search_20260727_rc_us_72h.sqlite3",
        "id": "1101ff42b374a824",
        "window": "Last 3 days",
        "verification": "Agent B verified live LinkedIn posting",
    },
    {
        "database": "search_20260727_rc_us_72h.sqlite3",
        "id": "8773b4e1775e02f2",
        "window": "Last 3 days",
        "verification": "Employer Paylocity board lists 2026-07-24",
        "url": "https://www.linkedin.com/jobs/view/4444607252",
    },
]


def build() -> tuple[Path, Path]:
    """Join selected scored records and export the dated interactive report."""
    records = []
    by_database: dict[str, list[dict]] = {}
    for selection in SELECTIONS:
        by_database.setdefault(selection["database"], []).append(selection)

    for database_name, selections in by_database.items():
        with JobStore(ROOT / "data" / database_name) as store:
            ranked = {record["id"]: record for record in store.ranked()}
        for selection in selections:
            record = ranked.get(selection["id"])
            if record is None:
                raise RuntimeError(
                    f"Selected job {selection['id']} is missing from {database_name}."
                )
            record = dict(record)
            for key in ("url", "work_mode", "posted_date", "salary"):
                if selection.get(key):
                    record[key] = selection[key]
            record["posted_date"] = (
                selection.get("posted_date")
                or f"{selection['window']} — {record.get('posted_date') or 'board filter'}"
            )
            record["recommendation"] = (
                f"{selection['window']} • {selection['verification']}"
            )
            record["notes"] = (
                "Resume-weighted score using the corrected resume. "
                f"{selection['verification']}."
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
        prefix="recruiting_coordinator_24h_3d_2026-07-27",
    )


if __name__ == "__main__":
    for path in build():
        print(path)
