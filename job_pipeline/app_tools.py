"""Broker specifications for bounded pipeline runs and local application drafts."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .tool_broker import ToolContext, ToolPolicy, ToolResult, ToolSpec
from .util import redact_secrets


Runner = Callable[..., subprocess.CompletedProcess[str]]
PROVIDER_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,71}$")
CONTROL_PROVIDER_ENV_KEYS = {
    "EXPEDIENT_PROVIDER_URL",
    "EXPEDIENT_PROVIDER_KEY_ENV",
    "FREECHAIN_ACCESS_KEY",
}


@dataclass(frozen=True)
class PipelineCommandResult:
    """Bounded subprocess status returned to a tool caller."""

    status: str
    exit_code: int
    output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "output": self.output,
        }


class JobPipelineToolAdapter:
    """Expose fixed non-submitting job pipeline commands to the tool broker."""

    def __init__(
        self,
        project_root: Path,
        *,
        python_binary: str | Path | None = None,
        runner: Runner | None = None,
        max_output_bytes: int = 131_072,
    ):
        self.project_root = Path(project_root).resolve()
        self.python_binary = str(python_binary or os.environ.get("PYTHON_EXE") or sys.executable)
        self.runner = runner or subprocess.run
        self.max_output_bytes = max(4096, int(max_output_bytes))

    def _run(self, command: list[str], *, timeout_seconds: float) -> PipelineCommandResult:
        arguments = [self.python_binary, "-m", "job_pipeline", *command]
        child_environment = dict(os.environ)
        credential_env = child_environment.get("EXPEDIENT_PROVIDER_KEY_ENV", "").strip().upper()
        blocked = set(CONTROL_PROVIDER_ENV_KEYS)
        if PROVIDER_ENV_NAME.fullmatch(credential_env):
            blocked.add(credential_env)
        child_environment = {
            key: value
            for key, value in child_environment.items()
            if key.upper() not in blocked
        }
        child_environment.update({
            "PYTHONPATH": str(self.project_root),
            "PYTHONUNBUFFERED": "1",
        })
        try:
            completed = self.runner(
                arguments,
                cwd=str(self.project_root),
                env=child_environment,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1.0, min(float(timeout_seconds), 900.0)),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Job pipeline command could not complete: {exc}") from exc
        output = redact_secrets(f"{completed.stdout}\n{completed.stderr}").strip()
        if len(output.encode("utf-8")) > self.max_output_bytes:
            raise RuntimeError("Job pipeline output exceeded the tool cap.")
        return PipelineCommandResult(
            status="ok" if completed.returncode == 0 else "failed",
            exit_code=int(completed.returncode),
            output=output,
        )

    @staticmethod
    def _document_path(raw_path: str, label: str, suffix: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if path.suffix.casefold() != suffix or not path.is_file():
            raise ValueError(f"{label} must be an existing {suffix} file.")
        return path

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        """Return unattended pipeline and local draft tool contracts."""
        def run_pipeline(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
            result = self._run(
                [
                    "run",
                    "--max-jobs", str(arguments["max_jobs"]),
                    "--concurrency", str(arguments["concurrency"]),
                    "--min-score", str(arguments["min_score"]),
                ],
                timeout_seconds=900,
            )
            return ToolResult(data=result.to_dict(), summary=f"Pipeline run: {result.status}")

        def prepare_draft(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
            job_id = str(arguments["job_id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", job_id):
                raise ValueError("Draft job identifier is invalid.")
            resume = self._document_path(str(arguments["resume_path"]), "Resume", ".docx")
            profile = self._document_path(
                str(arguments["application_profile_path"]),
                "Application profile",
                ".json",
            )
            result = self._run(
                [
                    "agent-c",
                    job_id,
                    "--resume", str(resume),
                    "--application-profile", str(profile),
                ],
                timeout_seconds=180,
            )
            return ToolResult(data=result.to_dict(), summary=f"Application draft: {result.status}")

        return (
            ToolSpec(
                name="jobs.pipeline.run",
                description=(
                    "Discover, extract, score, store, and report a bounded batch of jobs. "
                    "This never submits an application."
                ),
                policy=ToolPolicy.LOCAL_WRITE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "max_jobs": {"type": "integer", "minimum": 1, "maximum": 500},
                        "concurrency": {"type": "integer", "minimum": 1, "maximum": 4},
                        "min_score": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                    "required": ["max_jobs", "concurrency", "min_score"],
                    "additionalProperties": False,
                },
                handler=run_pipeline,
                timeout_seconds=910,
                max_output_bytes=self.max_output_bytes,
            ),
            ToolSpec(
                name="jobs.application.prepare_draft",
                description=(
                    "Prepare a truthful local application packet from a reviewed Agent B "
                    "handoff. This never fills or submits an employer form."
                ),
                policy=ToolPolicy.EXTERNAL_DRAFT,
                input_schema={
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "minLength": 8, "maxLength": 80},
                        "resume_path": {"type": "string", "minLength": 1, "maxLength": 1024},
                        "application_profile_path": {
                            "type": "string", "minLength": 1, "maxLength": 1024
                        },
                    },
                    "required": ["job_id", "resume_path", "application_profile_path"],
                    "additionalProperties": False,
                },
                handler=prepare_draft,
                timeout_seconds=190,
                max_output_bytes=self.max_output_bytes,
            ),
        )
