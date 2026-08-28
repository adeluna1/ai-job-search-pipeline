"""HTTP adapter for the optional srbhr/Resume-Matcher service."""

from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ResumeMatcherError(RuntimeError):
    """Raised when Resume-Matcher is unavailable or returns an invalid response."""


Transport = Callable[[str, str, bytes | None, dict[str, str]], dict[str, Any]]


@dataclass
class ATSAssessment:
    """Small stable projection of Resume-Matcher's ATS preview response."""

    overall_score: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    missing_keywords: list[str] = field(default_factory=list)
    injectable_keywords: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the stable ATS projection without tailored resume contents."""
        return {
            "provider": "resume-matcher",
            "assessment_stage": "tailoring_preview",
            "overall_score": self.overall_score,
            "sub_scores": self.sub_scores,
            "missing_keywords": self.missing_keywords,
            "injectable_keywords": self.injectable_keywords,
            "recommendations": self.recommendations,
        }


class ResumeMatcherClient:
    """Minimal stdlib client for a user-controlled Resume-Matcher API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:3000/api/v1",
        timeout: int = 180,
        transport: Transport | None = None,
    ):
        cleaned = base_url.rstrip("/")
        parts = urlsplit(cleaned)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parts.username is not None
            or parts.password is not None
        ):
            raise ResumeMatcherError("Resume-Matcher must use a loopback HTTP endpoint.")
        self.base_url = cleaned if cleaned.endswith("/api/v1") else cleaned + "/api/v1"
        self.timeout = timeout
        self._transport = transport or self._default_transport

    def _default_transport(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        request = Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            raise ResumeMatcherError(f"Resume-Matcher HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise ResumeMatcherError(f"Resume-Matcher is unavailable at {self.base_url}: {exc}") from exc
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ResumeMatcherError("Resume-Matcher returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise ResumeMatcherError("Resume-Matcher response was not an object.")
        return data

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        return self._transport(method, path, body, headers)

    def health(self) -> bool:
        """Check only the service process; the upstream health endpoint avoids an LLM call."""
        return self._json("GET", "/health").get("status") == "healthy"

    def upload_resume(self, path: Path) -> str:
        """Upload one explicitly authorized resume using multipart/form-data."""
        if not path.exists():
            raise FileNotFoundError(f"Resume not found: {path}")
        boundary = "----JobPipeline" + uuid.uuid4().hex
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        filename = path.name.replace('"', "").replace("\r", "").replace("\n", "")
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("ascii")
        data = self._transport(
            "POST",
            "/resumes/upload",
            body,
            {"Accept": "application/json", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        resume_id = str(data.get("resume_id") or "")
        if not resume_id:
            raise ResumeMatcherError("Resume-Matcher upload did not return resume_id.")
        if data.get("processing_status") == "failed":
            raise ResumeMatcherError("Resume-Matcher could not process the uploaded resume.")
        return resume_id

    def upload_jobs(self, descriptions: list[str], resume_id: str) -> list[str]:
        """Store one batch of job descriptions and preserve input ordering."""
        data = self._json(
            "POST",
            "/jobs/upload",
            {"job_descriptions": descriptions, "resume_id": resume_id},
        )
        job_ids = data.get("job_id")
        if not isinstance(job_ids, list) or len(job_ids) != len(descriptions):
            raise ResumeMatcherError("Resume-Matcher returned an unexpected job_id list.")
        return [str(value) for value in job_ids]

    def preview(self, resume_id: str, job_id: str) -> ATSAssessment:
        """Request a non-persisting tailoring preview and project its ATS evidence."""
        data = self._json(
            "POST",
            "/resumes/improve/preview",
            {"resume_id": resume_id, "job_id": job_id},
        )
        ats = data.get("data", {}).get("ats_score")
        if not isinstance(ats, dict):
            raise ResumeMatcherError("Resume-Matcher preview did not include ats_score.")
        try:
            score = float(ats.get("overall_score", 0))
        except (TypeError, ValueError) as exc:
            raise ResumeMatcherError("Resume-Matcher returned an invalid ATS score.") from exc
        sub_scores = ats.get("sub_scores") if isinstance(ats.get("sub_scores"), dict) else {}
        try:
            projected_sub_scores = {str(key): float(value) for key, value in sub_scores.items()}
        except (TypeError, ValueError) as exc:
            raise ResumeMatcherError("Resume-Matcher returned invalid ATS sub-scores.") from exc

        def _strings(field_name: str) -> list[str]:
            values = ats.get(field_name, [])
            return [str(value) for value in values] if isinstance(values, list) else []

        return ATSAssessment(
            overall_score=max(0.0, min(100.0, score)),
            sub_scores=projected_sub_scores,
            missing_keywords=_strings("missing_keywords"),
            injectable_keywords=_strings("injectable_keywords"),
            recommendations=_strings("recommendations"),
        )
