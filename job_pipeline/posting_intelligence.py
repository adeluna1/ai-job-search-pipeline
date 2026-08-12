"""Deterministic posting-trust, repost, and cross-listing intelligence.

The design selectively adapts Career Ops' separate legitimacy layer and
zero-dependency SimHash approach. These signals never change resume-match
scores and never bypass the pipeline's live employer-page verification gate.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from .application_history import _company_identity
from .jobs import Job
from .util import canonical_url, normalize_term, utc_now


FINGERPRINT_MIN_TEXT = 200
CROSS_LISTING_THRESHOLD = 0.92
DEFAULT_WINDOW_DAYS = 90

SUSPICIOUS_DOMAINS = (
    "bit.ly",
    "tinyurl.com",
    "t.co",
    "forms.gle",
    "goo.gl",
    "shorturl.at",
    "rebrand.ly",
    "cutt.ly",
)

ATS_DOMAINS = (
    "greenhouse.io",
    "ashbyhq.com",
    "lever.co",
    "workday.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "jobvite.com",
    "recruitee.com",
    "workable.com",
    "icims.com",
    "taleo.net",
    "applytojob.com",
    "breezy.hr",
    "jazz.co",
    "bamboohr.com",
    "teamtailor.com",
)

TRUST_PENALTIES = {
    "invalid_url": 50,
    "missing_apply_url": 40,
    "suspicious_domain": 25,
    "company_domain_mismatch": 15,
    "unverified_employer_page": 45,
}

TITLE_BASELINE_TOKENS = {
    "and",
    "the",
    "remote",
    "hybrid",
    "onsite",
    "senior",
    "junior",
    "contract",
    "temporary",
}


@dataclass(frozen=True)
class TrustAssessment:
    """Explainable URL and provenance trust result kept separate from fit."""

    score: int
    level: str
    flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "level": self.level, "flags": self.flags}


def _host_matches(hostname: str, domains: Iterable[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)


def _company_matches_hostname(company: str, hostname: str) -> bool:
    """Conservatively determine whether an employer name appears in its host."""
    normalized = re.sub(r"[^a-z0-9 ]", "", company.casefold()).strip()
    if not normalized:
        return True
    slug = re.sub(r"\s+", "", normalized)
    if slug and slug in hostname:
        return True
    return any(word in hostname for word in normalized.split() if len(word) >= 3)


def assess_posting_trust(job: Job) -> TrustAssessment:
    """Score source trust without changing the candidate-fit score."""
    flags: list[str] = []
    score = 100
    url = str(job.url or "").strip()
    if not url:
        flags.append("missing_apply_url")
    else:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            flags.append("invalid_url")
        else:
            hostname = parts.netloc.casefold().split(":", 1)[0]
            if _host_matches(hostname, SUSPICIOUS_DOMAINS):
                flags.append("suspicious_domain")
            if (
                job.company
                and not _host_matches(hostname, ATS_DOMAINS)
                and not _company_matches_hostname(job.company, hostname)
            ):
                flags.append("company_domain_mismatch")

    verification = job.raw.get("verification", {}) if isinstance(job.raw, dict) else {}
    if not (
        verification.get("active") is True
        and verification.get("verified_by") == "webclaw"
    ):
        flags.append("unverified_employer_page")

    for flag in flags:
        score -= TRUST_PENALTIES[flag]
    score = max(0, min(100, score))
    level = "high" if score >= 90 else "medium" if score >= 60 else "low"
    return TrustAssessment(score=score, level=level, flags=flags)


def normalize_jd_text(text: str) -> str:
    """Normalize a job description for stable three-token shingling."""
    normalized = str(text or "").casefold()
    normalized = re.sub(r"<[^>]*>", " ", normalized)
    normalized = re.sub(r"&[a-z#0-9]+;", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def content_fingerprint(text: str) -> str:
    """Return a 64-bit SimHash for a sufficiently descriptive JD body."""
    normalized = normalize_jd_text(text)
    if len(normalized) < FINGERPRINT_MIN_TEXT:
        return ""
    tokens = normalized.split()
    if len(tokens) < 3:
        return ""
    weights = [0] * 64
    for index in range(len(tokens) - 2):
        shingle = " ".join(tokens[index : index + 3])
        digest = hashlib.sha1(shingle.encode("utf-8")).digest()[:8]
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += 1 if value & (1 << (63 - bit)) else -1
    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight > 0:
            fingerprint |= 1 << (63 - bit)
    return f"{fingerprint:016x}"


def fingerprint_similarity(left: str, right: str) -> float:
    """Return normalized 64-bit Hamming similarity for valid fingerprints."""
    if not re.fullmatch(r"[0-9a-f]{16}", left or ""):
        return 0.0
    if not re.fullmatch(r"[0-9a-f]{16}", right or ""):
        return 0.0
    distance = (int(left, 16) ^ int(right, 16)).bit_count()
    return 1.0 - distance / 64


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_term(value).split()
        if len(token) > 1 and token not in TITLE_BASELINE_TOKENS
    }


def similar_role_title(left: str, right: str) -> bool:
    """Fuzzy-match a likely relisting while keeping adjacent roles distinct."""
    left_normalized = normalize_term(left)
    right_normalized = normalize_term(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(overlap) >= 2 and bool(union) and len(overlap) / len(union) >= 0.6


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _was_live_verified(job: Job) -> bool:
    verification = job.raw.get("verification", {}) if isinstance(job.raw, dict) else {}
    if not isinstance(verification, dict):
        return False
    return verification.get("active") is True and verification.get("verified_by") == "webclaw"


def build_posting_intelligence(
    job: Job,
    history: Iterable[Job] = (),
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cross_listing_threshold: float = CROSS_LISTING_THRESHOLD,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build independent trust and historical-pattern evidence for one posting."""
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=max(1, int(window_days)))
    fingerprint = content_fingerprint(job.description)
    company_key = _company_identity(job.company)
    repost_matches: list[dict[str, Any]] = []
    cross_listings: list[dict[str, Any]] = []

    for previous in history:
        if canonical_url(previous.url) == canonical_url(job.url):
            continue
        seen_at = _parse_timestamp(previous.discovered_at)
        if seen_at is None or seen_at < cutoff or not _was_live_verified(previous):
            continue
        previous_fingerprint = ""
        if isinstance(previous.raw, dict):
            previous_fingerprint = str(
                previous.raw.get("posting_intelligence", {}).get("fingerprint") or ""
            )
        previous_fingerprint = previous_fingerprint or content_fingerprint(previous.description)
        similarity = fingerprint_similarity(fingerprint, previous_fingerprint)
        if _company_identity(previous.company) == company_key:
            if similar_role_title(previous.title, job.title):
                repost_matches.append({
                    "job_id": previous.id,
                    "url": previous.url,
                    "title": previous.title,
                    "first_seen": previous.discovered_at,
                })
        elif similarity >= float(cross_listing_threshold):
            cross_listings.append({
                "job_id": previous.id,
                "company": previous.company,
                "title": previous.title,
                "url": previous.url,
                "similarity": round(similarity, 4),
            })

    unique_reposts = {item["url"]: item for item in repost_matches}
    trust = assess_posting_trust(job)
    return {
        "schema_version": 1,
        "derived_from": "career-ops-1.25.0",
        "generated_at": utc_now(),
        "trust": trust.to_dict(),
        "fingerprint": fingerprint,
        "repost": {
            "detected": bool(unique_reposts),
            "appearance_count": 1 + len(unique_reposts),
            "window_days": int(window_days),
            "matches": list(unique_reposts.values()),
        },
        "cross_listings": cross_listings,
        "fit_score_affected": False,
    }


def enrich_jobs_with_posting_intelligence(
    jobs: Iterable[Job],
    history: Iterable[Job] = (),
    *,
    enabled: bool = True,
    window_days: int = DEFAULT_WINDOW_DAYS,
    cross_listing_threshold: float = CROSS_LISTING_THRESHOLD,
) -> list[Job]:
    """Attach intelligence to raw provenance without changing canonical job fields."""
    pending = list(jobs)
    if not enabled:
        return pending
    comparison_history = list(history)
    enriched: list[Job] = []
    for job in pending:
        intelligence = build_posting_intelligence(
            job,
            comparison_history,
            window_days=window_days,
            cross_listing_threshold=cross_listing_threshold,
        )
        raw = dict(job.raw) if isinstance(job.raw, dict) else {}
        raw["posting_intelligence"] = intelligence
        current = replace(job, raw=raw)
        enriched.append(current)
        comparison_history.append(current)
    return enriched
