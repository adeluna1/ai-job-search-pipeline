"""WebClaw fallback discovery, employer-page resolution, and active-role verification."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import html
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from .integrations.agent_web_browser import (
    AgentWebBrowserClient,
    AgentWebBrowserError,
)
from .candidate_triage import ats_job_id, ats_platform, classify_resolution_failure
from .jobs import Job, normalize_webclaw_job, validate_job
from .util import canonical_url, normalize_space, normalize_term, stable_id, unique_preserving_order, utc_now
from .webclaw import WebClawClient, WebClawError


BOARD_DOMAINS = {
    "glassdoor": (
        "glassdoor.com",
        "glassdoor.ca",
        "glassdoor.co.in",
        "glassdoor.co.uk",
        "glassdoor.com.au",
        "glassdoor.de",
        "glassdoor.fr",
    ),
    "zip_recruiter": ("ziprecruiter.com", "ziprecruiter.ca"),
    "linkedin": ("linkedin.com",),
    "indeed": ("indeed.com", "indeed.ca", "indeed.co.uk"),
}
OTHER_AGGREGATOR_DOMAINS = (
    "bebee.com",
    "careerbuilder.com",
    "dice.com",
    "jooble.org",
    "lensa.com",
    "monster.com",
    "simplyhired.com",
    "talent.com",
)
DIRECT_ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
    "catsone.com",
    "bamboohr.com",
    "breezy.hr",
    "recruitee.com",
    "teamtailor.com",
    "taleo.net",
    "workable.com",
    "dayforcehcm.com",
    "dayforce.com",
    "applytojob.com",
    "paylocity.com",
    "paycomonline.net",
    "hrmdirect.com",
    "workwolf.com",
)
DIRECT_ATS_SEARCH_GROUPS = {
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
TITLE_SEARCH_FAMILIES = {
    "recruiting_coordination": (
        "recruiting coordinator", "recruitment coordinator",
        "recruiting assistant", "recruiting scheduler",
    ),
    "talent_acquisition_coordination": (
        "talent acquisition coordinator", "sourcing coordinator",
    ),
    "recruiting_operations": (
        "recruiting operations coordinator", "talent operations coordinator",
        "candidate experience coordinator",
    ),
    "junior_recruiter": (
        "recruiting associate", "associate recruiter",
        "talent acquisition associate", "junior recruiter",
        "recruiter i", "recruiter 1", "talent acquisition specialist",
    ),
    "university_recruiting": (
        "university recruiting coordinator", "university recruiter",
        "campus recruiter", "campus recruiting coordinator",
    ),
    "adjacent_review": (
        "recruitment and hr coordinator", "talent strategy and operations associate",
        "talent outreach coordinator", "recruiting relations specialist",
        "people engagement coordinator", "hr specialist recruitment",
    ),
}
NON_APPLICATION_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "google.com",
)


BAY_AREA_DIRECT_SEARCH_LOCATIONS = (
    "Mountain View, California",
    "Palo Alto, California",
    "Santa Clara, California",
    "Sunnyvale, California",
    "Fremont, California",
    "San Mateo, California",
    "Redwood City, California",
    "Walnut Creek, California",
    "Pleasanton, California",
)
GREENHOUSE_BOARD_TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

def _host(url: str) -> str:
    return urlsplit(url).netloc.casefold()


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_board_url(url: str) -> bool:
    host = _host(url)
    domains = (
        domain for board_domains in BOARD_DOMAINS.values() for domain in board_domains
    )
    return any(_host_matches(host, domain) for domain in domains) or any(
        _host_matches(host, domain) for domain in OTHER_AGGREGATOR_DOMAINS
    )


def _board_for_url(url: str) -> str | None:
    """Return the canonical supported board name for an aggregator URL."""
    host = _host(url)
    for board, domains in BOARD_DOMAINS.items():
        if any(_host_matches(host, domain) for domain in domains):
            return board
    return None


def _is_application_candidate(url: str) -> bool:
    """Keep plausible employer/ATS job URLs and reject board/social navigation."""
    parts = urlsplit(url)
    host = parts.netloc.casefold()
    path = parts.path.casefold()
    if parts.scheme not in {"http", "https"} or not host:
        return False
    if _is_board_url(url) or any(
        _host_matches(host, domain) for domain in NON_APPLICATION_DOMAINS
    ):
        return False
    return (
        any(_host_matches(host, domain) for domain in DIRECT_ATS_DOMAINS)
        or host.startswith(("jobs.", "careers."))
        or any(token in path for token in ("/job", "/jobs", "/career", "/apply", "/position"))
    )

def _expanded_direct_search_locations(locations: Iterable[str]) -> list[str]:
    """Expand a Bay Area alias for discovery while preserving exact downstream gates."""
    requested = unique_preserving_order(
        normalize_space(location) for location in locations if normalize_space(location)
    )
    if any("bay area" in normalize_term(location) for location in requested):
        requested.extend(
            location
            for location in BAY_AREA_DIRECT_SEARCH_LOCATIONS
            if location not in requested
        )
    return requested


def _parse_greenhouse_updated_at(value: str) -> datetime | None:
    """Parse the official Greenhouse feed timestamp without guessing."""
    try:
        parsed = datetime.fromisoformat(normalize_space(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _live_greenhouse_candidates(
    client: WebClawClient,
    boards: Iterable[str],
    title_groups: dict[str, list[str]],
    hours_old: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read configured public Greenhouse feeds so new jobs need not be search-indexed."""
    diagnostics: dict[str, Any] = {
        "requested_boards": [], "endpoints": {}, "errors": {},
        "jobs_seen": 0, "matching_recent_jobs": 0,
    }
    matches: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours_old)))
    requested_titles = [
        (family, normalize_term(title), title)
        for family, titles in title_groups.items()
        for title in titles
    ]
    for raw_board in unique_preserving_order(boards):
        board = normalize_space(raw_board).casefold()
        if not GREENHOUSE_BOARD_TOKEN.fullmatch(board):
            diagnostics["errors"][board or str(raw_board)] = "invalid Greenhouse board token"
            continue
        diagnostics["requested_boards"].append(board)
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        diagnostics["endpoints"][board] = endpoint
        try:
            probe = client.probe(endpoint)
            status = int(probe.get("status") or 0)
            if status < 200 or status >= 300:
                raise WebClawError(f"official Greenhouse feed returned HTTP {status}")
            payload = json.loads(str(probe.get("body") or ""))
            records = payload.get("jobs", []) if isinstance(payload, dict) else []
            if not isinstance(records, list):
                raise WebClawError("official Greenhouse feed returned an unexpected shape")
        except (WebClawError, json.JSONDecodeError, TypeError, ValueError) as exc:
            diagnostics["errors"][board] = str(exc)
            continue
        diagnostics["jobs_seen"] += len(records)
        for record in records:
            if not isinstance(record, dict):
                continue
            normalized_title = normalize_term(str(record.get("title") or ""))
            title_match = next(((family, title) for family, normalized, title in requested_titles
                                if normalized and normalized in normalized_title), None)
            updated_at = _parse_greenhouse_updated_at(str(record.get("updated_at") or ""))
            url = canonical_url(str(record.get("absolute_url") or ""))
            if (title_match is None or updated_at is None or updated_at < cutoff
                    or not _host_matches(_host(url), "greenhouse.io")
                    or "/jobs/" not in urlsplit(url).path.casefold()):
                continue
            location_value = record.get("location", {})
            location = (normalize_space(str(location_value.get("name") or ""))
                        if isinstance(location_value, dict) else normalize_space(str(location_value or "")))
            matches.append({
                "url": url, "title": normalize_space(str(record.get("title") or "")),
                "location": location, "updated_at": updated_at.isoformat(),
                "title_group": title_match[0], "requested_title": title_match[1], "board": board,
            })
    diagnostics["matching_recent_jobs"] = len(matches)
    return matches, diagnostics




