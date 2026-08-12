"""Approval-gated browser-use adapter for Agent C.

Dry-run planning is dependency-free. Actual browser control is imported only
after an approval receipt is validated against the exact private packet.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..util import read_json, utc_now, write_json


class BrowserUseError(RuntimeError):
    """Raised when an application plan or approval fails a safety invariant."""


def packet_sha256(path: Path) -> str:
    """Bind an approval to the immutable bytes the reviewer actually saw."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_form_answer_catalog(candidate: dict[str, Any]) -> dict[str, Any]:
    """Map common ATS field families to truthful profile values.

    Unknown questions and voluntary demographic disclosures are always routed
    to a human. No answer is guessed from unrelated candidate data.
    """
    contact = candidate.get("contact", {})
    links = candidate.get("links", {})
    eligibility = candidate.get("eligibility", {})
    preferences = candidate.get("preferences", {})
    standard = candidate.get("standard_answers", {})
    first = str(contact.get("first_name") or "").strip()
    last = str(contact.get("last_name") or "").strip()
    fields = {
        "first_name": first,
        "last_name": last,
        "full_name": " ".join(part for part in (first, last) if part),
        "email": contact.get("email", ""),
        "phone": contact.get("phone", ""),
        "city": contact.get("city", ""),
        "state": contact.get("state", ""),
        "country": contact.get("country", ""),
        "linkedin": links.get("linkedin", ""),
        "portfolio": links.get("portfolio", ""),
        "work_authorization": eligibility.get("authorized_to_work_us"),
        "requires_sponsorship": eligibility.get("requires_sponsorship"),
        "desired_salary": preferences.get("desired_salary", ""),
        "start_date": preferences.get("start_date", ""),
        "preferred_work_mode": preferences.get("work_mode", ""),
        "why_interested": standard.get("why_interested", ""),
        "additional_information": standard.get("additional_information", ""),
    }
    return {
        "known_fields": fields,
        "supported_controls": ["text", "textarea", "select", "radio", "checkbox", "file_upload"],
        "manual_only_topics": [
            "gender",
            "race_or_ethnicity",
            "veteran_status",
            "disability_status",
            "criminal_history",
            "unrecognized_or_ambiguous_question",
        ],
        "unknown_field_policy": "pause_and_request_human_answer",
    }


