"""Persist applied-role identities so fresh searches do not resurface them."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .jobs import Job
from .lifecycle import SEARCH_SUPPRESSION_STATES
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

COMPANY_ALIASES = {
    "ashton carter": "aston carter",
    "latham and watins": "latham and watkins",
    "protaganist theraputics": "protagonist therapeutics",
    "si time": "sitime",
    "skiid ai": "skild ai",
    "tik tok": "tiktok",
}


def _company_identity(value: str) -> str:
    """Normalize a company while ignoring harmless legal-entity suffix differences."""
    tokens = normalize_term(value).replace(".", " ").split()
    while tokens and tokens[-1] in CORPORATE_SUFFIXES:
        tokens.pop()
    normalized = " ".join(tokens)
    return COMPANY_ALIASES.get(normalized, normalized)


def job_identity(job: Job) -> str:
    """Return a stable company/title key that survives board-specific URL aliases."""
    return job_identity_from_fields(job.company, job.title)


def job_identity_from_fields(company: str, title: str) -> str:
    """Return the same stable identity without requiring a complete Job object."""
    return stable_id("applied-role", _company_identity(company), normalize_term(title))


def load_applied_registry(path: Path) -> dict[str, Any]:
    """Load the local applied-role registry, returning an empty schema when absent."""
    if not path.exists():
        return {"schema_version": 2, "updated_at": "", "jobs": []}
    value = read_json(path)
    jobs = value.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError(f"Applied-role registry jobs must be a list: {path}")
    return {"schema_version": 2, "updated_at": value.get("updated_at", ""), "jobs": jobs}


def partition_previously_applied(
    jobs: Iterable[Job], registry_path: Path
) -> tuple[list[Job], list[Job]]:
    """Split discovered jobs into new and previously applied collections."""
    entries = load_applied_registry(registry_path)["jobs"]
    identities = {str(item.get("identity_key") or "") for item in entries}
    identities.update(
        job_identity_from_fields(str(item.get("company") or ""), str(item.get("title") or ""))
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


def record_applied_jobs(
    path: Path,
    jobs: Iterable[Job],
    *,
    status: str = "applied",
) -> int:
    """Merge lifecycle-suppressed jobs into the durable rediscovery registry."""
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
            "status": status,
            "status_updated_at": now,
            "sources": [],
        })
        entry["sources"] = sorted({*entry.get("sources", ["import"]), "lifecycle"})
        entry["status"] = status
        entry["status_updated_at"] = now
        entry["job_ids"] = sorted({*entry.get("job_ids", []), job.id})
        entry["urls"] = sorted({
            *entry.get("urls", []),
            canonical_url(job.url),
        })
        by_identity[identity] = entry
        count += 1
    write_json(path, {
        "schema_version": 2,
        "updated_at": now,
        "jobs": sorted(by_identity.values(), key=lambda item: (item["company"], item["title"])),
    })
    return count


def record_applied_entries(path: Path, entries: Iterable[dict[str, Any]]) -> int:
    """Merge spreadsheet/manual company-title rows into the applied registry."""
    registry = load_applied_registry(path)
    by_identity = {
        str(item.get("identity_key") or ""): dict(item)
        for item in registry["jobs"]
        if item.get("identity_key")
    }
    count = 0
    now = utc_now()
    for source in entries:
        company = str(source.get("company") or "").strip()
        title = str(source.get("title") or "").strip()
        if not company or not title:
            continue
        identity = job_identity_from_fields(company, title)
        entry = by_identity.get(identity, {
            "identity_key": identity,
            "title": title,
            "company": company,
            "job_ids": [],
            "urls": [],
            "applied_at": str(source.get("applied_at") or now),
            "status": str(source.get("status") or "applied"),
            "status_updated_at": now,
            "sources": [],
        })
        entry["sources"] = sorted({*entry.get("sources", ["import"]), "import"})
        entry["status"] = str(source.get("status") or entry.get("status") or "applied")
        entry["status_updated_at"] = now
        source_url = str(source.get("url") or "").strip()
        if source_url:
            entry["urls"] = sorted({*entry.get("urls", []), canonical_url(source_url)})
        by_identity[identity] = entry
        count += 1
    write_json(path, {
        "schema_version": 2,
        "updated_at": now,
        "jobs": sorted(by_identity.values(), key=lambda item: (item["company"], item["title"])),
    })
    return count


def sync_lifecycle_registry(path: Path, job: Job, status: str) -> None:
    """Keep lifecycle-driven rediscovery suppression synchronized with SQLite."""
    if status in SEARCH_SUPPRESSION_STATES:
        record_applied_jobs(path, [job], status=status)
        return

    registry = load_applied_registry(path)
    identity = job_identity(job)
    kept: list[dict[str, Any]] = []
    changed = False
    for source in registry["jobs"]:
        item = dict(source)
        if str(item.get("identity_key") or "") != identity:
            kept.append(item)
            continue
        sources = set(item.get("sources") or ["import"])
        if "lifecycle" not in sources:
            kept.append(item)
            continue
        sources.discard("lifecycle")
        changed = True
        if sources:
            item["sources"] = sorted(sources)
            kept.append(item)
    if changed:
        write_json(path, {
            "schema_version": 2,
            "updated_at": utc_now(),
            "jobs": sorted(kept, key=lambda item: (item["company"], item["title"])),
        })

DASHBOARD_OUTCOME_FLAGS = {"interview", "denied", "not_selected"}


def update_applied_entry_outcome(
    path: Path,
    identity_key: str,
    *,
    status: str,
    outcome_flag: str,
    notes: str = "",
) -> bool:
    """Persist a reviewed dashboard outcome on one applied-registry identity."""
    if status not in SEARCH_SUPPRESSION_STATES:
        raise ValueError(f"Unsupported application outcome status: {status}")
    if outcome_flag not in DASHBOARD_OUTCOME_FLAGS:
        raise ValueError(f"Unsupported dashboard outcome flag: {outcome_flag}")
    registry = load_applied_registry(path)
    changed = False
    now = utc_now()
    updated: list[dict[str, Any]] = []
    for source in registry["jobs"]:
        item = dict(source)
        company = str(item.get("company") or "")
        title = str(item.get("title") or "")
        item_identity = str(
            item.get("identity_key") or job_identity_from_fields(company, title)
        )
        if item_identity == identity_key:
            history = list(item.get("dashboard_outcome_history") or [])
            history.append({
                "changed_at": now,
                "previous": {
                    "status_present": "status" in item,
                    "status": item.get("status"),
                    "outcome_flag_present": "outcome_flag" in item,
                    "outcome_flag": item.get("outcome_flag"),
                    "notes_present": "notes" in item,
                    "notes": item.get("notes"),
                    "status_updated_at_present": "status_updated_at" in item,
                    "status_updated_at": item.get("status_updated_at"),
                },
                "new": {
                    "status": status,
                    "outcome_flag": outcome_flag,
                    "notes": notes.strip(),
                },
            })
            item["identity_key"] = item_identity
            item["status"] = status
            item["outcome_flag"] = outcome_flag
            item["status_updated_at"] = now
            item["dashboard_outcome_history"] = history[-20:]
            item["sources"] = sorted({*(item.get("sources") or []), "dashboard"})
            if notes.strip():
                item["notes"] = notes.strip()
            changed = True
        updated.append(item)
    if not changed:
        return False
    write_json(path, {
        "schema_version": 2,
        "updated_at": now,
        "jobs": sorted(updated, key=lambda item: (item["company"], item["title"])),
    })
    return True

def previous_applied_entry_outcome(path: Path, identity_key: str) -> dict[str, Any] | None:
    """Return the latest durable dashboard snapshot without changing the registry."""
    registry = load_applied_registry(path)
    for item in registry["jobs"]:
        company = str(item.get("company") or "")
        title = str(item.get("title") or "")
        item_identity = str(
            item.get("identity_key") or job_identity_from_fields(company, title)
        )
        history = list(item.get("dashboard_outcome_history") or [])
        if item_identity == identity_key and history:
            previous = history[-1].get("previous")
            return dict(previous) if isinstance(previous, dict) else None
    return None


def undo_applied_entry_outcome(path: Path, identity_key: str) -> bool:
    """Restore the previous dashboard status/outcome snapshot for one application."""
    registry = load_applied_registry(path)
    changed = False
    now = utc_now()
    updated: list[dict[str, Any]] = []
    for source in registry["jobs"]:
        item = dict(source)
        company = str(item.get("company") or "")
        title = str(item.get("title") or "")
        item_identity = str(
            item.get("identity_key") or job_identity_from_fields(company, title)
        )
        history = list(item.get("dashboard_outcome_history") or [])
        if item_identity == identity_key and history:
            snapshot = history.pop()
            previous = snapshot.get("previous") or {}
            for field in ("status", "outcome_flag", "notes", "status_updated_at"):
                if previous.get(f"{field}_present"):
                    item[field] = previous.get(field)
                else:
                    item.pop(field, None)
            if history:
                item["dashboard_outcome_history"] = history
            else:
                item.pop("dashboard_outcome_history", None)
            item["sources"] = sorted({*(item.get("sources") or []), "dashboard"})
            changed = True
        updated.append(item)
    if not changed:
        return False
    write_json(path, {
        "schema_version": 2,
        "updated_at": now,
        "jobs": sorted(updated, key=lambda item: (item["company"], item["title"])),
    })
    return True