def _requested_title_groups(search_term: str) -> dict[str, list[str]]:
    """Keep direct-ATS queries small by grouping only titles present in the request."""
    normalized_query = normalize_space(search_term).casefold()
    quoted = [normalize_space(value) for value in re.findall(r'"([^"\r\n]+)"', search_term)]
    requested = quoted or [normalize_space(search_term.strip('"() '))]
    output: dict[str, list[str]] = {}
    for family, titles in TITLE_SEARCH_FAMILIES.items():
        matches = [
            title for title in titles
            if title in normalized_query
            or any(normalize_space(value).casefold() == title for value in requested)
        ]
        if matches:
            output[family] = unique_preserving_order(matches)
    if not output:
        safe_titles = [value for value in requested if value and len(value) <= 100]
        output["requested"] = safe_titles[:6] or ["recruiting coordinator"]
    return output


def requested_title_family_queries(search_term: str) -> dict[str, str]:
    """Return bounded OR queries for the maintained entry-level title families."""
    return {
        family: " OR ".join(f'"{title}"' for title in titles)
        for family, titles in _requested_title_groups(search_term).items()
        if titles
    }

def _discovery_job_hint(
    source_url: str,
    visible_title: str,
    location: str,
    source: str,
) -> Job:
    """Build a non-verified identity hint from search-result evidence only."""
    title = normalize_space(visible_title) or "Unresolved recruiting lead"
    company = "Unknown company"
    for separator in (" at ", " | ", " - "):
        if separator in title:
            parts = [normalize_space(value) for value in title.split(separator) if normalize_space(value)]
            if len(parts) >= 2:
                title, company = parts[0], parts[-1]
                break
    clean_url = canonical_url(source_url)
    return Job(
        id=stable_id(clean_url),
        url=clean_url,
        title=title,
        company=company,
        location=normalize_space(location) or "Unspecified",
        work_mode="remote" if "remote" in normalize_space(location).casefold() else "unknown",
        employment_type="",
        posted_date="",
        salary="",
        description="",
        source=source,
        raw={"discovery_evidence": {"source_urls": [clean_url], "unverified_hint": True}},
    )

def _payload_links(value: Any, parent_key: str = "") -> list[str]:
    """Read explicit URL/link/href fields from WebClaw JSON without mining body prose."""
    links: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).casefold()
            if isinstance(child, str) and (
                normalized_key in {"url", "link", "href"}
                or normalized_key.endswith("_url")
            ):
                links.append(child)
            else:
                links.extend(_payload_links(child, normalized_key))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, str) and parent_key in {"links", "urls"}:
                links.append(child)
            else:
                links.extend(_payload_links(child, parent_key))
    return links


def _candidate_rank(url: str) -> tuple[int, int]:
    """Prefer known direct ATS pages, then obvious employer job paths."""
    host = _host(url)
    direct_rank = 0 if any(_host_matches(host, domain) for domain in DIRECT_ATS_DOMAINS) else 1
    return direct_rank, len(url)


def _identity_tokens(value: str) -> set[str]:
    ignored = {"the", "and", "inc", "llc", "corp", "company", "co", "job", "jobs"}
    return {
        token
        for token in normalize_space(value).casefold().replace("-", " ").split()
        if len(token) > 2 and token not in ignored
    }


def _identity_slug(value: str) -> str:
    """Join meaningful employer tokens in their original order for domain matching."""
    ignored = {"the", "and", "inc", "llc", "corp", "company", "co", "job", "jobs"}
    tokens = re.findall(r"[a-z0-9]+", normalize_space(value).casefold())
    return "".join(token for token in tokens if len(token) > 2 and token not in ignored)


MULTI_LABEL_PUBLIC_SUFFIXES = {
    "co.uk", "com.au", "co.in", "co.jp", "com.br", "com.mx", "com.sg", "co.nz"
}


def _registrant_label(host: str) -> str:
    """Return the conservative registrant label without trusting arbitrary subdomains."""
    labels = [label for label in host.casefold().strip(".").split(".") if label]
    if len(labels) < 2:
        return ""
    suffix = ".".join(labels[-2:])
    return labels[-3] if suffix in MULTI_LABEL_PUBLIC_SUFFIXES and len(labels) >= 3 else labels[-2]


