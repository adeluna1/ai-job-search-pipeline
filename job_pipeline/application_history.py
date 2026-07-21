"""Persist applied-role identities so fresh searches do not resurface them."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .jobs import Job
from .util import canonical_url, normalize_term, read_json, stable_id, utc_now, write_json


CORPORATE_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "llc",
    "llp",
    "lp",
    "ltd",
    "limited",
    "plc",
}


def _company_identity(value: str) -> str:
    """Normalize a company while ignoring harmless legal-entity suffix differences."""
    tokens = normalize_term(value).replace(".", " ").split()
    while tokens and tokens[-1] in CORPORATE_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def job_identity(job: Job) -> str:
    """Return a stable company/title key that survives board-specific URL aliases."""
    return stable_id("applied-role", _company_identity(job.company), normalize_term(job.title))


def load_applied_registry(path: Path) -> dict[str, Any]:
    """Load the local applied-role registry, returning an empty schema when absent."""
    if not path.exists():
        return {"schema_version": 1, "updated_at": "", "jobs": []}
    value = read_json(path)
    jobs = value.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError(f"Applied-role registry jobs must be a list: {path}")
    return {"schema_version": 1, "updated_at": value.get("updated_at", ""), "jobs": jobs}


def partition_previously_applied(
    jobs: Iterable[Job], registry_path: Path
) -> tuple[list[Job], list[Job]]:
    """Split discovered jobs into new and previously applied collections."""
    entries = load_applied_registry(registry_path)["jobs"]
    identities = {str(item.get("identity_key") or "") for item in entries}
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
    new_jobs: list[Job] = []
    applied_jobs: list[Job] = []
    for job in jobs:
        was_applied = (
            job_identity(job) in identities
            or job.id in job_ids
            or canonical_url(job.url) in urls
        )
        (applied_jobs if was_applied else new_jobs).append(job)
    return new_jobs, applied_jobs


def record_applied_jobs(path: Path, jobs: Iterable[Job]) -> int:
    """Merge applied jobs into the local registry and return the number processed."""
    registry = load_applied_registry(path)
    by_identity = {
        str(item.get("identity_key") or ""): dict(item)
        for item in registry["jobs"]
        if item.get("identity_key")
    }
    count = 0
    now = utc_now()
    for job in jobs:
        identity = job_identity(job)
        entry = by_identity.get(identity, {
            "identity_key": identity,
            "title": job.title,
            "company": job.company,
            "job_ids": [],
            "urls": [],
            "applied_at": now,
        })
        entry["job_ids"] = sorted({*entry.get("job_ids", []), job.id})
        entry["urls"] = sorted({
            *entry.get("urls", []),
            canonical_url(job.url),
        })
        by_identity[identity] = entry
        count += 1
    write_json(path, {
        "schema_version": 1,
        "updated_at": now,
        "jobs": sorted(by_identity.values(), key=lambda item: (item["company"], item["title"])),
    })
    return count
