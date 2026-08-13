"""Conservative title matching for the user's requested role family."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .jobs import Job
from .util import normalize_term

RECRUITING_SEARCH_MARKERS = (
    "recruiting",
    "recruitment",
    "recruiter",
    "talent acquisition",
    "talent coordinator",
)
ADJACENT_RECRUITING_TITLES = (
    "recruiting assistant",
    "recruiting scheduler",
    "recruiting coordinator",
    "recruitment coordinator",
    "talent acquisition coordinator",
    "talent coordinator",
    "recruiting operations coordinator",
    "talent operations coordinator",
    "candidate experience coordinator",
    "recruiting program coordinator",
    "sourcing coordinator",
    "people operations coordinator",
    "junior recruiter",
    "recruiter i",
    "recruiter 1",
    "associate recruiter",
    "recruiting associate",
    "talent acquisition associate",
    "talent acquisition specialist",
    "recruiting specialist",
    "recruiting operations specialist",
    "talent operations specialist",
    "university recruiter",
    "university recruiting coordinator",
    "campus recruiter",
)
MANUAL_REVIEW_ONLY_TITLES = (
    "recruitment and hr coordinator",
    "talent strategy and operations associate",
    "talent outreach coordinator",
    "recruiting relations specialist",
    "people engagement coordinator",
    "hr specialist recruitment",
)

GENERIC_DISCOVERY_TITLE_MARKERS = (
    "job description template",
    "career overview",
    "results for recruiting",
    "results for talent acquisition",
    "what does a recruiting",
    "what does a recruiter",
    "what is a recruiting",
    "what s it like to work as",
)

EXCLUDED_RECRUITING_TITLES = (
    "technical recruiter",
)
SENIOR_RECRUITING_TERMS = (
    "senior", "sr", "lead", "manager", "director", "head", "principal",
    "vice president", "vp", "chief",
)


@dataclass(frozen=True)
class RoleScopeDecision:
    """Explain whether a discovered title belongs to the requested role family."""

    eligible: bool
    reason: str
    category: str = "role_mismatch"


def generic_discovery_title_reason(title: str) -> str:
    """Reject search indexes, templates, and career-information pages by title."""
    normalized = normalize_term(title)
    if any(marker in normalized for marker in GENERIC_DISCOVERY_TITLE_MARKERS):
        return f"Title '{title}' describes a search/index or career-information page."
    if re.search(r"\bjobs?\s+(?:in|and work in)\b", normalized):
        return f"Title '{title}' is a location search page, not a job-detail title."
    if re.search(r"\bjobs?\s+employment\b", normalized):
        return f"Title '{title}' is a job-search index, not a job-detail title."
    if re.match(r"^\d+\s+results?\s+for\b", normalized):
        return f"Title '{title}' is a search-results page."
    if normalized.endswith(" jobs"):
        return f"Title '{title}' is a jobs category, not a job-detail title."
    return ""

def is_manual_review_role(job: Job) -> bool:
    """Return whether an adjacent title is visible only in the manual queue."""
    title = normalize_term(job.title)
    title_tokens = set(title.split())
    if any(
        marker in title_tokens or " " in marker and marker in title
        for marker in SENIOR_RECRUITING_TERMS
    ):
        return False
    return any(marker in title for marker in MANUAL_REVIEW_ONLY_TITLES)

def evaluate_role_scope(job: Job, query: str) -> RoleScopeDecision:
    """Admit configured junior recruiting equivalents and reject senior titles."""
    requested = normalize_term(query)
    title = normalize_term(job.title)
    generic_reason = generic_discovery_title_reason(job.title)
    if generic_reason:
        return RoleScopeDecision(False, generic_reason, "generic_or_unrelated_page")
    recruiting_search = any(marker in requested for marker in RECRUITING_SEARCH_MARKERS)
    if recruiting_search:
        title_tokens = set(title.split())
        senior_match = next(
            (
                marker for marker in SENIOR_RECRUITING_TERMS
                if marker in title_tokens or " " in marker and marker in title
            ),
            "",
        )
        if senior_match:
            return RoleScopeDecision(
                False,
                f"Title '{job.title}' is senior-level ({senior_match}).",
                "senior_or_excluded_role",
            )
        excluded_match = next(
            (marker for marker in EXCLUDED_RECRUITING_TITLES if marker in title),
            "",
        )
        if excluded_match:
            return RoleScopeDecision(
                False,
                f"Title '{job.title}' is excluded from the entry-level search ({excluded_match}).",
                "senior_or_excluded_role",
            )
        if any(marker in title for marker in ADJACENT_RECRUITING_TITLES):
            return RoleScopeDecision(True, "Title matches the expanded junior recruiting family.")
        return RoleScopeDecision(
            False,
            f"Title '{job.title}' is outside the expanded junior recruiting family.",
        )

    query_terms = {term for term in requested.split() if len(term) >= 4}
    title_terms = set(title.split())
    if query_terms and len(query_terms & title_terms) >= max(1, len(query_terms) // 2):
        return RoleScopeDecision(True, "Title overlaps the requested role terms.")
    return RoleScopeDecision(False, f"Title '{job.title}' does not match query '{query}'.")


def partition_by_role_scope(
    jobs: Iterable[Job], query: str
) -> tuple[list[Job], list[tuple[Job, RoleScopeDecision]]]:
    """Split discovered jobs into requested-role and unrelated collections."""
    eligible: list[Job] = []
    rejected: list[tuple[Job, RoleScopeDecision]] = []
    for job in jobs:
        decision = evaluate_role_scope(job, query)
        if decision.eligible:
            eligible.append(job)
        else:
            rejected.append((job, decision))
    return eligible, rejected
