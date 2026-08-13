"""Normalize WebClaw output and Schema.org JobPosting data into one job model."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import urlsplit

from .util import canonical_url, normalize_space, stable_id, unique_preserving_order, utc_now


@dataclass
class Job:
    """Canonical job record persisted and scored by the application."""
    id: str
    url: str
    title: str
    company: str
    location: str
    work_mode: str
    employment_type: str
    posted_date: str
    salary: str
    description: str
    source: str = "webclaw"
    required_years: float | None = None
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    discovered_at: str = field(default_factory=utc_now)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert this dataclass to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "work_mode": self.work_mode,
            "employment_type": self.employment_type,
            "posted_date": self.posted_date,
            "salary": self.salary,
            "description": self.description,
            "source": self.source,
            "required_years": self.required_years,
            "required_skills": self.required_skills,
            "preferred_skills": self.preferred_skills,
            "responsibilities": self.responsibilities,
            "discovered_at": self.discovered_at,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        """Build a job from known dataclass fields and ignore unknown extension fields."""
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})


def _iter_json_objects(value: Any) -> Iterable[dict[str, Any]]:
    """Yield every nested dictionary in JSON-LD graphs, arrays, and objects."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_objects(child)


def _find_job_posting(structured_data: Any) -> dict[str, Any]:
    """Return the first nested Schema.org object whose type is JobPosting."""
    for item in _iter_json_objects(structured_data):
        item_type = item.get("@type", "")
        types = item_type if isinstance(item_type, list) else [item_type]
        if any(str(value).casefold() == "jobposting" for value in types):
            return item
    return {}


def _strip_html(value: str | None) -> str:
    """Remove scripts, styles, tags, and entity encoding from a short HTML fragment."""
    if not value:
        return ""
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h[1-6]>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_space(html.unescape(value))


def _organization_name(value: Any) -> str:
    """Read an organization name from either JSON-LD object or string syntax."""
    if isinstance(value, dict):
        return normalize_space(value.get("name"))
    return normalize_space(str(value)) if value else ""


def _location_text(value: Any) -> str:
    """Flatten one or more Schema.org Place/PostalAddress values into display text."""
    locations = value if isinstance(value, list) else [value]
    output: list[str] = []
    for location in locations:
        if isinstance(location, str):
            output.append(location)
            continue
        if not isinstance(location, dict):
            continue
        address = location.get("address", location)
        if isinstance(address, str):
            output.append(address)
            continue
        if isinstance(address, dict):
            parts = unique_preserving_order(str(value) for value in [
                address.get("addressLocality"),
                address.get("addressRegion"),
                address.get("addressCountry"),
            ] if value)
            output.append(", ".join(parts))
    return "; ".join(unique_preserving_order(output))


def _salary_text(value: Any) -> str:
    """Flatten common Schema.org MonetaryAmount/QuantitativeValue salary shapes."""
    if not isinstance(value, dict):
        return normalize_space(str(value)) if value else ""
    currency = value.get("currency", "")
    amount = value.get("value", value)
    if isinstance(amount, dict):
        low = amount.get("minValue")
        high = amount.get("maxValue")
        unit = amount.get("unitText", "")
        if low is not None and high is not None:
            return normalize_space(f"{currency} {low}-{high} {unit}")
        if amount.get("value") is not None:
            return normalize_space(f"{currency} {amount['value']} {unit}")
    return normalize_space(json.dumps(value, ensure_ascii=False))


def _split_page_title(value: str) -> tuple[str, str]:
    """Derive a conservative title/company fallback from common page-title separators."""
    value = normalize_space(value)
    hrmdirect_title = re.match(
        r"(?i)^(?P<title>.+?)\s*,?\s+careers\s+at\s+(?P<company>.+)$",
        value,
    )
    if hrmdirect_title:
        return (
            normalize_space(hrmdirect_title.group("title")),
            normalize_space(hrmdirect_title.group("company")),
        )
    for separator in (" | ", " - ", " at ", " @ "):
        if separator in value:
            parts = [part.strip() for part in value.split(separator) if part.strip()]
            if len(parts) >= 2:
                return parts[0], parts[-1]
    return value, ""


