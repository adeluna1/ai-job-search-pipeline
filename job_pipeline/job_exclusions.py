"""Durable exclusions for closed, removed, unverifiable, or previously sent roles."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .application_history import job_identity, job_identity_from_fields
from .jobs import Job
from .util import canonical_url, read_json


def load_job_exclusions(path: Path) -> dict[str, Any]:
    """Load the exclusion registry, returning an empty schema when it is absent."""
    if not path.exists():
        return {"schema_version": 1, "updated_at": "", "jobs": []}
    value = read_json(path)
    jobs = value.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError(f"Job-exclusion registry jobs must be a list: {path}")
    return {"schema_version": 1, "updated_at": value.get("updated_at", ""), "jobs": jobs}


def partition_excluded_jobs(
    jobs: Iterable[Job], registry_path: Path
) -> tuple[list[Job], list[Job]]:
    """Split jobs into eligible and explicitly excluded collections."""
    entries = load_job_exclusions(registry_path)["jobs"]
    identities = {
        str(item.get("identity_key") or "")
        for item in entries
        if item.get("identity_key")
    }
    identities.update(
        job_identity_from_fields(
            str(item.get("company") or ""),
            str(item.get("title") or ""),
        )
        for item in entries
        if item.get("company") and item.get("title")
    )
    job_ids = {
        str(job_id)
        for item in entries
        for job_id in item.get("job_ids", [])
        if str(job_id)
    }
    urls = {
        canonical_url(str(url))
        for item in entries
        for url in item.get("urls", [])
        if str(url)
    }
    eligible: list[Job] = []
    excluded: list[Job] = []
    for job in jobs:
        is_excluded = (
            job_identity(job) in identities
            or job.id in job_ids
            or canonical_url(job.url) in urls
        )
        (excluded if is_excluded else eligible).append(job)
    return eligible, excluded
