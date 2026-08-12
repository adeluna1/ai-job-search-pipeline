"""Print recently refreshed jobs from the local pipeline database as JSON."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    database = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/jobs.sqlite3")
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT id, title, company, location, work_mode, employment_type,
               posted_date, salary, url, source, discovered_at, updated_at
        FROM jobs
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    print(json.dumps([dict(row) for row in rows], indent=2, ensure_ascii=False))
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
