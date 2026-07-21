"""Bounded specialist agents for discovery, verification, and application preparation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .integrations.browser_use_runner import build_form_answer_catalog
from .jobs import Job, normalize_webclaw_job, validate_job
from .matching import MatchResult
from .util import normalize_space, read_json, utc_now, write_json
from .webclaw import WebClawClient, WebClawError


DIRECT_ATS_DOMAINS = (
    "greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
)


def _parse_posted_datetime(value: str) -> datetime | None:
    """Parse common ISO job timestamps without guessing non-ISO relative dates."""
    cleaned = normalize_space(value)
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(cleaned[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_quality(url: str) -> str:
    """Classify a source conservatively for downstream verification decisions."""
    host = urlsplit(url).netloc.casefold()
    if any(domain in host for domain in DIRECT_ATS_DOMAINS):
        return "direct_ats"
    if any(domain in host for domain in ("indeed.com", "linkedin.com", "ziprecruiter.com", "simplyhired.com")):
        return "major_job_board"
    return "employer_or_other_board"


@dataclass
class RecruiterFinding:
    """Agent A's structured freshness and source-quality assessment."""

    active: bool
    fresh: bool | None
    age_days: int | None
    source_quality: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize Agent A's finding for JSON handoff to Agent B."""
        return {
            "active": self.active,
            "fresh": self.fresh,
            "age_days": self.age_days,
            "source_quality": self.source_quality,
            "reasons": self.reasons,
        }


class RecruiterAgent:
    """Agent A: identify viable, fresh job records before deeper analysis."""

    name = "agent_a_recruiter"

    def inspect(self, job: Job, fresh_days: int = 7, now: datetime | None = None) -> RecruiterFinding:
        """Validate one normalized job and assess whether its stated date is fresh."""
        valid, validation_reason = validate_job(job)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        posted = _parse_posted_datetime(job.posted_date)
        reasons: list[str] = []
        fresh: bool | None = None
        age_days: int | None = None
        if posted is None:
            reasons.append("Posting date is unavailable; Agent B must verify freshness.")
        else:
            age_days = (current.date() - posted.date()).days
            fresh = 0 <= age_days <= max(0, fresh_days)
            reasons.append(
                f"Posting date is {age_days} calendar day(s) old; freshness limit is {fresh_days}."
            )
        if not valid:
            reasons.append(validation_reason)
        return RecruiterFinding(
            active=valid,
            fresh=fresh,
            age_days=age_days,
            source_quality=_source_quality(job.url),
            reasons=reasons,
        )


@dataclass
class MatchAnalysis:
    """Agent B's independent verification and evidence-based recommendation."""

    score: float
    fit_label: str
    recommendation: str
    live_verified: bool
    verified_at: str
    matched_skills: list[str]
    matched_evidence: list[str]
    gaps: list[str]
    insights: list[str]
    blockers: list[str]
    discrepancies: list[str]
    resume_matcher: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize Agent B's complete decision and evidence trail."""
        return {
            "score": self.score,
            "fit_label": self.fit_label,
            "recommendation": self.recommendation,
            "live_verified": self.live_verified,
            "verified_at": self.verified_at,
            "matched_skills": self.matched_skills,
            "matched_evidence": self.matched_evidence,
            "gaps": self.gaps,
            "insights": self.insights,
            "blockers": self.blockers,
            "discrepancies": self.discrepancies,
            "resume_matcher": self.resume_matcher,
        }


