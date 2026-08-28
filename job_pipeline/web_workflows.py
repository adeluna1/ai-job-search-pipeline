"""Original MIT workflow runtime for brokered web and agent tools.

Definitions are deliberately small data objects, not executable code. The
runtime validates dependencies and interpolation, records each step before and
after execution, retries bounded transient failures, resumes completed runs,
and leaves external-action authorization to the central tool broker.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .tool_broker import (
    ApprovalRequiredError,
    ToolBroker,
    ToolBrokerError,
    ToolCancelledError,
    ToolContext,
    ToolExecutionError,
    ToolResult,
    ToolTimeoutError,
)
from .util import redact_secrets, utc_now


class WorkflowError(RuntimeError):
    """Base class for workflow definition and execution failures."""


class WorkflowValidationError(WorkflowError):
    """Raised before execution when a workflow is invalid."""


class WorkflowCircuitOpenError(WorkflowError):
    """Raised when repeated tool failures open the local circuit breaker."""


@dataclass(frozen=True)
class WorkflowStep:
    """One typed tool invocation and its explicit prerequisites."""

    id: str
    tool: str
    arguments: Mapping[str, Any]
    depends_on: tuple[str, ...] = ()
    max_attempts: int = 2


@dataclass(frozen=True)
class WorkflowDefinition:
    """An ordered, acyclic set of broker-backed workflow steps."""

    name: str
    steps: tuple[WorkflowStep, ...]


@dataclass(frozen=True)
class WorkflowRunResult:
    """Current durable state and structured outputs for one run."""

    run_id: int | None
    status: str
    step_states: Mapping[str, str]
    outputs: Mapping[str, Any]
    error: str = ""


_REFERENCE = re.compile(r"^\$\{([a-zA-Z][a-zA-Z0-9_-]{0,63})\.data(?:\.([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)*))?\}$")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _definition_payload(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "name": definition.name,
        "steps": [asdict(step) for step in definition.steps],
    }


def _definition_digest(definition: WorkflowDefinition) -> str:
    return hashlib.sha256(_stable_json(_definition_payload(definition)).encode("utf-8")).hexdigest()


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _lookup_reference(token: str, outputs: Mapping[str, Any]) -> Any:
    match = _REFERENCE.fullmatch(token)
    if not match:
        raise WorkflowValidationError("Workflow interpolation must be one exact data reference.")
    step_id, path = match.groups()
    if step_id not in outputs:
        raise WorkflowValidationError(f"Referenced step has no output: {step_id}")
    value: Any = outputs[step_id].get("data")
    for part in path.split(".") if path else ():
        if not isinstance(value, Mapping) or part not in value:
            raise WorkflowValidationError(f"Workflow result field is unavailable: {step_id}.{path}")
        value = value[part]
    return value


def _interpolate(value: Any, outputs: Mapping[str, Any]) -> Any:
    if isinstance(value, str) and "${" in value:
        return _lookup_reference(value, outputs)
    if isinstance(value, Mapping):
        return {str(key): _interpolate(item, outputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, outputs) for item in value]
    if isinstance(value, tuple):
        return [_interpolate(item, outputs) for item in value]
    return value


class WorkflowRunner:
    """Validate and durably execute workflows through a ``ToolBroker``."""

    def __init__(
        self,
        broker: ToolBroker,
        database_path: Path,
        *,
        retry_delay_seconds: float = 0.2,
        circuit_failure_threshold: int = 3,
    ):
        if retry_delay_seconds < 0 or circuit_failure_threshold <= 0:
            raise ValueError("Workflow retry and circuit settings are invalid.")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.broker = broker
        self.retry_delay_seconds = retry_delay_seconds
        self.circuit_failure_threshold = circuit_failure_threshold
        self._failures: dict[str, int] = {}
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                definition_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workflow_steps (
                run_id INTEGER NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
                step_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                output_json TEXT NOT NULL DEFAULT '',
                error_summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, step_id)
            );
            CREATE TABLE IF NOT EXISTS workflow_dataset (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
                step_id TEXT NOT NULL,
                row_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.commit()
            self.connection.close()

    def validate(self, definition: WorkflowDefinition) -> None:
        """Reject unknown tools, invalid DAGs, and executable interpolation syntax."""
        if not definition.name.strip() or len(definition.name) > 128:
            raise WorkflowValidationError("Workflow name must contain between 1 and 128 characters.")
        if not definition.steps or len(definition.steps) > 100:
            raise WorkflowValidationError("A workflow must contain between 1 and 100 steps.")
        known_tools = {item["name"] for item in self.broker.list_tools()}
        seen: set[str] = set()
        for step in definition.steps:
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", step.id):
                raise WorkflowValidationError("Workflow step identifiers are invalid.")
            if step.id in seen:
                raise WorkflowValidationError(f"Duplicate workflow step: {step.id}")
            if step.tool not in known_tools:
                raise WorkflowValidationError(f"Unknown workflow tool: {step.tool}")
            if not isinstance(step.arguments, Mapping):
                raise WorkflowValidationError("Workflow step arguments must be objects.")
            if not 1 <= step.max_attempts <= 5:
                raise WorkflowValidationError("Workflow attempts must be between 1 and 5.")
            missing = [dependency for dependency in step.depends_on if dependency not in seen]
            if missing:
                raise WorkflowValidationError(f"Workflow dependency is unavailable: {missing[0]}")
            for text in _walk_strings(step.arguments):
                if "${" not in text:
                    continue
                match = _REFERENCE.fullmatch(text)
                if not match:
                    raise WorkflowValidationError(
                        "Workflow interpolation permits only exact prior-step data references."
                    )
                referenced = match.group(1)
                if referenced not in seen or referenced not in step.depends_on:
                    raise WorkflowValidationError(
                        f"Interpolated step must be an explicit dependency: {referenced}"
                    )
            seen.add(step.id)

    def _create_run(self, definition: WorkflowDefinition) -> int:
        now = utc_now()
        cursor = self.connection.execute(
            "INSERT INTO workflow_runs(name, definition_digest, status, created_at, updated_at) VALUES (?, ?, 'running', ?, ?)",
            (definition.name, _definition_digest(definition), now, now),
        )
        run_id = int(cursor.lastrowid)
        self.connection.executemany(
            "INSERT INTO workflow_steps(run_id, step_id, tool_name, status, updated_at) VALUES (?, ?, ?, 'pending', ?)",
            [(run_id, step.id, step.tool, now) for step in definition.steps],
        )
        self.connection.commit()
        return run_id

    def _resume_state(
        self,
        definition: WorkflowDefinition,
        run_id: int,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        row = self.connection.execute(
            "SELECT definition_digest FROM workflow_runs WHERE id=?", (run_id,)
        ).fetchone()
        if not row:
            raise WorkflowValidationError("Workflow run does not exist.")
        if row["definition_digest"] != _definition_digest(definition):
            raise WorkflowValidationError("Workflow definition changed and cannot resume this run.")
        states: dict[str, str] = {}
        outputs: dict[str, Any] = {}
        rows = self.connection.execute(
            "SELECT step_id, status, output_json FROM workflow_steps WHERE run_id=? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        for item in rows:
            states[str(item["step_id"])] = str(item["status"])
            if item["status"] == "succeeded" and item["output_json"]:
                outputs[str(item["step_id"])] = json.loads(str(item["output_json"]))
        return states, outputs

    def _set_step(
        self,
        run_id: int,
        step_id: str,
        status: str,
        *,
        attempts: int | None = None,
        output: Any | None = None,
        error: str = "",
    ) -> None:
        output_json = "" if output is None else _stable_json(output)
        safe_error = redact_secrets(error).replace("\r", " ").replace("\n", " ")[:500]
        if attempts is None:
            self.connection.execute(
                "UPDATE workflow_steps SET status=?, output_json=?, error_summary=?, updated_at=? WHERE run_id=? AND step_id=?",
                (status, output_json, safe_error, utc_now(), run_id, step_id),
            )
        else:
            self.connection.execute(
                "UPDATE workflow_steps SET status=?, attempts=?, output_json=?, error_summary=?, updated_at=? WHERE run_id=? AND step_id=?",
                (status, attempts, output_json, safe_error, utc_now(), run_id, step_id),
            )
        self.connection.commit()

    def _finish(self, run_id: int, status: str) -> None:
        self.connection.execute(
            "UPDATE workflow_runs SET status=?, updated_at=? WHERE id=?",
            (status, utc_now(), run_id),
        )
        self.connection.commit()

    def dataset(self, run_id: int) -> list[dict[str, Any]]:
        """Return ordered structured rows emitted by successful steps."""
        rows = self.connection.execute(
            "SELECT step_id, row_json, created_at FROM workflow_dataset WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [
            {
                "step_id": str(row["step_id"]),
                "row": json.loads(str(row["row_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def run(
        self,
        definition: WorkflowDefinition,
        context: ToolContext,
        *,
        run_id: int | None = None,
        dry_run: bool = False,
    ) -> WorkflowRunResult:
        """Execute or resume a workflow, stopping safely on approval or cancellation."""
        self.validate(definition)
        if dry_run:
            return WorkflowRunResult(
                run_id=None,
                status="dry_run",
                step_states={step.id: "planned" for step in definition.steps},
                outputs={},
            )
        with self._lock:
            if run_id is None:
                run_id = self._create_run(definition)
            states, outputs = self._resume_state(definition, run_id)

            for step in definition.steps:
                if states.get(step.id) == "succeeded":
                    continue
                if context.cancel_event is not None and context.cancel_event.is_set():
                    for remaining in definition.steps:
                        if states.get(remaining.id) != "succeeded":
                            states[remaining.id] = "cancelled"
                            self._set_step(run_id, remaining.id, "cancelled", error="Workflow cancelled.")
                    self._finish(run_id, "cancelled")
                    return WorkflowRunResult(run_id, "cancelled", states, outputs)
                if any(states.get(dependency) != "succeeded" for dependency in step.depends_on):
                    states[step.id] = "blocked"
                    self._set_step(run_id, step.id, "blocked", error="A dependency did not succeed.")
                    continue
                if self._failures.get(step.tool, 0) >= self.circuit_failure_threshold:
                    states[step.id] = "circuit_open"
                    self._set_step(run_id, step.id, "circuit_open", error="Tool circuit is open.")
                    self._finish(run_id, "failed")
                    return WorkflowRunResult(run_id, "failed", states, outputs, "Tool circuit is open.")

                try:
                    arguments = _interpolate(step.arguments, outputs)
                except WorkflowValidationError as exc:
                    states[step.id] = "failed"
                    self._set_step(run_id, step.id, "failed", error=str(exc))
                    self._finish(run_id, "failed")
                    return WorkflowRunResult(run_id, "failed", states, outputs, str(exc))

                last_error = ""
                for attempt in range(1, step.max_attempts + 1):
                    try:
                        step_context = replace(
                            context,
                            request_id=f"{context.request_id}:{run_id}:{step.id}:{attempt}",
                        )
                        result: ToolResult = self.broker.invoke(step.tool, arguments, step_context)
                    except ApprovalRequiredError:
                        states[step.id] = "awaiting_approval"
                        self._set_step(
                            run_id,
                            step.id,
                            "awaiting_approval",
                            attempts=attempt,
                            error="Exact approval is required for this step.",
                        )
                        self._finish(run_id, "awaiting_approval")
                        return WorkflowRunResult(
                            run_id,
                            "awaiting_approval",
                            states,
                            outputs,
                            "Exact approval is required for this step.",
                        )
                    except ToolCancelledError:
                        states[step.id] = "cancelled"
                        self._set_step(run_id, step.id, "cancelled", attempts=attempt)
                        self._finish(run_id, "cancelled")
                        return WorkflowRunResult(run_id, "cancelled", states, outputs)
                    except (ToolExecutionError, ToolTimeoutError) as exc:
                        last_error = str(exc)
                        self._failures[step.tool] = self._failures.get(step.tool, 0) + 1
                        if attempt < step.max_attempts and self.retry_delay_seconds:
                            time.sleep(self.retry_delay_seconds)
                        continue
                    except ToolBrokerError as exc:
                        last_error = str(exc)
                        break
                    else:
                        payload = {
                            "data": result.data,
                            "metadata": dict(result.metadata),
                            "summary": redact_secrets(result.summary)[:500],
                        }
                        states[step.id] = "succeeded"
                        outputs[step.id] = payload
                        self._failures[step.tool] = 0
                        self._set_step(
                            run_id,
                            step.id,
                            "succeeded",
                            attempts=attempt,
                            output=payload,
                        )
                        self.connection.execute(
                            "INSERT INTO workflow_dataset(run_id, step_id, row_json, created_at) VALUES (?, ?, ?, ?)",
                            (run_id, step.id, _stable_json(payload), utc_now()),
                        )
                        self.connection.commit()
                        break
                else:
                    pass

                if states.get(step.id) != "succeeded":
                    states[step.id] = "failed"
                    safe_error = redact_secrets(last_error)[:500]
                    self._set_step(
                        run_id,
                        step.id,
                        "failed",
                        attempts=step.max_attempts,
                        error=safe_error,
                    )
                    self._finish(run_id, "failed")
                    return WorkflowRunResult(run_id, "failed", states, outputs, safe_error)

            status = "succeeded" if all(value == "succeeded" for value in states.values()) else "failed"
            self._finish(run_id, status)
            return WorkflowRunResult(run_id, status, states, outputs)