def direct_application_domain(url: str, company: str) -> dict[str, Any]:
    """Prove that a URL belongs to a known ATS or the named employer.

    A valid-looking page is not enough. Aggregators are rejected, ATS hosts must
    match an exact registered suffix, and other hosts must have a job path plus
    company identity evidence in the hostname.
    """
    parts = urlsplit(url)
    host = parts.netloc.casefold().split(":", 1)[0]
    path = parts.path.casefold()
    evidence: dict[str, Any] = {
        "verified": False,
        "host": host,
        "kind": "unknown",
        "reason": "unclassified application domain",
    }
    if parts.scheme not in {"http", "https"} or not host:
        evidence["reason"] = "invalid HTTP(S) application URL"
        return evidence
    if _is_board_url(url):
        evidence["reason"] = "job board or aggregator domain"
        return evidence
    ats_domain = next(
        (domain for domain in DIRECT_ATS_DOMAINS if _host_matches(host, domain)),
        "",
    )
    if ats_domain:
        return {
            "verified": True,
            "host": host,
            "kind": "direct_ats",
            "matched_domain": ats_domain,
            "reason": "exact known ATS domain",
        }
    has_job_path = any(
        token in path for token in ("/job", "/jobs", "/career", "/apply", "/position")
    )
    registrant = _registrant_label(host)
    registrant_tokens = _identity_tokens(registrant.replace("-", " "))
    company_tokens = _identity_tokens(company) - {"unknown"}
    company_slug = _identity_slug(company)
    registrant_slug = re.sub(r"[^a-z0-9]+", "", registrant)
    company_match = bool(
        registrant
        and (
            registrant in company_tokens
            or registrant_slug == company_slug
            or bool(registrant_tokens.intersection(company_tokens))
        )
    )
    if has_job_path and company_match:
        return {
            "verified": True,
            "host": host,
            "kind": "employer_domain",
            "registrant_label": registrant,
            "matched_company_tokens": sorted(registrant_tokens.intersection(company_tokens)),
            "reason": "job path on registrant label matching the employer identity",
        }
    evidence["reason"] = (
        "hostname does not match the employer identity"
        if has_job_path
        else "URL does not contain an application-specific path"
    )
    return evidence


def _same_role(source: Job, candidate: Job) -> bool:
    """Require title overlap and, when usable, company overlap before redirecting."""
    source_title = _identity_tokens(source.title)
    candidate_title = _identity_tokens(candidate.title)
    if source_title and candidate_title and not source_title.intersection(candidate_title):
        return False
    source_company = _identity_tokens(source.company)
    candidate_company = _identity_tokens(candidate.company)
    unknown = {"unknown"}
    if source_company - unknown and candidate_company - unknown:
        return bool(source_company.intersection(candidate_company))
    return True


def _fresh_application_probe(client: WebClawClient, url: str) -> dict[str, Any]:
    """Fail closed when a no-cache request redirects away from the exact job."""
    probe = getattr(client, "probe", None)
    if not callable(probe):
        return {"performed": False, "active": True, "reason": "probe unavailable"}
    evidence = dict(probe(url) or {})
    evidence["performed"] = True
    status = int(evidence.get("status") or 0)
    final_url = str(evidence.get("final_url") or url)
    final_lower = final_url.casefold()
    requested = urlsplit(url)
    final = urlsplit(final_url)
    body = html.unescape(
        re.sub(r"(?is)<[^>]+>", " ", str(evidence.get("body") or ""))
    )
    body = re.sub(r"\s+", " ", body).casefold()
    if status < 200 or status >= 400:
        evidence.update(active=False, reason=f"fresh probe returned HTTP {status}")
        return evidence
    redirect_markers = (
        "expired_jd_redirect",
        "error=true",
        "jobnotfound",
        "job-not-found",
        "position-closed",
    )
    if any(marker in final_lower for marker in redirect_markers):
        evidence.update(active=False, reason="fresh probe followed an expired-job redirect")
        return evidence
    requested_job_path = any(
        token in requested.path.casefold()
        for token in ("/job/", "/jobs/", "/view/", "/position/")
    )
    evidence.pop("body", None)
    final_job_path = any(
        token in final.path.casefold()
        for token in ("/job/", "/jobs/", "/view/", "/position/")
    )
    if (
        requested_job_path
        and not final_job_path
        and not _is_application_candidate(final_url)
    ):
        evidence.update(active=False, reason="fresh probe redirected to a generic jobs page")
        return evidence
    closed_markers = (
        "this job is no longer available",
        "this position is no longer available",
        "this role is no longer available",
        "no longer accepting applications",
        "the job you are looking for is no longer open",
        "job not found",
        "job posting has expired",
        "applications are closed",
    )
    if any(marker in body[:120_000] for marker in closed_markers):
        evidence.update(
            active=False,
            reason="fresh probe body states that applications are closed",
        )
        return evidence
    evidence.update(
        active=True,
        reason="exact job URL survived a no-cache redirect and closure check",
    )
    return evidence


def _follow_safe_final_url(
    client: WebClawClient,
    requested_url: str,
    job: Job,
    probe: dict[str, Any],
) -> tuple[Job, bool]:
    """Follow a live redirect only when its final page is another direct job URL."""
    final_url = canonical_url(str(probe.get("final_url") or requested_url))
    if final_url == canonical_url(requested_url):
        return job, False
    if not _is_application_candidate(final_url) or _is_board_url(final_url):
        raise WebClawError("fresh probe redirected outside a plausible employer job page")
    payload = client.scrape(final_url)
    final_job = normalize_webclaw_job(final_url, payload)
    valid, reason = validate_job(final_job)
    if not valid:
        raise WebClawError(f"redirect target failed job validation: {reason}")
    if not _same_role(job, final_job):
        raise WebClawError("redirect target title/company did not match the requested role")
    domain = direct_application_domain(final_job.url, final_job.company)
    if domain.get("verified") is not True:
        raise WebClawError(f"redirect target failed direct-domain verification: {domain['reason']}")
    return final_job, True


def _mark_verified(
    job: Job,
    source_url: str,
    resolution: str,
    fresh_probe: dict[str, Any] | None = None,
) -> Job:
    domain = direct_application_domain(job.url, job.company)
    if domain.get("verified") is not True:
        raise WebClawError(f"Direct application-domain verification failed: {domain['reason']}")
    raw = dict(job.raw)
    prior_evidence = raw.get("discovery_evidence", {}) if isinstance(raw.get("discovery_evidence"), dict) else {}
    source_urls = unique_preserving_order([*prior_evidence.get("source_urls", []), source_url, job.url])
    raw["discovery_evidence"] = {
        "source_urls": source_urls,
        "source_count": len(source_urls),
        "deduplicated": len(source_urls) > 1,
    }
    platform = ats_platform(job.url)
    if platform:
        if normalize_term(job.company) in {"", "unknown", "unknown company"}:
            raise WebClawError("structured ATS reader could not establish employer identity")
        raw["structured_ats"] = {
            "source_platform": platform,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "work_mode": job.work_mode,
            "posted_date": job.posted_date,
            "description": job.description,
            "canonical_job_id": ats_job_id(job.url) or job.id,
            "active_status": "active",
            "final_application_url": job.url,
            "evidence_complete": True,
        }
    raw["verification"] = {
        "active": True,
        "verified_at": utc_now(),
        "verified_by": "webclaw",
        "source_url": source_url,
        "resolved_url": job.url,
        "resolution": resolution,
        "direct_domain_verified": True,
        "direct_domain": domain,
        "fresh_application_probe": fresh_probe or {"performed": False},
    }
    source = job.source
    if "webclaw_verified" not in source:
        source = f"{source}; webclaw_verified"
    return replace(job, source=source, raw=raw)


