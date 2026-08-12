"""Bounded specialist agents for discovery, verification, and application preparation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .discovery_fallback import direct_application_domain
from .integrations.browser_use_runner import build_form_answer_catalog
from .jobs import Job, normalize_webclaw_job, validate_job
from .matching import MatchResult
from .tailoring import build_tailoring_plan
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


def _posted_precision(value: str) -> str:
    """Identify whether a posting date carries enough precision for an hourly gate."""
    cleaned = normalize_space(value)
    if not cleaned:
        return "unknown"
    return "timestamp" if "T" in cleaned or re.search(r"\d{1,2}:\d{2}", cleaned) else "date"


def _source_quality(url: str) -> str:
    """Classify a source conservatively for downstream verification decisions."""
    host = urlsplit(url).netloc.casefold().split(":", 1)[0]
    matches = lambda domain: host == domain or host.endswith(f".{domain}")
    if any(matches(domain) for domain in DIRECT_ATS_DOMAINS):
        return "direct_ats"
    if any(
        matches(domain)
        for domain in ("indeed.com", "linkedin.com", "ziprecruiter.com", "simplyhired.com")
    ):
        return "major_job_board"
    return "employer_or_other_board"


@dataclass
class RecruiterFinding:
    """Agent A's structured freshness and source-quality assessment."""

    active: bool
    fresh: bool | None
    age_days: int | None
    age_hours: float | None
    freshness_window_hours: int
    freshness_precision: str
    freshness_source: str
    source_quality: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize Agent A's finding for JSON handoff to Agent B."""
        return {
            "active": self.active,
            "fresh": self.fresh,
            "age_days": self.age_days,
            "age_hours": self.age_hours,
            "freshness_window_hours": self.freshness_window_hours,
            "freshness_precision": self.freshness_precision,
            "freshness_source": self.freshness_source,
            "source_quality": self.source_quality,
            "reasons": self.reasons,
        }