class MatchAnalystAgent:
    """Agent B: verify the role independently and explain whether it merits applying."""

    name = "agent_b_match_analyst"

    def analyze(
        self,
        job: Job,
        match: MatchResult,
        finding: RecruiterFinding,
        threshold: float,
        fresh_days: int = 7,
        client: WebClawClient | None = None,
        resume_matcher: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MatchAnalysis:
        """Review stored facts, optionally re-scrape the page, and issue a decision."""
        current_job = job
        live_verified = False
        discrepancies: list[str] = []
        blockers: list[str] = []

        if client is not None:
            try:
                refreshed = normalize_webclaw_job(job.url, client.scrape(job.url))
                valid, reason = validate_job(refreshed)
                if not valid:
                    blockers.append(f"Live page validation failed: {reason}.")
                else:
                    live_verified = True
                    current_job = refreshed
                    if normalize_space(refreshed.title).casefold() != normalize_space(job.title).casefold():
                        discrepancies.append(
                            f"Live title changed from '{job.title}' to '{refreshed.title}'."
                        )
                    if normalize_space(refreshed.company).casefold() != normalize_space(job.company).casefold():
                        discrepancies.append(
                            f"Live company changed from '{job.company}' to '{refreshed.company}'."
                        )
            except WebClawError as exc:
                blockers.append(f"Live verification was unavailable: {exc}")

        verified_finding = RecruiterAgent().inspect(current_job, fresh_days=fresh_days, now=now)
        if not verified_finding.active:
            blockers.append("The job page does not contain a valid active role.")
        if verified_finding.fresh is False:
            blockers.append("The stated posting date is outside the configured freshness window.")

        if blockers or match.final_score < threshold:
            recommendation = "skip"
        elif verified_finding.fresh is None:
            recommendation = "review"
        else:
            recommendation = "apply"

        insights: list[str] = []
        if match.matched_evidence:
            insights.append("Lead with: " + match.matched_evidence[0])
        if match.matched_skills:
            insights.append("Strongest aligned skills: " + ", ".join(match.matched_skills[:5]) + ".")
        if match.gaps:
            insights.append("Resolve before applying: " + match.gaps[0])
        if not live_verified and finding.source_quality != "direct_ats":
            insights.append("Open the employer-controlled page before submission.")

        analysis_gaps = list(match.gaps)
        if resume_matcher:
            try:
                ats_score = float(resume_matcher.get("overall_score", 0))
            except (TypeError, ValueError):
                ats_score = 0.0
            insights.append(
                f"Resume-Matcher tailoring-preview ATS score: {ats_score:.1f}/100."
            )
            missing = [
                normalize_space(str(value))
                for value in resume_matcher.get("missing_keywords", [])
                if normalize_space(str(value))
            ]
            if missing:
                insights.append("ATS keyword gaps: " + ", ".join(missing[:5]) + ".")
                analysis_gaps.extend(
                    f"Resume-Matcher missing keyword: {value}" for value in missing
                )
            # The upstream score is calculated during a tailoring preview, so it
            # is evidence rather than a replacement for the original-resume score.
            if recommendation == "apply" and ats_score < 60:
                recommendation = "review"
                insights.append("Manual review required because the external ATS preview is below 60.")

        return MatchAnalysis(
            score=match.final_score,
            fit_label=match.fit_label,
            recommendation=recommendation,
            live_verified=live_verified,
            verified_at=utc_now(),
            matched_skills=match.matched_skills,
            matched_evidence=match.matched_evidence,
            gaps=list(dict.fromkeys(analysis_gaps)),
            insights=insights,
            blockers=blockers,
            discrepancies=discrepancies,
            resume_matcher=resume_matcher,
        )


@dataclass
class ApplicationDraft:
    """Agent C's non-sensitive workflow summary for one private application packet."""

    status: str
    packet_path: str
    answered_fields: list[str]
    unresolved_questions: list[str]
    tailoring_notes: list[str]
    prepared_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize Agent C's preparation status without packet contents."""
        return {
            "status": self.status,
            "packet_path": self.packet_path,
            "answered_fields": self.answered_fields,
            "unresolved_questions": self.unresolved_questions,
            "tailoring_notes": self.tailoring_notes,
            "prepared_at": self.prepared_at,
        }


def load_application_profile(path: Path) -> dict[str, Any]:
    """Load a private application profile and require explicit contact-data consent."""
    profile = read_json(path)
    if not isinstance(profile.get("contact"), dict):
        raise ValueError("Application profile must contain a contact object.")
    if not profile.get("consents", {}).get("use_contact_for_applications", False):
        raise ValueError(
            "Application profile consent is disabled. Set consents.use_contact_for_applications to true after review."
        )
    return profile


class ApplicationAgent:
    """Agent C: prepare truthful application packets while withholding submission authority."""

    name = "agent_c_application_assistant"
    required_contact_fields = ("first_name", "last_name", "email", "phone", "city", "state", "country")
    required_eligibility_fields = ("authorized_to_work_us", "requires_sponsorship")

    def prepare(
        self,
        job: Job,
        analysis: MatchAnalysis,
        application_profile: dict[str, Any],
        resume_path: Path | None,
        packet_dir: Path,
    ) -> ApplicationDraft:
        """Write one private, review-required packet without inventing missing answers."""
        contact = dict(application_profile.get("contact", {}))
        links = dict(application_profile.get("links", {}))
        eligibility = dict(application_profile.get("eligibility", {}))
        preferences = dict(application_profile.get("preferences", {}))
        standard_answers = dict(application_profile.get("standard_answers", {}))
        unresolved: list[str] = []

        for field_name in self.required_contact_fields:
            if not normalize_space(str(contact.get(field_name, ""))):
                unresolved.append(f"contact.{field_name}")
        for field_name in self.required_eligibility_fields:
            if eligibility.get(field_name) is None:
                unresolved.append(f"eligibility.{field_name}")
        if resume_path is None or not resume_path.exists():
            unresolved.append("resume_file")

        tailoring_notes = [
            *analysis.insights[:3],
            "Use only documented resume evidence; do not add unstated credentials or results.",
        ]
        packet = {
            "schema_version": 1,
            "job": {
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "url": job.url,
                "location": job.location,
            },
            "candidate": {
                "contact": contact,
                "links": links,
                "eligibility": eligibility,
                "preferences": preferences,
                "standard_answers": standard_answers,
                "resume_path": str(resume_path.resolve()) if resume_path and resume_path.exists() else "",
            },
            "form_answer_catalog": build_form_answer_catalog({
                "contact": contact,
                "links": links,
                "eligibility": eligibility,
                "preferences": preferences,
                "standard_answers": standard_answers,
            }),
            "match": {
                "score": analysis.score,
                "matched_skills": analysis.matched_skills,
                "matched_evidence": analysis.matched_evidence,
                "gaps": analysis.gaps,
            },
            "tailoring_notes": tailoring_notes,
            "unresolved_questions": unresolved,
            "review_required": True,
            "approval": "pending",
            "external_submission_performed": False,
            "prepared_at": utc_now(),
        }
        packet_path = packet_dir / f"{job.id}.json"
        write_json(packet_path, packet)
        answered_fields = [
            *[f"contact.{key}" for key, value in contact.items() if value not in (None, "")],
            *[f"links.{key}" for key, value in links.items() if value not in (None, "")],
            *[f"eligibility.{key}" for key, value in eligibility.items() if value is not None],
            *[f"preferences.{key}" for key, value in preferences.items() if value not in (None, "")],
            *[f"standard_answers.{key}" for key, value in standard_answers.items() if value not in (None, "")],
        ]
        return ApplicationDraft(
            status="needs_information" if unresolved else "awaiting_review",
            packet_path=str(packet_path),
            answered_fields=answered_fields,
            unresolved_questions=unresolved,
            tailoring_notes=tailoring_notes,
            prepared_at=packet["prepared_at"],
        )
