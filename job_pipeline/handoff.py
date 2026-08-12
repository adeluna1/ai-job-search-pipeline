"""Integrity-bound Agent B to Agent C handoff contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .jobs import Job
from .util import canonical_url, utc_now


HANDOFF_SCHEMA_VERSION = 1


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_agent_c_handoff(record: dict[str, Any], *, created_at: str | None = None) -> dict[str, Any]:
    """Create a compact handoff only for a fully verified Agent B apply decision."""
    analysis = record.get("analysis", {})
    freshness = analysis.get("freshness", {})
    if analysis.get("recommendation") != "apply":
        raise ValueError("Agent C handoffs may contain only Agent B apply decisions.")
    if analysis.get("live_verified") is not True:
        raise ValueError("Agent C handoff requires Agent B live verification.")
    if analysis.get("direct_domain_verified") is not True:
        raise ValueError("Agent C handoff requires a verified employer or ATS domain.")
    if freshness.get("fresh") is not True:
        raise ValueError("Agent C handoff requires an unambiguous in-window posting date.")
    if record.get("geography_eligible") is False:
        raise ValueError("Agent C handoff requires the requested geography.")

    payload = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "job_id": str(record.get("job_id") or ""),
        "job_url": canonical_url(str(record.get("url") or "")),
        "title": str(record.get("title") or ""),
        "company": str(record.get("company") or ""),
        "recommendation": "apply",
        "reviewed_at": str(analysis.get("verified_at") or ""),
        "live_verified": True,
        "direct_domain_verified": True,
        "freshness": freshness,
        "geography_eligible": record.get("geography_eligible"),
        "created_at": created_at or utc_now(),
    }
    if not payload["job_id"] or not payload["job_url"] or not payload["reviewed_at"]:
        raise ValueError("Agent C handoff is missing job identity or review time.")
    return {**payload, "handoff_sha256": _digest(payload)}


def validate_agent_c_handoff(
    review_payload: dict[str, Any],
    job: Job,
    *,
    max_age_hours: int = 24,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one exact review record and return its analysis and handoff."""
    records = review_payload.get("records", [])
    handoffs = review_payload.get("agent_c_handoffs", [])
    record = next((item for item in records if item.get("job_id") == job.id), None)
    handoff = next((item for item in handoffs if item.get("job_id") == job.id), None)
    if not isinstance(record, dict) or not isinstance(handoff, dict):
        raise ValueError("Agent C requires a current Agent B apply review and handoff for this job.")

    supplied_digest = str(handoff.get("handoff_sha256") or "")
    digest_payload = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    if not supplied_digest or supplied_digest != _digest(digest_payload):
        raise ValueError("Agent B to Agent C handoff integrity check failed.")
    if handoff.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        raise ValueError("Agent C handoff schema is unsupported.")
    if canonical_url(str(handoff.get("job_url") or "")) != canonical_url(job.url):
        raise ValueError("Agent C handoff URL does not match the stored employer posting.")

    analysis = record.get("analysis", {})
    required = {
        "recommendation": analysis.get("recommendation") == "apply",
        "live verification": analysis.get("live_verified") is True,
        "direct-domain verification": analysis.get("direct_domain_verified") is True,
        "freshness": analysis.get("freshness", {}).get("fresh") is True,
        "geography": record.get("geography_eligible") is not False,
    }
    failed = [name for name, passed in required.items() if not passed]
    if failed:
        raise ValueError("Agent C handoff failed required gate(s): " + ", ".join(failed))
    if str(analysis.get("verified_at") or "") != str(handoff.get("reviewed_at") or ""):
        raise ValueError("Agent C handoff no longer matches the Agent B review timestamp.")

    try:
        created = datetime.fromisoformat(str(handoff.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Agent C handoff has an invalid creation timestamp.") from exc
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if created.astimezone(timezone.utc) > current:
        raise ValueError("Agent C handoff timestamp is in the future.")
    if current - created.astimezone(timezone.utc) > timedelta(hours=max(1, max_age_hours)):
        raise ValueError("Agent C handoff expired; rerun Agent B live verification.")
    return analysis, handoff