class RecruiterAgent:
    """Agent A: identify viable, fresh job records before deeper analysis."""

    name = "agent_a_recruiter"

    def inspect(
        self,
        job: Job,
        fresh_days: int = 7,
        now: datetime | None = None,
        fresh_hours: int | None = None,
    ) -> RecruiterFinding:
        """Validate one job and prove freshness at the requested hour precision."""
        valid, validation_reason = validate_job(job)
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        posted = _parse_posted_datetime(job.posted_date)
        precision = _posted_precision(job.posted_date)
        window_hours = max(1, int(fresh_hours if fresh_hours is not None else fresh_days * 24))
        provenance = job.raw.get("verification_provenance", {}) if isinstance(job.raw, dict) else {}
        freshness_source = str(provenance.get("posted_date") or "job_record")
        reasons: list[str] = []
        fresh: bool | None = None
        age_days: int | None = None
        age_hours: float | None = None
        if posted is None:
            reasons.append("Posting date is unavailable; freshness cannot be proven.")
        else:
            age_days = (current.date() - posted.date()).days
            age_hours = round((current - posted).total_seconds() / 3600, 2)
            if precision == "timestamp":
                fresh = 0 <= age_hours <= window_hours
                reasons.append(
                    f"Posting timestamp is {age_hours:.2f} hour(s) old; exact limit is {window_hours}."
                )
            else:
                # A date-only value represents a 24-hour uncertainty interval.
                # Accept or reject only when that entire interval is on one side
                # of the boundary; a boundary-crossing date remains unknown.
                youngest_age = (current - (posted + timedelta(days=1))).total_seconds() / 3600
                oldest_age = (current - posted).total_seconds() / 3600
                if oldest_age < 0:
                    fresh = False
                elif oldest_age <= window_hours:
                    fresh = True
                elif youngest_age > window_hours:
                    fresh = False
                else:
                    fresh = None
                reasons.append(
                    "Date-only posting evidence spans "
                    f"{max(0.0, youngest_age):.2f}-{max(0.0, oldest_age):.2f} hour(s) old "
                    f"against a {window_hours}-hour limit; result is {fresh}."
                )
        if not valid:
            reasons.append(validation_reason)
        return RecruiterFinding(
            active=valid,
            fresh=fresh,
            age_days=age_days,
            age_hours=age_hours,
            freshness_window_hours=window_hours,
            freshness_precision=precision,
            freshness_source=freshness_source,
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
    direct_domain_verified: bool
    verification_url: str
    verified_at: str
    freshness: dict[str, Any]
    matched_skills: list[str]
    matched_evidence: list[str]
    gaps: list[str]
    tailoring: dict[str, Any]
    insights: list[str]
    blockers: list[str]
    discrepancies: list[str]
    resume_matcher: dict[str, Any] | None = None
    posting_intelligence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize Agent B's complete decision and evidence trail."""
        return {
            "score": self.score,
            "fit_label": self.fit_label,
            "recommendation": self.recommendation,
            "live_verified": self.live_verified,
            "direct_domain_verified": self.direct_domain_verified,
            "verification_url": self.verification_url,
            "verified_at": self.verified_at,
            "freshness": self.freshness,
            "matched_skills": self.matched_skills,
            "matched_evidence": self.matched_evidence,
            "gaps": self.gaps,
            "tailoring": self.tailoring,
            "insights": self.insights,
            "blockers": self.blockers,
            "discrepancies": self.discrepancies,
            "resume_matcher": self.resume_matcher,
            "posting_intelligence": self.posting_intelligence,
        }


    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatchAnalysis":
        """Rehydrate the exact persisted Agent B decision for Agent C."""
        return cls(
            score=float(data.get("score", 0)),
            fit_label=str(data.get("fit_label") or ""),
            recommendation=str(data.get("recommendation") or "skip"),
            live_verified=data.get("live_verified") is True,
            direct_domain_verified=data.get("direct_domain_verified") is True,
            verification_url=str(data.get("verification_url") or ""),
            verified_at=str(data.get("verified_at") or ""),
            freshness=dict(data.get("freshness") or {}),
            matched_skills=list(data.get("matched_skills") or []),
            matched_evidence=list(data.get("matched_evidence") or []),
            gaps=list(data.get("gaps") or []),
            tailoring=dict(data.get("tailoring") or {}),
            insights=list(data.get("insights") or []),
            blockers=list(data.get("blockers") or []),
            discrepancies=list(data.get("discrepancies") or []),
            resume_matcher=data.get("resume_matcher"),
            posting_intelligence=data.get("posting_intelligence"),
        )


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
        fresh_hours: int | None = None,
        client: WebClawClient | None = None,
        resume_matcher: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MatchAnalysis:
        """Review stored facts, optionally re-scrape the page, and issue a decision."""
        current_job = job
        live_verified = False
        direct_domain_verified = False
        verification_url = ""
        discrepancies: list[str] = []
        blockers: list[str] = []

        if client is not None:
            try:
                refreshed = normalize_webclaw_job(job.url, client.scrape(job.url))
                valid, reason = validate_job(refreshed)
                if not valid:
                    blockers.append(f"Live page validation failed: {reason}.")
                else:
                    domain = direct_application_domain(refreshed.url, refreshed.company)
                    direct_domain_verified = domain.get("verified") is True
                    if not direct_domain_verified:
                        blockers.append(
                            "Direct application-domain verification failed: "
                            f"{domain.get('reason', 'unknown domain')}."
                        )
                    else:
                        live_verified = True
                        verification_url = refreshed.url
                    refreshed_raw = dict(refreshed.raw)
                    if isinstance(job.raw, dict) and job.raw.get("posting_intelligence"):
                        refreshed_raw["posting_intelligence"] = job.raw["posting_intelligence"]
                    refreshed_raw["verification_provenance"] = {
                        "posted_date": "employer_page" if refreshed.posted_date else "agent_a_verified_record",
                        "location": "employer_page" if normalize_space(refreshed.location).casefold()
                        not in {"", "unknown", "unspecified", "not specified", "n/a"}
                        else "agent_a_verified_record",
                        "work_mode": "employer_page" if normalize_space(refreshed.work_mode).casefold()
                        not in {"", "unknown", "unspecified", "not specified", "n/a"}
                        else "agent_a_verified_record",
                    }
                    current_job = replace(
                        refreshed,
                        posted_date=refreshed.posted_date or job.posted_date,
                        location=(
                            job.location
                            if normalize_space(refreshed.location).casefold()
                            in {"", "unknown", "unspecified", "not specified", "n/a"}
                            else refreshed.location
                        ),
                        work_mode=(
                            job.work_mode
                            if normalize_space(refreshed.work_mode).casefold()
                            in {"", "unknown", "unspecified", "not specified", "n/a"}
                            else refreshed.work_mode
                        ),
                        raw=refreshed_raw,
                    )
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

        verified_finding = RecruiterAgent().inspect(
            current_job,
            fresh_days=fresh_days,
            fresh_hours=fresh_hours,
            now=now,
        )
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
        posting_intelligence = (
            job.raw.get("posting_intelligence", {}) if isinstance(job.raw, dict) else {}
        )
        trust = posting_intelligence.get("trust", {}) or {}
        repost = posting_intelligence.get("repost", {}) or {}
        cross_listings = posting_intelligence.get("cross_listings", []) or []
        legitimacy_concerns: list[str] = []
        if trust:
            insights.append(
                "Posting confidence: "
                f"{str(trust.get('level', 'unknown')).title()} "
                f"({trust.get('score', 0)}/100); this does not alter the resume-fit score."
            )
            if trust.get("level") == "low":
                legitimacy_concerns.append("low source trust")
        if repost.get("detected"):
            appearances = int(repost.get("appearance_count", 2))
            legitimacy_concerns.append(f"same-company role appeared {appearances} times")
            insights.append(
                f"Repost signal: {appearances} distinct URLs appeared inside "
                f"{repost.get('window_days', 90)} days."
            )
        if cross_listings:
            legitimacy_concerns.append("near-identical description under another company")
            insights.append(
                f"Cross-listing signal: {len(cross_listings)} near-identical description(s) "
                "were found under another company name."
            )
        if recommendation == "apply" and (
            trust.get("level") == "low" or len(legitimacy_concerns) >= 2
        ):
            recommendation = "review"
            insights.append(
                "Manual review required because independent posting-legitimacy signals conflict."
            )
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

        tailoring = build_tailoring_plan(current_job, match, resume_matcher)
        return MatchAnalysis(
            score=match.final_score,
            fit_label=match.fit_label,
            recommendation=recommendation,
            live_verified=live_verified,
            direct_domain_verified=direct_domain_verified,
            verification_url=verification_url,
            verified_at=utc_now(),
            freshness=verified_finding.to_dict(),
            matched_skills=match.matched_skills,
            matched_evidence=match.matched_evidence,
            gaps=list(dict.fromkeys(analysis_gaps)),
            tailoring=tailoring,
            insights=insights,
            blockers=blockers,
            discrepancies=discrepancies,
            resume_matcher=resume_matcher,
            posting_intelligence=posting_intelligence or None,
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
        handoff: dict[str, Any] | None = None,
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

        tailoring_plan = dict(analysis.tailoring or {})
        tailoring_notes = [
            *list(tailoring_plan.get("summary_focus", []))[:2],
            *list(tailoring_plan.get("evidence_bullets", []))[:2],
            "Use only documented resume evidence; do not add unstated credentials or results.",
        ]
        packet = {
            "schema_version": 2,
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
            "agent_b_handoff": dict(handoff or {}),
            "match": {
                "score": analysis.score,
                "recommendation": analysis.recommendation,
                "live_verified": analysis.live_verified,
                "direct_domain_verified": analysis.direct_domain_verified,
                "verified_at": analysis.verified_at,
                "freshness": analysis.freshness,
                "matched_skills": analysis.matched_skills,
                "matched_evidence": analysis.matched_evidence,
                "gaps": analysis.gaps,
            },
            "tailoring_plan": tailoring_plan,
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