@dataclass
class BrowserApplicationPlan:
    """Non-secret execution summary suitable for logs and Paperclip status."""

    job_id: str
    job_url: str
    packet_path: str
    packet_sha256: str
    allowed_domain: str
    requested_action: str
    approval_status: str
    blockers: list[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the public-safe dry-run plan to JSON-compatible data."""
        return self.__dict__.copy()


class BrowserUseRunner:
    """Create and optionally run a browser-use application task."""

    valid_actions = {"fill_only", "fill_and_submit"}

    def __init__(self, packet_path: Path):
        if not packet_path.exists():
            raise FileNotFoundError(f"Application packet not found: {packet_path}")
        self.packet_path = packet_path
        self.packet = read_json(packet_path)
        self.job = self.packet.get("job", {})
        self.job_id = str(self.job.get("id") or "")
        self.job_url = str(self.job.get("url") or "")
        parts = urlsplit(self.job_url)
        if parts.scheme != "https" or not parts.netloc:
            raise BrowserUseError("Agent C requires an HTTPS job URL with an exact host.")
        self.allowed_domain = parts.netloc.casefold()
        self.digest = packet_sha256(packet_path)

    def approval_template(self) -> dict[str, Any]:
        """Return a pending receipt that a human can review and explicitly accept."""
        return {
            "schema_version": 1,
            "job_id": self.job_id,
            "job_url": self.job_url,
            "packet_sha256": self.digest,
            "decision": "pending",
            "allowed_action": "fill_only",
            "approved_by": "",
            "approved_at": "",
            "expires_at": "",
        }

    def write_approval_template(self, path: Path) -> Path:
        """Create a review receipt without overwriting a reviewer decision."""
        if not path.exists():
            write_json(path, self.approval_template())
        return path

    def _validate_approval(self, path: Path, requested_action: str) -> dict[str, Any]:
        if requested_action not in self.valid_actions:
            raise BrowserUseError(f"Unsupported browser action: {requested_action}")
        if not path.exists():
            raise BrowserUseError(f"Approval receipt not found: {path}")
        receipt = read_json(path)
        comparisons = {
            "job_id": self.job_id,
            "job_url": self.job_url,
            "packet_sha256": self.digest,
        }
        for field, expected in comparisons.items():
            if receipt.get(field) != expected:
                raise BrowserUseError(f"Approval receipt {field} does not match the application packet.")
        if receipt.get("decision") != "approved":
            raise BrowserUseError("Application approval is not accepted.")
        if receipt.get("allowed_action") != requested_action:
            raise BrowserUseError(
                f"Approval permits {receipt.get('allowed_action')!r}, not {requested_action!r}."
            )
        approved_at = str(receipt.get("approved_at") or "").strip()
        if not str(receipt.get("approved_by") or "").strip() or not approved_at:
            raise BrowserUseError("Approval must record approved_by and approved_at.")
        try:
            approval_time = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BrowserUseError("Approval approved_at is not a valid ISO timestamp.") from exc
        if approval_time.tzinfo is None:
            approval_time = approval_time.replace(tzinfo=timezone.utc)
        if approval_time.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise BrowserUseError("Application approval timestamp is in the future.")
        expires_at = str(receipt.get("expires_at") or "").strip()
        if expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise BrowserUseError("Approval expires_at is not a valid ISO timestamp.") from exc
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                raise BrowserUseError("Application approval has expired.")
        return receipt

    def packet_blockers(self, requested_action: str) -> list[str]:
        """Return packet-level reasons the requested browser action cannot run."""
        if requested_action not in self.valid_actions:
            return [f"Unsupported browser action: {requested_action}"]
        unresolved = [
            str(value) for value in self.packet.get("unresolved_questions", []) if str(value)
        ]
        if requested_action == "fill_and_submit" and unresolved:
            return [
                "Submission is blocked while unresolved application questions remain: "
                + ", ".join(unresolved)
            ]
        return []

    def validate_execution(self, approval_path: Path, requested_action: str) -> dict[str, Any]:
        """Validate packet readiness, exact approval, and the local resume before state changes."""
        blockers = self.packet_blockers(requested_action)
        if blockers:
            raise BrowserUseError(blockers[0])
        receipt = self._validate_approval(approval_path, requested_action)
        candidate = self.packet.get("candidate", {})
        resume_path = Path(str(candidate.get("resume_path") or ""))
        if not resume_path.exists():
            raise BrowserUseError("The approved packet's resume file is unavailable.")
        return receipt

    def plan(self, requested_action: str, approval_path: Path | None = None) -> BrowserApplicationPlan:
        """Build a public-safe plan; a missing receipt remains explicitly pending."""
        blockers = self.packet_blockers(requested_action)
        status = "blocked" if blockers else "pending"
        if not blockers and approval_path and approval_path.exists():
            receipt = read_json(approval_path)
            if receipt.get("decision") == "pending":
                status = "pending"
            else:
                try:
                    self._validate_approval(approval_path, requested_action)
                    status = "approved"
                except BrowserUseError:
                    status = "invalid"
        return BrowserApplicationPlan(
            job_id=self.job_id,
            job_url=self.job_url,
            packet_path=str(self.packet_path),
            packet_sha256=self.digest,
            allowed_domain=self.allowed_domain,
            requested_action=requested_action,
            approval_status=status,
            blockers=blockers,
            created_at=utc_now(),
        )

    def _task(self, requested_action: str) -> str:
        submit_instruction = (
            "After reviewing every field against the secure candidate data, submit once and verify the confirmation page."
            if requested_action == "fill_and_submit"
            else (
                "Fill text fields and upload the resume, but do not click anything. "
                "Report dropdown, radio, checkbox, multi-step, and final Submit/Apply controls for human completion."
            )
        )
        return f"""Open {self.job_url} and process the application for {self.job.get('title', 'the role')}.
Use only the domain-scoped secure candidate data and the supplied resume. Never invent an answer.
Handle text, textarea, dropdown, radio, checkbox, file-upload, and multi-step controls.
For demographic, criminal-history, or any unknown/ambiguous question, stop and report the exact question.
Do not bypass CAPTCHA, bot detection, access controls, or site terms.
{submit_instruction}
Return a concise list of fields filled, unresolved questions, the final URL, and whether submission occurred.
"""

    @staticmethod
    def tool_exclusions(requested_action: str) -> list[str]:
        """Remove every generic submission path when approval is fill-only."""
        if requested_action == "fill_only":
            return ["search", "click", "send_keys", "select_dropdown", "evaluate"]
        if requested_action == "fill_and_submit":
            return ["search"]
        raise BrowserUseError(f"Unsupported browser action: {requested_action}")

    def execute(
        self,
        approval_path: Path,
        requested_action: str,
        model: str = "gpt-4.1",
        max_steps: int = 40,
    ) -> dict[str, Any]:
        """Run browser-use only after exact packet/action approval is validated."""
        self.validate_execution(approval_path, requested_action)
        candidate = self.packet.get("candidate", {})
        resume_path = Path(str(candidate.get("resume_path") or ""))
        try:
            from browser_use import Agent, BrowserProfile, ChatOpenAI, Tools
        except ImportError as exc:
            raise BrowserUseError(
                "browser-use is not installed. Run scripts/install-agent-integrations.ps1 -BrowserUse."
            ) from exc
        secure_values = {
            key: str(value)
            for key, value in build_form_answer_catalog(candidate)["known_fields"].items()
            if value not in (None, "")
        }
        secure_values["resume_path"] = str(resume_path.resolve())
        profile = BrowserProfile(
            allowed_domains=[self.allowed_domain],
            headless=False,
            keep_alive=False,
            disable_security=False,
        )
        tools = Tools(exclude_actions=self.tool_exclusions(requested_action))
        llm = ChatOpenAI(model=model, temperature=0.0)
        agent = Agent(
            task=self._task(requested_action),
            llm=llm,
            browser_profile=profile,
            tools=tools,
            sensitive_data={self.allowed_domain: secure_values},
            available_file_paths=[str(resume_path.resolve())],
            max_actions_per_step=1,
            use_judge=True,
        )

        async def _run() -> Any:
            return await agent.run(max_steps=max(1, min(max_steps, 80)))

        history = asyncio.run(_run())
        final_result = history.final_result() if hasattr(history, "final_result") else str(history)
        return {
            "job_id": self.job_id,
            "requested_action": requested_action,
            "completed_at": utc_now(),
            "result": final_result,
        }