def is_webclaw_verified(job: Job) -> bool:
    """Return whether the canonical job carries a successful live verification receipt."""
    verification = job.raw.get("verification", {}) if isinstance(job.raw, dict) else {}
    return (
        verification.get("active") is True
        and verification.get("verified_by") == "webclaw"
        and verification.get("direct_domain_verified") is True
    )


def resolve_employer_application(
    client: WebClawClient,
    source_url: str,
    search_limit: int = 5,
    browser_client: AgentWebBrowserClient | None = None,
    job_hint: Job | None = None,
) -> tuple[Job, dict[str, Any]]:
    """Resolve one search/board URL to a validated employer application page."""
    source_reader = "webclaw"
    webclaw_error = ""
    try:
        source_payload = client.scrape(source_url)
    except WebClawError as exc:
        source_payload = {}
        webclaw_error = str(exc)

    board = _board_for_url(source_url)
    if not source_payload and board and browser_client is not None:
        try:
            page = browser_client.read_job_page(source_url, board)
            source_payload = {
                # The browser-visible title is live evidence. Never replace a
                # generic ATS shell title (for example, Ashby's "Jobs") with
                # discovery data, because doing so can resurrect a closed role.
                "metadata": {"title": page.title},
                "content": {"plain_text": page.text},
                "structured_data": [],
                "agent_web_browser": {
                    "url": page.url,
                    "platform": page.platform,
                    "text_length": page.text_length,
                },
            }
            source_reader = "agent_web_browser"
        except AgentWebBrowserError as exc:
            raise WebClawError(
                f"WebClaw could not read {source_url} ({webclaw_error}); "
                f"Agent Web Browser fallback also failed: {exc}"
            ) from exc
    if not source_payload:
        raise WebClawError(webclaw_error or f"Could not read {source_url}")

    source_job = normalize_webclaw_job(source_url, source_payload)
    source_valid, source_reason = validate_job(source_job)
    if (
        not source_valid
        and board
        and browser_client is not None
        and source_reader != "agent_web_browser"
    ):
        try:
            page = browser_client.read_job_page(source_url, board)
            source_payload = {
                "metadata": {"title": page.title},
                "content": {"plain_text": page.text},
                "structured_data": [],
                "agent_web_browser": {
                    "url": page.url,
                    "platform": page.platform,
                    "text_length": page.text_length,
                },
            }
            source_job = normalize_webclaw_job(source_url, source_payload)
            source_valid, source_reason = validate_job(source_job)
            source_reader = "agent_web_browser"
        except AgentWebBrowserError:
            pass

    candidates = unique_preserving_order(
        canonical_url(url)
        for url in _payload_links(source_payload)
        if isinstance(url, str) and _is_application_candidate(url)
    )
    candidates.sort(key=_candidate_rank)

    used_resolution_search = False
    resolution_queries: list[str] = []
    identity_job = source_job
    if job_hint is not None and normalize_term(source_job.title) in {
        "", "untitled role", "jobs", "careers", "current openings",
    }:
        identity_job = job_hint
    if not candidates and _is_board_url(source_url):
        usable_identity = (
            normalize_term(identity_job.title) not in {
                "", "untitled role", "jobs", "careers", "current openings",
            }
            and normalize_term(identity_job.company) not in {
                "", "unknown", "unknown company",
            }
        )
        if usable_identity:
            used_resolution_search = True
            exact = f'"{identity_job.title}" "{identity_job.company}"'
            domain_batches = [
                (),
                ("greenhouse.io", "ashbyhq.com", "lever.co", "workable.com"),
                ("myworkdayjobs.com", "smartrecruiters.com", "icims.com", "dayforcehcm.com"),
                ("paycomonline.net", "hrmdirect.com", "workwolf.com"),
            ]
            for domains in domain_batches:
                suffix = (
                    " (" + " OR ".join(f"site:{domain}" for domain in domains) + ")"
                    if domains else " (jobs OR careers OR apply)"
                )
                query = exact + suffix
                resolution_queries.append(query)
                try:
                    results = client.search(
                        query, num=search_limit, country="us", language="en"
                    )
                except WebClawError:
                    continue
                for result in results:
                    url = canonical_url(str(result.get("link", "")))
                    if _is_application_candidate(url):
                        candidates.append(url)
                candidates = unique_preserving_order(candidates)
                if len(candidates) >= search_limit:
                    break
            candidates.sort(key=_candidate_rank)

    candidate_errors: list[dict[str, str]] = []
    for candidate_url in candidates[:search_limit]:
        try:
            payload = client.scrape(candidate_url)
            candidate_job = normalize_webclaw_job(candidate_url, payload)
            valid, reason = validate_job(candidate_job)
            if not valid:
                candidate_errors.append({"url": candidate_url, "error": reason})
                continue
            probe = _fresh_application_probe(client, candidate_url)
            if probe.get("active") is not True:
                candidate_errors.append({
                    "url": candidate_url,
                    "error": str(probe.get("reason") or "fresh application probe failed"),
                })
                continue
            candidate_job, followed_redirect = _follow_safe_final_url(
                client, candidate_url, candidate_job, probe
            )
            source_has_identity = normalize_space(source_job.title).casefold() not in {
                "",
                "untitled role",
                "jobs",
                "careers",
                "current openings",
            }
            if source_has_identity and not _same_role(source_job, candidate_job):
                candidate_errors.append({"url": candidate_url, "error": "title/company mismatch"})
                continue
            return _mark_verified(
                candidate_job,
                source_url,
                "employer_application_page",
                fresh_probe=probe,
            ), {
                "source_url": source_url,
                "resolved_url": candidate_job.url,
                "resolution": "employer_application_page",
                "followed_safe_redirect": followed_redirect,
                "source_reader": source_reader,
                "used_resolution_search": used_resolution_search,
                "resolution_queries": resolution_queries,
                "candidate_errors": candidate_errors,
            }
        except WebClawError as exc:
            candidate_errors.append({"url": candidate_url, "error": str(exc)})

    if source_valid and not _is_board_url(source_url):
        probe = _fresh_application_probe(client, source_url)
        if probe.get("active") is not True:
            raise WebClawError(
                f"Could not resolve {source_url}: "
                f"{probe.get('reason') or 'fresh application probe failed'}"
            )
        source_job, followed_redirect = _follow_safe_final_url(
            client, source_url, source_job, probe
        )
        verified = _mark_verified(
            source_job,
            source_url,
            "source_is_employer_page",
            fresh_probe=probe,
        )
        return verified, {
            "source_url": source_url,
            "resolved_url": verified.url,
            "resolution": "source_is_employer_page",
            "source_reader": source_reader,
            "used_resolution_search": used_resolution_search,
            "resolution_queries": resolution_queries,
            "followed_safe_redirect": followed_redirect,
            "candidate_errors": candidate_errors,
        }

    detail = source_reason if not source_valid else "no validated employer application URL was found"
    raise WebClawError(f"Could not resolve {source_url}: {detail}")

