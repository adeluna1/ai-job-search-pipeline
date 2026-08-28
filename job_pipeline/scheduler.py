"""Restart-safe scheduling for policy-bounded job-hunting workflows."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .tool_broker import ToolBroker, ToolContext, ToolPolicy
from .util import redact_secrets, utc_now
from .web_workflows import (
    WorkflowDefinition,
    WorkflowRunner,
    WorkflowStep,
)


ALLOWED_SCHEDULE_POLICIES = frozenset({
    ToolPolicy.READ.value,
    ToolPolicy.LOCAL_WRITE.value,
    ToolPolicy.EXTERNAL_DRAFT.value,
})


class ScheduleError(RuntimeError):
    """Base class for schedule storage and execution failures."""


class ScheduleValidationError(ScheduleError):
    """Raised before persistence when a schedule is unsafe or malformed."""


@dataclass(frozen=True)
class Recurrence:
    """An interval or daily wall-clock recurrence."""

    kind: str
    interval_minutes: int = 0
    local_time: str = ""
    timezone_name: str = "UTC"

    @classmethod
    def interval(cls, minutes: int) -> "Recurrence":
        return cls("interval", interval_minutes=int(minutes))

    @classmethod
    def daily(cls, local_time: str, timezone_name: str) -> "Recurrence":
        return cls("daily", local_time=local_time, timezone_name=timezone_name)

    def validate(self) -> None:
        if self.kind == "interval":
            if not 5 <= self.interval_minutes <= 10_080:
                raise ScheduleValidationError("Interval must be between 5 minutes and 7 days.")
            return
        if self.kind != "daily":
            raise ScheduleValidationError("Schedule recurrence must be interval or daily.")
        try:
            datetime.strptime(self.local_time, "%H:%M")
            ZoneInfo(self.timezone_name)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ScheduleValidationError("Daily schedule time or timezone is invalid.") from exc

    def next_after(self, now: datetime) -> datetime:
        """Return the first recurrence strictly after an aware UTC instant."""
        current = _as_utc(now)
        if self.kind == "interval":
            return current + timedelta(minutes=self.interval_minutes)
        zone = ZoneInfo(self.timezone_name)
        local_now = current.astimezone(zone)
        parsed = datetime.strptime(self.local_time, "%H:%M").time()
        candidate = datetime.combine(local_now.date(), wall_time(parsed.hour, parsed.minute), zone)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)


@dataclass(frozen=True)
class ScheduleRecord:
    """One persisted schedule and its next due instant."""

    id: int
    name: str
    workflow: WorkflowDefinition
    recurrence: Recurrence
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    created_at: str
    updated_at: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ScheduleValidationError("Schedule timestamps must include a timezone.")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(timezone.utc) if value else None


def _workflow_json(definition: WorkflowDefinition) -> str:
    return json.dumps(
        {
            "name": definition.name,
            "steps": [asdict(step) for step in definition.steps],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _workflow_from_json(value: str) -> WorkflowDefinition:
    payload = json.loads(value)
    steps = tuple(
        WorkflowStep(
            id=str(item["id"]),
            tool=str(item["tool"]),
            arguments=dict(item.get("arguments", {})),
            depends_on=tuple(item.get("depends_on", ())),
            max_attempts=int(item.get("max_attempts", 2)),
        )
        for item in payload["steps"]
    )
    return WorkflowDefinition(str(payload["name"]), steps)


class ScheduleService:
    """Persist schedules and execute due workflows with a durable wake lease."""

    def __init__(
        self,
        database_path: Path,
        runner: WorkflowRunner,
        broker: ToolBroker,
    ):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.broker = broker
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database_path, timeout=10, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                workflow_json TEXT NOT NULL,
                recurrence_json TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                next_run_at TEXT NOT NULL,
                last_run_at TEXT,
                locked_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schedule_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                workflow_run_id INTEGER,
                status TEXT NOT NULL,
                error_summary TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.commit()
            self.connection.close()

    def _validate_workflow(self, definition: WorkflowDefinition) -> None:
        self.runner.validate(definition)
        policies = {item["name"]: item["policy"] for item in self.broker.list_tools()}
        for step in definition.steps:
            if policies.get(step.tool) not in ALLOWED_SCHEDULE_POLICIES:
                raise ScheduleValidationError(
                    f"Scheduled workflow tool is outside unattended policy: {step.tool}"
                )

    def create(
        self,
        name: str,
        workflow: WorkflowDefinition,
        recurrence: Recurrence,
        *,
        now: datetime | None = None,
        enabled: bool = True,
    ) -> ScheduleRecord:
        """Validate and persist an unattended-safe workflow schedule."""
        normalized_name = name.strip()
        if not normalized_name or len(normalized_name) > 160:
            raise ScheduleValidationError("Schedule name is invalid.")
        recurrence.validate()
        self._validate_workflow(workflow)
        current = _as_utc(now or datetime.now(timezone.utc))
        next_run = current if recurrence.kind == "interval" else recurrence.next_after(current)
        stamp = utc_now()
        with self._lock:
            cursor = self.connection.execute(
                """
                INSERT INTO schedules(
                    name, workflow_json, recurrence_json, enabled, next_run_at,
                    last_run_at, locked_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    normalized_name,
                    _workflow_json(workflow),
                    json.dumps(asdict(recurrence), sort_keys=True),
                    int(enabled),
                    _iso(next_run),
                    stamp,
                    stamp,
                ),
            )
            self.connection.commit()
            return self.get(int(cursor.lastrowid))

    @staticmethod
    def _record(row: sqlite3.Row) -> ScheduleRecord:
        recurrence = Recurrence(**json.loads(str(row["recurrence_json"])))
        return ScheduleRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            workflow=_workflow_from_json(str(row["workflow_json"])),
            recurrence=recurrence,
            enabled=bool(row["enabled"]),
            next_run_at=_parse(str(row["next_run_at"])) or datetime.now(timezone.utc),
            last_run_at=_parse(row["last_run_at"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def get(self, schedule_id: int) -> ScheduleRecord:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM schedules WHERE id=?", (schedule_id,)
            ).fetchone()
        if not row:
            raise ScheduleValidationError("Schedule does not exist.")
        return self._record(row)

    def list(self) -> list[ScheduleRecord]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM schedules ORDER BY enabled DESC, next_run_at, id"
            ).fetchall()
        return [self._record(row) for row in rows]

    def set_enabled(
        self,
        schedule_id: int,
        enabled: bool,
        *,
        now: datetime | None = None,
    ) -> ScheduleRecord:
        with self._lock:
            schedule = self.get(schedule_id)
            current = _as_utc(now or datetime.now(timezone.utc))
            next_run = current if enabled else schedule.next_run_at
            self.connection.execute(
                "UPDATE schedules SET enabled=?, next_run_at=?, locked_until=NULL, updated_at=? WHERE id=?",
                (int(enabled), _iso(next_run), utc_now(), schedule_id),
            )
            self.connection.commit()
            return self.get(schedule_id)

    def due(self, *, now: datetime, limit: int = 10) -> list[ScheduleRecord]:
        current = _as_utc(now)
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT * FROM schedules
                WHERE enabled=1 AND next_run_at<=?
                  AND (locked_until IS NULL OR locked_until<=?)
                ORDER BY next_run_at, id LIMIT ?
                """,
                (_iso(current), _iso(current), max(1, min(int(limit), 100))),
            ).fetchall()
        return [self._record(row) for row in rows]

    def claim(
        self,
        schedule_id: int,
        *,
        now: datetime,
        lease_seconds: int = 900,
    ) -> bool:
        """Atomically acquire a bounded wake lease across scheduler processes."""
        current = _as_utc(now)
        locked_until = current + timedelta(seconds=max(30, min(int(lease_seconds), 3600)))
        with self._lock:
            cursor = self.connection.execute(
                """
                UPDATE schedules SET locked_until=?, updated_at=?
                WHERE id=? AND enabled=1
                  AND (locked_until IS NULL OR locked_until<=?)
                """,
                (_iso(locked_until), utc_now(), schedule_id, _iso(current)),
            )
            self.connection.commit()
            return cursor.rowcount == 1

    def run_due(self, *, now: datetime, limit: int = 10) -> list[dict[str, Any]]:
        """Run each due schedule once and coalesce any missed recurrence window."""
        current = _as_utc(now)
        summaries: list[dict[str, Any]] = []
        for schedule in self.due(now=current, limit=limit):
            if not self.claim(schedule.id, now=current):
                continue
            started = utc_now()
            workflow_run_id: int | None = None
            error = ""
            try:
                result = self.runner.run(
                    schedule.workflow,
                    ToolContext(
                        actor="scheduler",
                        request_id=f"schedule:{schedule.id}:{started}",
                    ),
                )
                workflow_run_id = result.run_id
                status = result.status
                error = result.error
            except Exception as exc:
                status = "failed"
                error = redact_secrets(str(exc))[:500]
            finished = utc_now()
            next_run = schedule.recurrence.next_after(current)
            with self._lock:
                self.connection.execute(
                    """
                    INSERT INTO schedule_runs(
                        schedule_id, workflow_run_id, status, error_summary,
                        started_at, finished_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (schedule.id, workflow_run_id, status, error[:500], started, finished),
                )
                self.connection.execute(
                    """
                    UPDATE schedules
                    SET last_run_at=?, next_run_at=?, locked_until=NULL, updated_at=?
                    WHERE id=?
                    """,
                    (_iso(current), _iso(next_run), finished, schedule.id),
                )
                self.connection.commit()
            summaries.append({
                "schedule_id": schedule.id,
                "workflow_run_id": workflow_run_id,
                "status": status,
                "next_run_at": _iso(next_run),
                "error": error[:500],
            })
        return summaries

    def history(self, schedule_id: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM schedule_runs WHERE schedule_id=? ORDER BY id DESC",
                (schedule_id,),
            ).fetchall()
        return [dict(row) for row in rows]
