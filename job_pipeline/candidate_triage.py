"""Early candidate identity, deduplication, and Agent A disposition helpers."""

from __future__ import annotations

from dataclasses import replace
import re
from typing import Any, Iterable
from urllib.parse import parse_qs, urlsplit

from .jobs import Job
from .util import canonical_url, normalize_space, normalize_term, stable_id, unique_preserving_order


ATS_DOMAINS = {
    "greenhouse": ("greenhouse.io",),
    "ashby": ("ashbyhq.com",),
    "lever": ("lever.co",),
    "workday": ("myworkdayjobs.com", "workday.com"),
    "smartrecruiters": ("smartrecruiters.com",),
    "icims": ("icims.com",),
    "workable": ("workable.com",),
    "dayforce": ("dayforcehcm.com", "dayforce.com"),
    "paycom": ("paycomonline.net",),
    "hrmdirect": ("hrmdirect.com",),
    "workwolf": ("workwolf.com",),
}


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def ats_platform(url: str) -> str:
    """Return the exact trusted ATS family for a URL, if any."""
    host = (urlsplit(url).hostname or "").casefold()
    for family, domains in ATS_DOMAINS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return family
    return ""


def ats_job_id(url: str) -> str:
    """Extract a conservative ATS requisition identity from known URL shapes."""
    family = ats_platform(url)
    if not family:
        return ""
    parts = urlsplit(url)
    query = {key.casefold(): values for key, values in parse_qs(parts.query).items()}
    query_keys = {
        "hrmdirect": ("req", "id"),
        "workday": ("jobid", "job_id", "reqid", "requisitionid"),
        "dayforce": ("jobid", "job_id", "postingid"),
        "paycom": ("job", "jobid"),
        "icims": ("job", "jobid"),
    }.get(family, ())
    for key in query_keys:
        values = query.get(key, [])
        if values and values[0]:
            return normalize_term(values[0])
    segments = [segment for segment in parts.path.split("/") if segment]
    patterns = {
        "greenhouse": (r"/jobs/(\d+)",),
        "ashby": (r"/([0-9a-f]{8}-[0-9a-f-]{27,})$", r"/([^/]+)$"),
        "lever": (r"/([0-9a-f]{8}-[0-9a-f-]{27,})$", r"/([^/]+)$"),
        "smartrecruiters": (r"/[^/]+/([^/]+)$",),
        "workable": (r"/j/([^/]+)", r"/([^/]+)$"),
        "workday": (r"/job/[^/]+/([^/]+)$", r"/([^/]+)$"),
        "dayforce": (r"/jobs/(?:[^/]+/)?([^/]+)$",),
        "paycom": (r"/jobs/([^/]+)",),
        "hrmdirect": (r"/(?:view|job-opening)\.php$",),
        "workwolf": (r"/jobs?/([^/]+)",),
        "icims": (r"/jobs/(\d+)",),
    }.get(family, ())
    path = parts.path.rstrip("/")
    for pattern in patterns:
        match = re.search(pattern, path, flags=re.IGNORECASE)
        if match and match.groups():
            value = normalize_term(match.group(1))
            if value and value not in {"jobs", "job", "apply", "view php"}:
                return value
    if family in {"ashby", "lever", "workable"} and segments:
        return normalize_term(segments[-1])
    return ""


def _location_bucket(value: str) -> str:
    normalized = normalize_term(value)
    if "remote" in normalized:
        if any(term in normalized for term in ("united states", "nationwide", " usa ")):
            return "remote-us"
        if "california" in normalized or normalized.endswith(" ca"):
            return "remote-ca"
        return "remote"
    normalized = re.sub(r"\b(california|ca|united states|usa|us)\b", " ", normalized)
    return normalize_space(normalized)


def candidate_identity_keys(job: Job) -> set[str]:
    """Build URL, ATS-ID, and exact role/location keys for early deduplication."""
    keys = {f"url:{canonical_url(job.url)}"}
    family = ats_platform(job.url)
    identifier = ats_job_id(job.url)
    if family and identifier:
        keys.add(f"ats:{family}:{identifier}")
    company = normalize_term(job.company)
    title = normalize_term(job.title)
    location = _location_bucket(job.location)
    if company not in {"", "unknown", "unknown company"} and title not in {
        "", "untitled role", "jobs", "careers",
    }:
        keys.add(f"role:{company}:{title}:{location or 'unknown-location'}")
    return keys


