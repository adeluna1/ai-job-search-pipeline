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
from .jobs import Job, normalize_webclaw_job, validate_job
from .util import canonical_url, normalize_space, unique_preserving_order, utc_now
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
    "applytojob.com",
    "paylocity.com",
)
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
    company_slug = "".join(sorted(company_tokens))
    company_match = bool(
        registrant
        and (
            registrant in company_tokens
            or registrant.replace("-", "") == company_slug
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
    if requested_job_path and not final_job_path:
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
    if not candidates and source_valid and _is_board_url(source_url):
        used_resolution_search = True
        query = f'"{source_job.title}" "{source_job.company}" (jobs OR careers OR apply)'
        for result in client.search(query, num=search_limit, country="us", language="en"):
            url = canonical_url(str(result.get("link", "")))
            if _is_application_candidate(url):
                candidates.append(url)
        candidates = unique_preserving_order(candidates)
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
                "resolved_url": candidate_url,
                "resolution": "employer_application_page",
                "source_reader": source_reader,
                "used_resolution_search": used_resolution_search,
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
        diagnostics["result_urls_by_board"][board] = urls
        for url in urls:
            try:
                job, resolution = resolve_employer_application(
                    client,
                    url,
                    browser_client=browser_client,
                )
                jobs.append(job)
                diagnostics["resolution_records"].append(resolution)
            except WebClawError as exc:
                diagnostics["resolution_errors"].append({"source_url": url, "error": str(exc)})

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


def verify_discovered_jobs(
    client: WebClawClient,
    jobs: Iterable[Job],
    concurrency: int = 4,
    browser_client: AgentWebBrowserClient | None = None,
) -> tuple[list[Job], list[dict[str, str]]]:
    """Live-check every discovered URL and return only currently active postings.

    Verification receipts are deliberately not reused here. A role can close between
    searches, so every Agent A run must create a new live receipt before Agent B scores it.
    """
    jobs_to_verify = list(jobs)
    verified: list[Job] = []
    pending = jobs_to_verify
    errors: list[dict[str, str]] = []

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
                errors.append({"job_id": job.id, "url": job.url, "error": str(exc)})
    return verified, errors
