"""Evidence-bound resume-tailoring guidance that never rewrites source facts."""

from __future__ import annotations

from typing import Any

from .jobs import Job
from .matching import MatchResult
from .util import normalize_term, normalize_space, unique_preserving_order


def _is_documented(keyword: str, match: MatchResult) -> bool:
    needle = normalize_term(keyword)
    if not needle:
        return False
    evidence = normalize_term(
        " ".join([*match.matched_skills, *match.matched_evidence])
    )
    return needle in evidence or any(
        needle in normalize_term(skill) or normalize_term(skill) in needle
        for skill in match.matched_skills
    )


def build_tailoring_plan(
    job: Job,
    match: MatchResult,
    resume_matcher: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured, truthful tailoring guidance for human review."""
    external = resume_matcher or {}
    suggested = [
        normalize_space(str(value))
        for value in external.get("injectable_keywords", [])
        if normalize_space(str(value))
    ]
    missing = [
        normalize_space(str(value))
        for value in external.get("missing_keywords", [])
        if normalize_space(str(value))
    ]
    supported_suggestions = [value for value in suggested if _is_documented(value, match)]
    unsupported = [
        value
        for value in unique_preserving_order([*suggested, *missing])
        if not _is_documented(value, match)
    ]
    priority_keywords = unique_preserving_order(
        [*match.matched_skills[:10], *supported_suggestions]
    )
    recommendations = [
        normalize_space(str(value))
        for value in external.get("recommendations", [])
        if normalize_space(str(value))
    ]
    return {
        "schema_version": 1,
        "target_title": job.title,
        "summary_focus": [
            f"Lead with documented experience most relevant to {job.title}.",
            *match.matched_evidence[:2],
        ],
        "priority_keywords_supported_by_resume": priority_keywords,
        "evidence_bullets": match.matched_evidence[:5],
        "gaps_to_address_truthfully": match.gaps[:8],
        "external_recommendations_for_review": recommendations[:8],
        "do_not_add_without_resume_evidence": unsupported[:12],
        "source_resume_must_remain_unchanged": True,
        "auto_edit_performed": False,
        "required_human_review": True,
    }