def _quality(job: Job) -> tuple[int, int, int, int]:
    family = ats_platform(job.url)
    source_count = len(job.raw.get("discovery_evidence", {}).get("source_urls", [])) if isinstance(job.raw, dict) else 0
    return (
        1 if family else 0,
        1 if normalize_term(job.company) not in {"", "unknown", "unknown company"} else 0,
        len(job.description),
        source_count,
    )


def _merge_evidence(preferred: Job, other: Job) -> Job:
    raw = dict(preferred.raw) if isinstance(preferred.raw, dict) else {}
    current = raw.get("discovery_evidence", {})
    source_urls = unique_preserving_order([
        *list(current.get("source_urls", [])),
        str((other.raw or {}).get("url") or ""),
        other.url,
        str((preferred.raw or {}).get("url") or ""),
        preferred.url,
        *list((other.raw or {}).get("discovery_evidence", {}).get("source_urls", [])),
    ])
    raw["discovery_evidence"] = {
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "deduplicated": bool(current.get("deduplicated")) or preferred is not other,
    }
    return replace(preferred, raw=raw)


def rejected_disposition(job: Job, category: str, reason: str, **extra: Any) -> dict[str, Any]:
    """Create the stable rejected-candidate contract used in Agent A diagnostics."""
    value: dict[str, Any] = {
        "candidate_id": job.id,
        "disposition": "rejected",
        "failure_category": category,
        "reason": normalize_space(reason),
        "title": job.title,
        "company": job.company,
        "source_url": job.url,
        "location": job.location,
        "posting_date_evidence": job.posted_date,
        "employer_url_found": False,
        "eligible_for_agent_b": False,
    }
    value.update(extra)
    return value


def deduplicate_candidates(jobs: Iterable[Job]) -> tuple[list[Job], list[dict[str, Any]]]:
    """Deduplicate before live verification while retaining all source URLs as evidence."""
    unique: list[Job] = []
    key_to_index: dict[str, int] = {}
    rejected: list[dict[str, Any]] = []
    for job in jobs:
        keys = candidate_identity_keys(job)
        matching_indexes = {key_to_index[key] for key in keys if key in key_to_index}
        if not matching_indexes:
            index = len(unique)
            unique.append(_merge_evidence(job, job))
            for key in keys:
                key_to_index[key] = index
            continue
        index = min(matching_indexes)
        existing = unique[index]
        preferred, duplicate = (job, existing) if _quality(job) > _quality(existing) else (existing, job)
        merged = _merge_evidence(preferred, duplicate)
        unique[index] = merged
        merged_keys = candidate_identity_keys(merged) | candidate_identity_keys(duplicate)
        for key in merged_keys:
            key_to_index[key] = index
        rejected.append(rejected_disposition(
            duplicate,
            "duplicate",
            f"Duplicate of {merged.title} at {merged.company}; source retained as evidence.",
            duplicate_of_candidate_id=merged.id,
            employer_url_found=bool(ats_platform(merged.url)),
            canonical_employer_url=merged.url,
        ))
    return unique, rejected


def classify_resolution_failure(message: str) -> tuple[str, str]:
    """Classify a failed resolution as manual-reviewable or definitively rejected."""
    normalized = normalize_term(message)
    rejected_markers = {
        "closed_or_stale": ("closed", "expired", "no longer", "filled", "job not found", "http 404", "http 410"),
        "unsafe_or_suspicious": ("lookalike", "outside a plausible", "invalid http", "unsafe"),
        "role_or_employer_mismatch": ("title company mismatch", "did not match the requested role", "live page title company"),
        "generic_or_unrelated_page": ("generic jobs page", "generic page title", "does not contain role specific"),
    }
    for category, markers in rejected_markers.items():
        if any(normalize_term(marker) in normalized for marker in markers):
            return "rejected", category
    manual_markers = {
        "access_blocked": ("access challenge", "captcha", "security verification", "verify you are human", "http 403"),
        "login_required": ("sign in", "login required", "authentication"),
        "javascript_only": ("javascript", "document body is loading", "visible text"),
        "temporary_access_failure": ("timeout", "not reachable", "http 429", "http 500", "http 502", "http 503"),
        "insufficient_page_evidence": ("too short", "could not read", "unavailable", "uncertain"),
    }
    for category, markers in manual_markers.items():
        if any(normalize_term(marker) in normalized for marker in markers):
            return "manual_verification_required", category
    return "manual_verification_required", "missing_employer_link"