def _company_from_markdown(url: str, markdown: str) -> str:
    """Recover direct-ATS company names from logo alt text or a conservative URL slug."""
    logo = re.search(r"!\[(?:!\[)?([^\]]+?)\s+Logo\]", markdown, flags=re.IGNORECASE)
    if logo:
        return normalize_space(logo.group(1))
    host = urlsplit(url).netloc.casefold()
    if "greenhouse.io" in host:
        path_parts = [part for part in urlsplit(url).path.split("/") if part]
        if path_parts:
            slug = re.sub(r"[-_]", " ", path_parts[0])
            return normalize_space(slug.title())
    if host == "hrmdirect.com" or host.endswith(".hrmdirect.com"):
        labels = host.split(".")
        tenant = labels[-3] if len(labels) >= 3 else ""
        if tenant not in {"", "www", "secure", "jobs", "careers"}:
            slug = re.sub(r"[-_]+", " ", tenant)
            return normalize_space(slug.title())
    return ""


def infer_work_mode(location: str, description: str) -> str:
    """Classify remote, hybrid, onsite, or unknown from stated posting language."""
    text = f"{location} {description[:5000]}".casefold()
    if re.search(r"\bhybrid\b", text):
        return "hybrid"
    if re.search(r"\b(remote|work from home|distributed)\b", text):
        return "remote"
    if re.search(r"\b(on[- ]?site|in office)\b", text):
        return "onsite"
    return "unknown"


def infer_required_years(description: str) -> float | None:
    """Extract the lowest explicit years-of-experience requirement from posting text."""
    years = [
        float(match.group(1))
        for match in re.finditer(
            r"(?i)\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\+?\s+years?(?:\s+of)?\s+(?:relevant\s+)?experience",
            description,
        )
    ]
    return min(years) if years else None


def _normalize_liveness_text(value: str) -> str:
    """Normalize punctuation and accents before matching closure banners."""
    value = str(value or "").replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = "".join(
        character
        for character in unicodedata.normalize("NFD", value)
        if unicodedata.category(character) != "Mn"
    )
    return normalize_space(value).casefold()


def validate_job(job: Job) -> tuple[bool, str]:
    """Reject empty shells, generic career indexes, and expired/redirected job pages."""
    if len(job.description) < 180:
        return False, "extracted job description is too short"
    generic_titles = {"jobs", "careers", "current openings", "job opportunities", "open positions"}
    normalized_title = normalize_space(job.title).casefold()
    if normalized_title in generic_titles:
        return False, f"generic page title: {job.title}"
    if any(marker in normalized_title for marker in ("job expired", "position filled", "no longer available")):
        return False, "page title states that the role is closed"
    description = _normalize_liveness_text(job.description)
    bot_challenges = (
        "just a moment",
        "performing security verification",
        "checking your browser before",
        "verify you are human",
        "verify you are not a human",
        "enable javascript and cookies to continue",
        "please complete the security check",
    )
    if any(marker in description[:1200] for marker in bot_challenges):
        return False, "page is an access challenge, so posting liveness is uncertain"
    closed_markers = (
        "this job is no longer available",
        "this position is no longer available",
        "this role is no longer available",
        "job is no longer open",
        "job no longer open",
        "this job has expired",
        "this job listing is closed",
        "this job is closed",
        "this position has been filled",
        "job posting has expired",
        "no longer accepting applications",
        "applications have closed",
        "applications are closed",
        "applications closed",
        "the job you are looking for is no longer",
        "job not found",
        "job listing not found",
        "the job you requested was not found",
        "the job posting you're looking for might have closed",
        "it has been removed",
        "couldn't find anything here",
        "404 error",
    )
    if any(marker in description[:2500] for marker in closed_markers):
        return False, "page states that the role is closed or no longer accepting applications"
    filled = re.search(
        r"\b(?:job|position|role|posting|opening|vacancy|requisition|req|listing)\b"
        r".{0,60}?\bhas been filled\b(?!\s+out)",
        description[:2500],
    )
    if filled and not re.search(r"\b(?:application|form)\s+has been filled", filled.group(0)):
        return False, "page states that the role has been filled"
    markers = (
        "responsibilities",
        "qualifications",
        "requirements",
        "what you'll do",
        "what you will do",
        "about the role",
        "employment type",
        "minimum qualifications",
    )
    if not any(marker in description for marker in markers):
        return False, "page does not contain role-specific responsibility or qualification markers"
    return True, ""