RECOVERY_FAILURE_CATEGORIES = {
    "missing_employer_link",
    "insufficient_page_evidence",
    "manual_verification_required",
    "access_blocked",
    "login_required",
    "javascript_only",
    "temporary_access_failure",
    "browser_budget_exhausted",
}


def recover_employer_application(
    client: WebClawClient,
    job_hint: Job,
    *,
    browser_client: AgentWebBrowserClient | None = None,
    search_limit: int = 8,
) -> tuple[Job, dict[str, Any]]:
    """Recover one manual lead through exact employer/ATS searches.

    Search snippets are discovery evidence only. Promotion still requires the normal
    active-page, direct-domain, title, and employer-identity verification path.
    """
    company = normalize_space(job_hint.company)
    title = normalize_space(job_hint.title)
    if normalize_term(company) in {"", "unknown", "unknown company"}:
        raise WebClawError("verification recovery requires a known company name")
    if normalize_term(title) in {"", "untitled role", "jobs", "careers"}:
        raise WebClawError("verification recovery requires an exact job title")

    location = normalize_space(job_hint.location)
    location_known = normalize_term(location) not in {
        "", "unknown", "unspecified", "not specified", "n a",
    }
    job_identifier = ats_job_id(job_hint.url)
    exact_terms = [f'"{company}"', f'"{title}"']
    if location_known:
        exact_terms.append(f'"{location}"')
    if job_identifier:
        exact_terms.append(f'"{job_identifier}"')
    base = " ".join(exact_terms)

    source_host = _host(job_hint.url)
    official_domains: tuple[str, ...] = ()
    if (
        source_host
        and not _is_board_url(job_hint.url)
        and not any(_host_matches(source_host, domain) for domain in OTHER_AGGREGATOR_DOMAINS)
        and not any(_host_matches(source_host, domain) for domain in DIRECT_ATS_DOMAINS)
        and _identity_slug(_registrant_label(source_host)) == _identity_slug(company)
    ):
        official_domains = (source_host,)

    domain_batches = [
        official_domains,
        ("greenhouse.io", "ashbyhq.com", "lever.co", "workable.com"),
        ("myworkdayjobs.com", "workday.com", "smartrecruiters.com", "icims.com"),
        ("dayforcehcm.com", "dayforce.com", "paycomonline.net", "hrmdirect.com", "workwolf.com"),
    ]
    queries: list[str] = [base + " (careers OR jobs OR apply)"]
    for domains in domain_batches:
        if domains:
            queries.append(
                base + " (" + " OR ".join(f"site:{domain}" for domain in domains) + ")"
            )

    result_urls: list[str] = []
    search_errors: list[str] = []
    raw_url_count = 0
    for query in queries:
        try:
            results = client.search(
                query,
                num=max(1, min(int(search_limit), 10)),
                country="us",
                language="en",
            )
        except WebClawError as exc:
            search_errors.append(str(exc))
            continue
        for result in results:
            url = canonical_url(str(result.get("link") or ""))
            if not url or not _is_application_candidate(url):
                continue
            raw_url_count += 1
            if url != canonical_url(job_hint.url):
                result_urls.append(url)
    candidates = unique_preserving_order(result_urls)
    candidates.sort(key=_candidate_rank)
    diagnostics: dict[str, Any] = {
        "candidate_id": job_hint.id,
        "title": title,
        "company": company,
        "location": location if location_known else "Unspecified",
        "job_id": job_identifier,
        "queries": queries,
        "candidate_urls": candidates,
        "duplicate_candidate_urls_avoided": max(0, raw_url_count - len(candidates)),
        "search_errors": search_errors,
        "candidate_errors": [],
    }

    for candidate_url in candidates:
        try:
            recovered, resolution = resolve_employer_application(
                client,
                candidate_url,
                browser_client=browser_client,
                job_hint=job_hint,
            )
            if not _same_role(job_hint, recovered):
                raise WebClawError("recovered employer page title/company mismatch")
            diagnostics["resolved_url"] = recovered.url
            diagnostics["resolution"] = resolution
            return recovered, diagnostics
        except WebClawError as exc:
            diagnostics["candidate_errors"].append({
                "url": candidate_url,
                "error": str(exc),
            })

    detail = (
        diagnostics["candidate_errors"][-1]["error"]
        if diagnostics["candidate_errors"]
        else search_errors[-1]
        if search_errors
        else "no employer or trusted ATS job-specific URL was found"
    )
    raise WebClawError(f"Verification recovery failed for {title} at {company}: {detail}")

