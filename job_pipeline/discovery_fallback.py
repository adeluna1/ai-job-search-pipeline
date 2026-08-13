"""WebClaw fallback discovery, employer-page resolution, and active-role verification."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
import html
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
    "coordination": (
        "recruiting coordinator", "recruitment coordinator",
        "talent acquisition coordinator", "recruiting assistant",
        "recruiting scheduler", "candidate experience coordinator",
        "sourcing coordinator", "university recruiting coordinator",
    ),
    "operations": (
        "recruiting operations coordinator", "talent operations coordinator",
    ),
    "junior_recruiter": (
        "recruiting associate", "associate recruiter", "junior recruiter",
        "recruiter i", "recruiter 1", "talent acquisition specialist",
        "university recruiter",
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


def webclaw_fallback_discovery(
    client: WebClawClient,
    search_term: str,
    location: str,
    hours_old: int,
    boards: Iterable[str],
    results_wanted: int,
    browser_client: AgentWebBrowserClient | None = None,
) -> tuple[list[Job], dict[str, Any]]:
    """Fill missing board coverage through WebClaw and retain only resolved active roles."""
    jobs: list[Job] = []
    diagnostics: dict[str, Any] = {
        "requested_boards": list(boards),
        "queries_by_board": {},
        "search_errors_by_board": {},
        "result_urls_by_board": {},
        "resolution_records": [],
        "resolution_errors": [],
    }
    per_board = max(1, min(int(results_wanted), 10))
    days = max(1, (max(1, int(hours_old)) + 23) // 24)
    for board in diagnostics["requested_boards"]:
        domains = BOARD_DOMAINS.get(board, ())
        site_filter = " OR ".join(f"site:{domain}" for domain in domains)
        board_name = board.replace("_", " ")
        search_expression = (
            search_term
            if " OR " in search_term.upper()
            else f'"{search_term}"'
        )
        query = (
            f'({search_expression}) "{location}" ({site_filter or board_name}) '
            f'("posted" OR "days ago") past {days} days'
        )
        diagnostics["queries_by_board"][board] = query
        try:
            results = client.search(query, num=per_board, country="us", language="en")
        except WebClawError as exc:
            diagnostics["search_errors_by_board"][board] = str(exc)
            continue
        urls = unique_preserving_order(
            canonical_url(str(result.get("link", "")))
            for result in results
            if result.get("link")
        )
        result_by_url = {
            canonical_url(str(result.get("link", ""))): result
            for result in results if result.get("link")
        }
        diagnostics["result_urls_by_board"][board] = urls
        for url in urls:
            result = result_by_url.get(url, {})
            title_evidence = normalize_space(str(result.get("title") or ""))
            job_hint = _discovery_job_hint(
                url, title_evidence, location, f"webclaw_fallback:{board}"
            )
            try:
                job, resolution = resolve_employer_application(
                    client,
                    url,
                    browser_client=browser_client,
                    job_hint=job_hint,
                )
                jobs.append(job)
                diagnostics["resolution_records"].append(resolution)
            except WebClawError as exc:
                diagnostics["resolution_errors"].append({
                    "board": board,
                    "location": location,
                    "source_url": url,
                    "title": title_evidence or "Unresolved recruiting lead",
                    "company": job_hint.company,
                    "posting_date_evidence": "",
                    "error": str(exc),
                })

    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        unique_jobs.setdefault(job.url, job)
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
    """Search signed-in board pages read-only, then resolve employer applications.

    Each board has a run-scoped circuit breaker. A browser access challenge stops
    every remaining location for that board, while an ordinary zero-result page
    remains a valid search outcome.
    """
    requested_locations = unique_preserving_order(
        normalize_space(location) for location in locations if normalize_space(location)
    )
    requested_boards = unique_preserving_order(
        board for board in boards if board in {"glassdoor", "zip_recruiter"}
    )
    diagnostics: dict[str, Any] = {
        "requested_boards": requested_boards,
        "requested_locations": requested_locations,
        "pages_by_board": {board: [] for board in requested_boards},
        "job_links_by_board": {board: [] for board in requested_boards},
        "job_link_records_by_board": {board: [] for board in requested_boards},
        "resolution_records": [],
        "resolution_errors": [],
        "circuit_breakers": {
            board: {"open": False, "reason": "", "retry_in_current_run": False}
            for board in requested_boards
        },
    }
    jobs: list[Job] = []
    seen_source_urls: set[str] = set()
    per_page = max(1, min(int(results_wanted), 10))
    for board in requested_boards:
        for location in requested_locations:
            try:
                result = browser_client.search_job_links(
                    board=board,
                    query=search_term,
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
                break
            diagnostics["pages_by_board"][board].append({
                "location": location,
                "search_url": result.search_url,
                "page_url": result.page_url,
                "title": result.title,
                "text_length": result.text_length,
                "job_links_found": len(result.job_links),
            })
            diagnostics["job_links_by_board"][board].extend(result.job_links)
            link_records = list(getattr(result, "job_link_records", []))
            diagnostics["job_link_records_by_board"][board].extend(
                {**record, "location": location}
                for record in link_records
                if isinstance(record, dict)
            )
            link_text_by_url = {
                canonical_url(str(record.get("url") or "")): normalize_space(str(record.get("text") or ""))
                for record in link_records
                if isinstance(record, dict) and record.get("url")
            }
            for source_url in result.job_links:
                canonical_source = canonical_url(source_url)
                if canonical_source in seen_source_urls:
                    continue
                seen_source_urls.add(canonical_source)
                try:
                    job_hint = _discovery_job_hint(
                        source_url,
                        link_text_by_url.get(canonical_source, ""),
                        location,
                        f"agent_web_browser:{board}",
                    )
                    job, resolution = resolve_employer_application(
                        client,
                        source_url,
                        browser_client=browser_client,
                        job_hint=job_hint,
                    )
                    jobs.append(job)
                    diagnostics["resolution_records"].append(resolution)
                except WebClawError as exc:
                    diagnostics["resolution_errors"].append({
                        "board": board,
                        "location": location,
                        "source_url": source_url,
                        "title": link_text_by_url.get(canonical_source, "") or "Unresolved recruiting lead",
                        "company": "Unknown company",
                        "posting_date_evidence": "",
                        "error": str(exc),
                    })

    unique_jobs: dict[str, Job] = {}
    for job in jobs:
        unique_jobs.setdefault(canonical_url(job.url), job)
    diagnostics["browser_search_pages"] = sum(
        len(pages) for pages in diagnostics["pages_by_board"].values()
    )
    diagnostics["job_links_found"] = len(seen_source_urls)
    diagnostics["resolved_active_jobs"] = len(unique_jobs)
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
) -> tuple[list[Job], dict[str, Any]]:
    """Run bounded parallel searches by requested title family and ATS family."""
    requested_locations = unique_preserving_order(
        normalize_space(location) for location in locations if normalize_space(location)
    )
    title_groups = _requested_title_groups(search_term)
    diagnostics: dict[str, Any] = {
        "requested_locations": requested_locations,
        "title_groups": title_groups,
        "ats_families": list(DIRECT_ATS_SEARCH_GROUPS),
        "search_concurrency": 4,
        "resolution_concurrency": 4,
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
    location_expression = " OR ".join(f'"{location}"' for location in requested_locations)
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
                " | ".join(requested_locations),
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
            "posted_date": "employer_page" if refreshed.posted_date else "discovery_board",
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