def normalize_webclaw_job(url: str, payload: dict[str, Any], ai_fields: dict[str, Any] | None = None) -> Job:
    """Merge JSON-LD, WebClaw metadata/content, and optional AI fields by trust order."""
    ai_fields = ai_fields or {}
    metadata = payload.get("metadata") or {}
    content = payload.get("content") or {}
    structured_data = payload.get("structured_data") or []
    posting = _find_job_posting(structured_data)

    page_title, page_company = _split_page_title(str(metadata.get("title") or ""))
    description = _strip_html(
        posting.get("description")
        or content.get("plain_text")
        or content.get("markdown")
        or ai_fields.get("description")
    )
    title = normalize_space(ai_fields.get("title") or posting.get("title") or page_title or "Untitled role")
    markdown = str(content.get("markdown") or "")
    company = normalize_space(
        ai_fields.get("company")
        or _organization_name(posting.get("hiringOrganization"))
        or metadata.get("site_name")
        or page_company
        or _company_from_markdown(url, markdown)
        or "Unknown company"
    )
    metadata_description = normalize_space(metadata.get("description"))
    metadata_location = metadata_description if 0 < len(metadata_description) <= 120 else ""
    location = normalize_space(
        ai_fields.get("location")
        or _location_text(posting.get("jobLocation"))
        or _location_text(posting.get("applicantLocationRequirements"))
        or metadata_location
        or "Unspecified"
    )
    if str(posting.get("jobLocationType", "")).casefold() == "telecommute" and "remote" not in location.casefold():
        location = f"Remote; {location}" if location != "Unspecified" else "Remote"

    work_mode = normalize_space(ai_fields.get("work_mode")) or infer_work_mode(location, description)
    if work_mode.casefold() not in {"remote", "hybrid", "onsite", "unknown"}:
        work_mode = infer_work_mode(location, description)

    employment_type = posting.get("employmentType") or ai_fields.get("employment_type") or ""
    if isinstance(employment_type, list):
        employment_type = ", ".join(str(value) for value in employment_type)
    posted_date = normalize_space(ai_fields.get("posted_date") or posting.get("datePosted") or metadata.get("published_date"))
    salary = normalize_space(ai_fields.get("salary") or _salary_text(posting.get("baseSalary")))
    required_years = ai_fields.get("required_years_experience")
    try:
        required_years = float(required_years) if required_years not in (None, "") else infer_required_years(description)
    except (TypeError, ValueError):
        required_years = infer_required_years(description)

    clean_url = canonical_url(url)
    return Job(
        id=stable_id(clean_url),
        url=clean_url,
        title=title,
        company=company,
        location=location,
        work_mode=work_mode.casefold(),
        employment_type=normalize_space(str(employment_type)),
        posted_date=posted_date,
        salary=salary,
        description=description,
        required_years=required_years,
        required_skills=unique_preserving_order(ai_fields.get("required_skills", [])),
        preferred_skills=unique_preserving_order(ai_fields.get("preferred_skills", [])),
        responsibilities=unique_preserving_order(ai_fields.get("responsibilities", [])),
        raw=payload,
    )


def job_from_fixture(data: dict[str, Any]) -> Job:
    """Build a normalized job from a deterministic test/demo fixture."""
    clean_url = canonical_url(data["url"])
    return Job(
        id=data.get("id") or stable_id(clean_url),
        url=clean_url,
        title=data.get("title", "Untitled role"),
        company=data.get("company", "Unknown company"),
        location=data.get("location", "Unspecified"),
        work_mode=data.get("work_mode", infer_work_mode(data.get("location", ""), data.get("description", ""))),
        employment_type=data.get("employment_type", ""),
        posted_date=data.get("posted_date", ""),
        salary=data.get("salary", ""),
        description=data.get("description", ""),
        required_years=data.get("required_years"),
        required_skills=data.get("required_skills", []),
        preferred_skills=data.get("preferred_skills", []),
        responsibilities=data.get("responsibilities", []),
        source=data.get("source", "fixture"),
        raw=data,
    )