def webclaw_fallback_discovery(
    client: WebClawClient,
    search_term: str,
    location: str,
    hours_old: int,
    boards: Iterable[str],
    results_wanted: int,
    browser_client: AgentWebBrowserClient | None = None,
) -> tuple[list[Job], dict[str, Any]]:
    """Search missing boards by bounded title family and verify only direct pages."""
    jobs: list[Job] = []
    title_queries = requested_title_family_queries(search_term)
    diagnostics: dict[str, Any] = {
        "requested_boards": list(boards),
        "title_family_queries": title_queries,
        "queries_by_board": {},
        "search_errors_by_board": {},
        "result_urls_by_board": {},
        "resolution_records": [],
        "resolution_errors": [],
        "duplicate_source_urls_avoided": 0,
    }
    per_board = max(1, min(int(results_wanted), 10))
    days = max(1, (max(1, int(hours_old)) + 23) // 24)
    seen_source_urls: set[str] = set()
    for board in diagnostics["requested_boards"]:
        domains = BOARD_DOMAINS.get(board, ())
        site_filter = " OR ".join(f"site:{domain}" for domain in domains)
        board_name = board.replace("_", " ")
        diagnostics["queries_by_board"][board] = {}
        diagnostics["result_urls_by_board"][board] = []
        for family, search_expression in title_queries.items():
            query = (
                f'({search_expression}) "{location}" ({site_filter or board_name}) '
                f'("posted" OR "days ago") past {days} days'
            )
            diagnostics["queries_by_board"][board][family] = query
            try:
                results = client.search(query, num=per_board, country="us", language="en")
            except WebClawError as exc:
                diagnostics["search_errors_by_board"].setdefault(board, {})[family] = str(exc)
                continue
            urls = unique_preserving_order(
                canonical_url(str(result.get("link", "")))
                for result in results
                if result.get("link")
            )
            diagnostics["result_urls_by_board"][board].extend(urls)
            result_by_url = {
                canonical_url(str(result.get("link", ""))): result
                for result in results if result.get("link")
            }
            for url in urls:
                if url in seen_source_urls:
                    diagnostics["duplicate_source_urls_avoided"] += 1
                    continue
                seen_source_urls.add(url)
                result = result_by_url.get(url, {})
                title_evidence = normalize_space(str(result.get("title") or ""))
                job_hint = _discovery_job_hint(
                    url,
                    title_evidence,
                    "Unspecified",
                    f"webclaw_fallback:{board}:{family}",
                )
                try:
                    job, resolution = resolve_employer_application(
                        client,
                        url,
                        browser_client=browser_client,
                        job_hint=job_hint,
                    )
                    jobs.append(job)
                    diagnostics["resolution_records"].append({
                        **resolution,
                        "title_family": family,
                    })
                except WebClawError as exc:
                    diagnostics["resolution_errors"].append({
                        "board": board,
                        "requested_location": location,
                        "location": "Unspecified",
                        "source_url": url,
                        "title": title_evidence or "Unresolved recruiting lead",
                        "company": job_hint.company,
                        "posting_date_evidence": "",
                        "title_family": family,
                        "error": str(exc),
                    })

    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        unique_jobs.setdefault(canonical_url(job.url), job)
    diagnostics["result_urls_by_board"] = {
        board: unique_preserving_order(urls)
        for board, urls in diagnostics["result_urls_by_board"].items()
    }
    diagnostics["resolved_active_jobs"] = len(unique_jobs)
    diagnostics["status"] = (
        "complete"
        if unique_jobs
        else "unavailable"
        if diagnostics["search_errors_by_board"]
        else "no_verified_results"
    )
    return list(unique_jobs.values()), diagnostics


def agent_web_browser_board_discovery(
    client: WebClawClient,
    browser_client: AgentWebBrowserClient,
    search_term: str,
    locations: Iterable[str],
    hours_old: int,
    boards: Iterable[str],
    results_wanted: int,
) -> tuple[list[Job], dict[str, Any]]:
    """Search signed-in boards read-only using bounded title-family queries.

    Search pages and job URLs are deduplicated before detail-page reads. Browser
    allowance failures preserve unresolved candidates for manual review.
    """
    requested_locations = unique_preserving_order(
        normalize_space(location) for location in locations if normalize_space(location)
    )
    requested_boards = unique_preserving_order(
        board for board in boards if board in {"glassdoor", "zip_recruiter"}
    )
    title_queries = requested_title_family_queries(search_term)
    diagnostics: dict[str, Any] = {
        "requested_boards": requested_boards,
        "requested_locations": requested_locations,
        "title_family_queries": title_queries,
        "pages_by_board": {board: [] for board in requested_boards},
        "job_links_by_board": {board: [] for board in requested_boards},
        "job_link_records_by_board": {board: [] for board in requested_boards},
        "resolution_records": [],
        "resolution_errors": [],
        "duplicate_source_urls_avoided": 0,
        "circuit_breakers": {
            board: {"open": False, "reason": "", "retry_in_current_run": False}
            for board in requested_boards
        },
    }
    jobs: list[Job] = []
    source_records: dict[str, dict[str, str]] = {}
    per_page = max(1, min(int(results_wanted), 10))
    for board in requested_boards:
        board_open = False
        for family, family_query in title_queries.items():
            if board_open:
                break
            for location in requested_locations:
                try:
                    result = browser_client.search_job_links(
                        board=board,
                        query=family_query,
                        location=location,
                        hours_old=hours_old,
                        results_wanted=per_page,
                    )
                except AgentWebBrowserError as exc:
                    diagnostics["circuit_breakers"][board] = {
                        "open": True,
                        "reason": str(exc),
                        "retry_in_current_run": False,
                    }
                    board_open = True
                    break
                diagnostics["pages_by_board"][board].append({
                    "title_family": family,
                    "requested_location": location,
                    "search_url": result.search_url,
                    "page_url": result.page_url,
                    "title": result.title,
                    "text_length": result.text_length,
                    "job_links_found": len(result.job_links),
                })
                diagnostics["job_links_by_board"][board].extend(result.job_links)
                link_records = list(getattr(result, "job_link_records", []))
                diagnostics["job_link_records_by_board"][board].extend(
                    {**record, "requested_location": location, "title_family": family}
                    for record in link_records
                    if isinstance(record, dict)
                )
                link_text_by_url = {
                    canonical_url(str(record.get("url") or "")): normalize_space(
                        str(record.get("text") or "")
                    )
                    for record in link_records
                    if isinstance(record, dict) and record.get("url")
                }
                for source_url in result.job_links:
                    canonical_source = canonical_url(source_url)
                    if canonical_source in source_records:
                        diagnostics["duplicate_source_urls_avoided"] += 1
                        continue
                    source_records[canonical_source] = {
                        "url": source_url,
                        "title": link_text_by_url.get(canonical_source, ""),
                        "requested_location": location,
                        "title_family": family,
                        "board": board,
                    }

    for record in source_records.values():
        source_url = record["url"]
        board = record["board"]
        title_evidence = record["title"]
        try:
            job_hint = _discovery_job_hint(
                source_url,
                title_evidence,
                "Unspecified",
                f"agent_web_browser:{board}:{record['title_family']}",
            )
            job, resolution = resolve_employer_application(
                client,
                source_url,
                browser_client=browser_client,
                job_hint=job_hint,
            )
            jobs.append(job)
            diagnostics["resolution_records"].append({
                **resolution,
                "title_family": record["title_family"],
            })
        except WebClawError as exc:
            diagnostics["resolution_errors"].append({
                "board": board,
                "requested_location": record["requested_location"],
                "location": "Unspecified",
                "source_url": source_url,
                "title": title_evidence or "Unresolved recruiting lead",
                "company": "Unknown company",
                "posting_date_evidence": "",
                "title_family": record["title_family"],
                "error": str(exc),
            })

    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        unique_jobs.setdefault(canonical_url(job.url), job)
    diagnostics["job_links_by_board"] = {
        board: unique_preserving_order(urls)
        for board, urls in diagnostics["job_links_by_board"].items()
    }
    diagnostics["browser_search_pages"] = sum(
        len(pages) for pages in diagnostics["pages_by_board"].values()
    )
    diagnostics["job_links_found"] = len(source_records)
    diagnostics["resolved_active_jobs"] = len(unique_jobs)
    usage = getattr(browser_client, "run_diagnostics", None)
    diagnostics["browser_usage"] = usage() if callable(usage) else {}
    open_breakers = sum(
        1 for value in diagnostics["circuit_breakers"].values() if value["open"]
    )
    diagnostics["status"] = (
        "complete"
        if unique_jobs
        else "unavailable"
        if requested_boards and open_breakers == len(requested_boards)
        else "no_verified_results"
    )
    return list(unique_jobs.values()), diagnostics


def direct_ats_discovery(
    client: WebClawClient,
    search_term: str,
    locations: Iterable[str],
    hours_old: int,
    results_wanted: int,
    greenhouse_boards: Iterable[str] = (),
) -> tuple[list[Job], dict[str, Any]]:
    """Run bounded parallel searches by requested title family and ATS family."""
    requested_locations = unique_preserving_order(
        normalize_space(location) for location in locations if normalize_space(location)
    )
    title_groups = _requested_title_groups(search_term)
    search_locations = _expanded_direct_search_locations(requested_locations)
    diagnostics: dict[str, Any] = {
        "requested_locations": requested_locations,
        "title_groups": title_groups,
        "ats_families": list(DIRECT_ATS_SEARCH_GROUPS),
        "search_locations": search_locations,
        "search_concurrency": 4,
        "resolution_concurrency": 4,
        "live_greenhouse": {},
        "queries_by_title_group_and_ats": {},
        "search_errors_by_title_group_and_ats": {},
        "result_urls_by_title_group_and_ats": {},
        "resolution_records_by_title_group_and_ats": {},
        "resolution_errors_by_title_group_and_ats": {},
        # Compatibility aliases retained for existing run summaries.
        "queries_by_group": {},
        "search_errors_by_group": {},
        "result_urls_by_group": {},
        "resolution_records": [],
        "resolution_errors": [],
    }
    location_expression = " OR ".join(f'"{location}"' for location in search_locations)
    days = max(1, (max(1, int(hours_old)) + 23) // 24)
    per_search = max(1, min(int(results_wanted), 10))
    tasks: list[dict[str, Any]] = []
    for title_group, titles in title_groups.items():
        title_expression = " OR ".join(f'"{title}"' for title in titles)
        for ats_family, domains in DIRECT_ATS_SEARCH_GROUPS.items():
            key = f"{title_group}:{ats_family}"
            site_filter = " OR ".join(f"site:{domain}" for domain in domains)
            query = (
                f"({title_expression}) ({location_expression or 'United States'}) "
                f"({site_filter}) (posted OR careers OR apply) past {days} days"
            )
            diagnostics["queries_by_title_group_and_ats"][key] = query
            diagnostics["queries_by_group"][key] = query
            diagnostics["resolution_records_by_title_group_and_ats"][key] = []
            diagnostics["resolution_errors_by_title_group_and_ats"][key] = []
            tasks.append({
                "key": key,
                "title_group": title_group,
                "titles": titles,
                "ats_family": ats_family,
                "domains": domains,
                "query": query,
            })

    def search_one(task: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return task, client.search(
            str(task["query"]), num=per_search, country="us", language="en"
        )

    search_results: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]] = {}
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(tasks)))) as executor:
        futures = {executor.submit(search_one, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            key = str(task["key"])
            try:
                search_results[key] = future.result()
            except WebClawError as exc:
                diagnostics["search_errors_by_title_group_and_ats"][key] = str(exc)
                diagnostics["search_errors_by_group"][key] = str(exc)

    resolution_tasks: dict[str, dict[str, Any]] = {}
    for task in tasks:
        key = str(task["key"])
        _, results = search_results.get(key, (task, []))
        domains = tuple(task["domains"])
        urls = unique_preserving_order(
            canonical_url(str(result.get("link", "")))
            for result in results
            if result.get("link")
            and any(
                _host_matches(_host(str(result.get("link", ""))), domain)
                for domain in domains
            )
            and _is_application_candidate(str(result.get("link", "")))
        )
        result_by_url = {
            canonical_url(str(result.get("link", ""))): result
            for result in results if result.get("link")
        }
        diagnostics["result_urls_by_title_group_and_ats"][key] = urls
        diagnostics["result_urls_by_group"][key] = urls
        for url in urls:
            result = result_by_url.get(url, {})
            title_evidence = normalize_space(str(result.get("title") or ""))
            job_hint = _discovery_job_hint(
                url,
                title_evidence or list(task["titles"])[0],
                "Unspecified",
                f"direct_ats:{task['ats_family']}",
            )
            if url in resolution_tasks:
                diagnostics["resolution_records_by_title_group_and_ats"][key].append({
                    "source_url": url,
                    "resolution": "deduplicated_before_resolution",
                })
                continue
            resolution_tasks[url] = {
                **task,
                "url": url,
                "title_evidence": title_evidence,
                "job_hint": job_hint,
            }

    live_candidates, live_diagnostics = _live_greenhouse_candidates(
        client, greenhouse_boards, title_groups, hours_old
    )
    diagnostics["live_greenhouse"] = live_diagnostics
    for record in live_candidates:
        key = f"{record['title_group']}:greenhouse"
        url = str(record["url"])
        diagnostics["resolution_records_by_title_group_and_ats"].setdefault(key, [])
        diagnostics["resolution_errors_by_title_group_and_ats"].setdefault(key, [])
        diagnostics["result_urls_by_title_group_and_ats"].setdefault(key, [])
        diagnostics["result_urls_by_group"].setdefault(key, [])
        if url not in diagnostics["result_urls_by_title_group_and_ats"][key]:
            diagnostics["result_urls_by_title_group_and_ats"][key].append(url)
        if url not in diagnostics["result_urls_by_group"][key]:
            diagnostics["result_urls_by_group"][key].append(url)
        if url in resolution_tasks:
            diagnostics["resolution_records_by_title_group_and_ats"][key].append({
                "source_url": url,
                "resolution": "deduplicated_live_greenhouse_feed",
            })
            continue
        resolution_tasks[url] = {
            "key": key,
            "title_group": record["title_group"],
            "titles": [record["requested_title"]],
            "ats_family": "greenhouse",
            "url": url,
            "title_evidence": record["title"],
            "greenhouse_updated_at": record["updated_at"],
            "job_hint": _discovery_job_hint(
                url, record["title"], record["location"],
                f"greenhouse_live_feed:{record['board']}",
            ),
        }

    def resolve_one(task: dict[str, Any]) -> tuple[Job, dict[str, Any]]:
        return resolve_employer_application(
            client,
            str(task["url"]),
            job_hint=task["job_hint"],
        )

    jobs: list[Job] = []
    with ThreadPoolExecutor(
        max_workers=min(4, max(1, len(resolution_tasks)))
    ) as executor:
        futures = {
            executor.submit(resolve_one, task): task
            for task in resolution_tasks.values()
        }
        for future in as_completed(futures):
            task = futures[future]
            key = str(task["key"])
            try:
                job, resolution = future.result()
                greenhouse_updated_at = normalize_space(
                    str(task.get("greenhouse_updated_at") or "")
                )
                if greenhouse_updated_at and not job.posted_date:
                    raw = dict(job.raw)
                    raw["verification_provenance"] = {
                        "posted_date": "official_greenhouse_updated_at",
                    }
                    job = replace(job, posted_date=greenhouse_updated_at, raw=raw)
                jobs.append(job)
                record = {
                    **resolution,
                    "title_group": task["title_group"],
                    "ats_family": task["ats_family"],
                }
                diagnostics["resolution_records"].append(record)
                diagnostics["resolution_records_by_title_group_and_ats"][key].append(record)
            except WebClawError as exc:
                hint = task["job_hint"]
                error = {
                    "source_url": task["url"],
                    "title": task["title_evidence"] or list(task["titles"])[0],
                    "company": hint.company,
                    "location": hint.location,
                    "posting_date_evidence": "",
                    "title_group": task["title_group"],
                    "ats_family": task["ats_family"],
                    "error": str(exc),
                }
                diagnostics["resolution_errors"].append(error)
                diagnostics["resolution_errors_by_title_group_and_ats"][key].append(error)

    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        unique_jobs.setdefault(canonical_url(job.url), job)
    diagnostics["unique_source_urls_before_resolution"] = len(resolution_tasks)
    diagnostics["resolved_active_jobs"] = len(unique_jobs)
    diagnostics["status"] = (
        "complete"
        if unique_jobs
        else "unavailable"
        if diagnostics["search_errors_by_title_group_and_ats"]
        else "no_verified_results"
    )
    return list(unique_jobs.values()), diagnostics

def verify_discovered_jobs(
    client: WebClawClient,
    jobs: Iterable[Job],
    concurrency: int = 4,
    browser_client: AgentWebBrowserClient | None = None,
) -> tuple[list[Job], list[dict[str, Any]]]:
    """Live-check every discovered URL and return only currently active postings.

    Verification receipts are deliberately not reused here. A role can close between
    searches, so every Agent A run must create a new live receipt before Agent B scores it.
    """
    jobs_to_verify = list(jobs)
    verified: list[Job] = []
    pending = jobs_to_verify
    errors: list[dict[str, Any]] = []

    def worker(job: Job) -> Job:
        refreshed, _ = resolve_employer_application(
            client,
            job.url,
            browser_client=browser_client,
            job_hint=job,
        )
        if not _same_role(job, refreshed):
            raise WebClawError("live page title/company did not match the discovered role")
        raw = dict(refreshed.raw)
        raw["discovery"] = job.to_dict()
        posted_date = refreshed.posted_date or job.posted_date
        location = refreshed.location
        discovery_provenance = (
            job.raw.get("verification_provenance", {})
            if isinstance(job.raw, dict) else {}
        )
        if normalize_space(location).casefold() in {
            "", "unknown", "unspecified", "not specified", "n/a",
        }:
            location = job.location
        work_mode = refreshed.work_mode
        if normalize_space(work_mode).casefold() in {
            "", "unknown", "unspecified", "not specified", "n/a",
        }:
            work_mode = job.work_mode
        raw["verification_provenance"] = {
            "posted_date": (
                "employer_page"
                if refreshed.posted_date
                else discovery_provenance.get("posted_date", "discovery_board")
            ),
            "location": "employer_page" if location == refreshed.location else "discovery_board",
            "work_mode": "employer_page" if work_mode == refreshed.work_mode else "discovery_board",
        }
        return replace(
            refreshed,
            posted_date=posted_date,
            location=location,
            work_mode=work_mode,
            raw=raw,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(int(concurrency), 8))) as executor:
        futures = {executor.submit(worker, job): job for job in pending}
        for future in as_completed(futures):
            job = futures[future]
            try:
                verified.append(future.result())
            except Exception as exc:
                disposition, category = classify_resolution_failure(str(exc))
                source_urls = list(
                    (job.raw or {}).get("discovery_evidence", {}).get(
                        "source_urls", [job.url]
                    )
                )
                errors.append({
                    "job_id": job.id,
                    "url": job.url,
                    "source_urls": source_urls,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "work_mode": job.work_mode,
                    "posted_date": job.posted_date,
                    "source": job.source,
                    "disposition": disposition,
                    "failure_category": category,
                    "employer_url_found": bool(ats_platform(job.url)),
                    "error": str(exc),
                })
    return verified, errors
