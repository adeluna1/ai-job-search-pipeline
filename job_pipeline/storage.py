"""SQLite persistence for jobs, scores, runs, and application states."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .jobs import Job
from .matching import MatchResult
from .util import utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    work_mode TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    posted_date TEXT NOT NULL,
    salary TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    required_years REAL,
    required_skills_json TEXT NOT NULL,
    preferred_skills_json TEXT NOT NULL,
    responsibilities_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    deterministic_score REAL NOT NULL,
    final_score REAL NOT NULL,
    ai_score REAL,
    fit_label TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    components_json TEXT NOT NULL,
    matched_skills_json TEXT NOT NULL,
    matched_evidence_json TEXT NOT NULL,
    gaps_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    ai_reason TEXT NOT NULL,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'new',
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    jobs_seen INTEGER NOT NULL DEFAULT 0,
    jobs_saved INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0
);
"""


class JobStore:
    """Own the database connection and all persistence operations."""

    def __init__(self, path: Path):
        """Open a SQLite database and create or migrate the local schema."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        """Commit pending changes and close the connection."""
        self.connection.commit()
        self.connection.close()

    def __enter__(self) -> "JobStore":
        """Return this store for use in a context manager."""
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        """Close the store; SQLite rolls back an active failed statement itself."""
        self.close()

    def begin_run(self, action: str) -> int:
        """Create an execution record and return its integer ID."""
        cursor = self.connection.execute(
            "INSERT INTO runs(action, started_at) VALUES (?, ?)", (action, utc_now())
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, jobs_seen: int, jobs_saved: int, errors: int) -> None:
        """Finalize an execution record with observable counts."""
        self.connection.execute(
            """
            UPDATE runs
            SET finished_at=?, jobs_seen=?, jobs_saved=?, errors=?
            WHERE id=?
            """,
            (utc_now(), jobs_seen, jobs_saved, errors, run_id),
        )
        self.connection.commit()

    def upsert_job(self, job: Job) -> None:
        """Insert a new job or refresh extraction fields for its canonical URL."""
        self.connection.execute(
            """
            INSERT INTO jobs (
                id, url, title, company, location, work_mode, employment_type,
                posted_date, salary, description, source, required_years,
                required_skills_json, preferred_skills_json, responsibilities_json,
                raw_json, discovered_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                location=excluded.location,
                work_mode=excluded.work_mode,
                employment_type=excluded.employment_type,
                posted_date=excluded.posted_date,
                salary=excluded.salary,
                description=excluded.description,
                source=excluded.source,
                required_years=excluded.required_years,
                required_skills_json=excluded.required_skills_json,
                preferred_skills_json=excluded.preferred_skills_json,
                responsibilities_json=excluded.responsibilities_json,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                job.id,
                job.url,
                job.title,
                job.company,
                job.location,
                job.work_mode,
                job.employment_type,
                job.posted_date,
                job.salary,
                job.description,
                job.source,
                job.required_years,
                json.dumps(job.required_skills, ensure_ascii=False),
                json.dumps(job.preferred_skills, ensure_ascii=False),
                json.dumps(job.responsibilities, ensure_ascii=False),
                json.dumps(job.raw, ensure_ascii=False),
                job.discovered_at,
                utc_now(),
            ),
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO applications(job_id, status, notes, updated_at) VALUES (?, 'new', '', ?)",
            (job.id, utc_now()),
        )
        self.connection.commit()

    def upsert_match(self, match: MatchResult) -> None:
        """Store the latest scoring explanation for one job."""
        self.connection.execute(
            """
            INSERT INTO matches (
                job_id, deterministic_score, final_score, ai_score, fit_label,
                recommendation, components_json, matched_skills_json,
                matched_evidence_json, gaps_json, reasons_json, ai_reason, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                deterministic_score=excluded.deterministic_score,
                final_score=excluded.final_score,
                ai_score=excluded.ai_score,
                fit_label=excluded.fit_label,
                recommendation=excluded.recommendation,
                components_json=excluded.components_json,
                matched_skills_json=excluded.matched_skills_json,
                matched_evidence_json=excluded.matched_evidence_json,
                gaps_json=excluded.gaps_json,
                reasons_json=excluded.reasons_json,
                ai_reason=excluded.ai_reason,
                scored_at=excluded.scored_at
            """,
            (
                match.job_id,
                match.deterministic_score,
                match.final_score,
                match.ai_score,
                match.fit_label,
                match.recommendation,
                json.dumps(match.components, ensure_ascii=False),
                json.dumps(match.matched_skills, ensure_ascii=False),
                json.dumps(match.matched_evidence, ensure_ascii=False),
                json.dumps(match.gaps, ensure_ascii=False),
                json.dumps(match.reasons, ensure_ascii=False),
                match.ai_reason,
                utc_now(),
            ),
        )
        self.connection.commit()

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> Job:
        """Reconstruct one normalized job from its SQLite row."""
        return Job(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            work_mode=row["work_mode"],
            employment_type=row["employment_type"],
            posted_date=row["posted_date"],
            salary=row["salary"],
            description=row["description"],
            source=row["source"],
            required_years=row["required_years"],
            required_skills=json.loads(row["required_skills_json"]),
            preferred_skills=json.loads(row["preferred_skills_json"]),
            responsibilities=json.loads(row["responsibilities_json"]),
            discovered_at=row["discovered_at"],
            raw=json.loads(row["raw_json"]),
        )

    def jobs(self) -> list[Job]:
        """Return every normalized job in the database."""
        rows = self.connection.execute("SELECT * FROM jobs ORDER BY discovered_at DESC").fetchall()
        return [self._job_from_row(row) for row in rows]

    def job(self, job_id: str) -> Job | None:
        """Return one normalized job by stable ID, or None when it is unknown."""
        row = self.connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job_from_row(row) if row else None

    def match(self, job_id: str) -> MatchResult | None:
        """Return the latest structured match result for one job ID."""
        row = self.connection.execute("SELECT * FROM matches WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        return MatchResult(
            job_id=row["job_id"],
            deterministic_score=row["deterministic_score"],
            final_score=row["final_score"],
            ai_score=row["ai_score"],
            fit_label=row["fit_label"],
            recommendation=row["recommendation"],
            components=json.loads(row["components_json"]),
            matched_skills=json.loads(row["matched_skills_json"]),
            matched_evidence=json.loads(row["matched_evidence_json"]),
            gaps=json.loads(row["gaps_json"]),
            reasons=json.loads(row["reasons_json"]),
            ai_reason=row["ai_reason"],
        )

    def ranked(self, min_score: float = 0) -> list[dict[str, Any]]:
        """Return joined job, match, and application records by descending score."""
        rows = self.connection.execute(
            """
            SELECT j.*, m.*, a.status, a.notes
            FROM jobs j
            JOIN matches m ON m.job_id = j.id
            LEFT JOIN applications a ON a.job_id = j.id
            WHERE m.final_score >= ?
            ORDER BY m.final_score DESC, j.company, j.title
            """,
            (min_score,),
        ).fetchall()
        json_fields = {
            "components_json": "components",
            "matched_skills_json": "matched_skills",
            "matched_evidence_json": "matched_evidence",
            "gaps_json": "gaps",
            "reasons_json": "reasons",
        }
        output: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            for source, target in json_fields.items():
                record[target] = json.loads(record.pop(source))
            record.pop("raw_json", None)
            record.pop("required_skills_json", None)
            record.pop("preferred_skills_json", None)
            record.pop("responsibilities_json", None)
            output.append(record)
        return output

    def set_status(self, job_id: str, status: str, notes: str = "") -> bool:
        """Update a tracked application state and return whether the job exists."""
        exists = self.connection.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not exists:
            return False
        self.connection.execute(
            """
            INSERT INTO applications(job_id, status, notes, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status=excluded.status, notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (job_id, status, notes, utc_now()),
        )
        self.connection.commit()
        return True

    def count_jobs(self) -> int:
        """Return the current number of unique job URLs."""
        return int(self.connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def upsert_jobs(self, jobs: Iterable[Job]) -> int:
        """Persist a sequence and return the number processed."""
        count = 0
        for job in jobs:
            self.upsert_job(job)
            count += 1
        return count