def manual_disposition(
    job: Job,
    reason: str,
    *,
    failure_category: str | None = None,
    preliminary_score: float | None = None,
    employer_url: str = "",
    source_urls: Iterable[str] = (),
) -> dict[str, Any]:
    """Create a visible manual-review record that can never enter Agent B or C."""
    _, inferred = classify_resolution_failure(reason)
    urls = unique_preserving_order([job.url, *source_urls])
    return {
        "candidate_id": job.id or stable_id(job.url, job.title, job.company),
        "disposition": "manual_verification_required",
        "title": job.title,
        "company": job.company,
        "source_url": job.url,
        "source_urls": urls,
        "location": job.location,
        "posting_date_evidence": job.posted_date,
        "preliminary_resume_fit_score": preliminary_score,
        "failure_category": failure_category or inferred,
        "reason": normalize_space(reason),
        "recommended_manual_check": (
            "Open the source read-only, confirm the exact employer, role, location, "
            "posting date, and active direct application URL."
        ),
        "employer_url_found": bool(employer_url),
        "employer_url": employer_url,
        "eligible_for_agent_b": False,
        "eligible_for_agent_c": False,
    }


def job_from_resolution_error(
    record: dict[str, Any],
    *,
    default_location: str = "Unspecified",
    default_title: str = "Unresolved recruiting lead",
) -> Job:
    """Recover the non-verified facts available when a resolution attempt fails."""
    url = canonical_url(str(record.get("url") or record.get("source_url") or ""))
    title = normalize_space(str(record.get("title") or default_title))
    company = normalize_space(str(record.get("company") or "Unknown company"))
    for separator in (" at ", " | ", " - "):
        if company == "Unknown company" and separator in title:
            parts = [
                normalize_space(value) for value in title.split(separator)
                if normalize_space(value)
            ]
            if len(parts) >= 2:
                title, company = parts[0], parts[-1]
                break
    location = normalize_space(str(record.get("location") or default_location))
    return Job(
        id=str(record.get("job_id") or stable_id(url, title, company)),
        url=url,
        title=title,
        company=company,
        location=location,
        work_mode=normalize_space(str(record.get("work_mode") or (
            "remote" if "remote" in normalize_term(location) else "unknown"
        ))),
        employment_type="",
        posted_date=normalize_space(str(
            record.get("posted_date") or record.get("posting_date_evidence") or ""
        )),
        salary="",
        description="",
        source=normalize_space(str(
            record.get("source") or record.get("board") or "unresolved_discovery"
        )),
        raw={
            "discovery_evidence": {
                "source_urls": list(record.get("source_urls") or [url]),
                "unverified_hint": True,
            }
        },
    )

def verified_disposition(job: Job, score: float | None = None) -> dict[str, Any]:
    """Create a verified Agent A disposition after every hard gate passes."""
    return {
        "candidate_id": job.id,
        "disposition": "verified",
        "title": job.title,
        "company": job.company,
        "source_url": job.url,
        "source_urls": list((job.raw or {}).get("discovery_evidence", {}).get("source_urls", [job.url])),
        "location": job.location,
        "posting_date_evidence": job.posted_date,
        "preliminary_resume_fit_score": score,
        "failure_category": "",
        "reason": "Active direct employer or trusted ATS posting passed role, geography, recency, duplicate, and applied-history gates.",
        "recommended_manual_check": "",
        "employer_url_found": True,
        "employer_url": job.url,
        "eligible_for_agent_b": True,
        "eligible_for_agent_c": False,
    }
