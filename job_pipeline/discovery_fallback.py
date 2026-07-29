"""WebClaw fallback discovery, employer-page resolution, and active-role verification."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
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
    "glassdoor": ("glassdoor.com",),
    "zip_recruiter": ("ziprecruiter.com",),
    "linkedin": ("linkedin.com",),
    "indeed": ("indeed.com",),
}
DIRECT_ATS_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "icims.com",
    "jobvite.com",
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


def _is_board_url(url: str) -> bool:
    host = _host(url)
    return any(domain in host for domains in BOARD_DOMAINS.values() for domain in domains)


def _board_for_url(url: str) -> str | None:
    """Return the canonical supported board name for an aggregator URL."""
    host = _host(url)
    for board, domains in BOARD_DOMAINS.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return board
    return None


def _is_application_candidate(url: str) -> bool:
    """Keep plausible employer/ATS job URLs and reject board/social navigation."""
    parts = urlsplit(url)
    host = parts.netloc.casefold()
    path = parts.path.casefold()
    if parts.scheme not in {"http", "https"} or not host:
        return False
    if _is_board_url(url) or any(domain in host for domain in NON_APPLICATION_DOMAINS):
        return False
    return (
        any(domain in host for domain in DIRECT_ATS_DOMAINS)
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
    direct_rank = 0 if any(domain in host for domain in DIRECT_ATS_DOMAINS) else 1
    return direct_rank, len(url)


def _identity_tokens(value: str) -> set[str]:
    ignored = {"the", "and", "inc", "llc", "corp", "company", "co", "job", "jobs"}
    return {
        token
        for token in normalize_space(value).casefold().replace("-", " ").split()
        if len(token) > 2 and token not in ignored
    }


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


def _mark_verified(job: Job, source_url: str, resolution: str) -> Job:
    raw = dict(job.raw)
    raw["verification"] = {
        "active": True,
        "verified_at": utc_now(),
        "verified_by": "webclaw",
        "source_url": source_url,
        "resolved_url": job.url,
        "resolution": resolution,
    }
    source = job.source
    if "webclaw_verified" not in source:
        source = f"{source}; webclaw_verified"
    return replace(job, source=source, raw=raw)


def is_webclaw_verified(job: Job) -> bool:
    """Return whether the canonical job carries a successful live verification receipt."""
    verification = job.raw.get("verification", {}) if isinstance(job.raw, dict) else {}
    return verification.get("active") is True and verification.get("verified_by") == "webclaw"


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
            hinted_title = (
                f"{job_hint.title} | {job_hint.company}"
                if job_hint is not None
                else page.title
            )
            source_payload = {
                "metadata": {"title": hinted_title},
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
            hinted_title = (
                f"{job_hint.title} | {job_hint.company}"
                if job_hint is not None
                else page.title
            )
            source_payload = {
                "metadata": {"title": hinted_title},
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
            return _mark_verified(candidate_job, source_url, "employer_application_page"), {
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
        verified = _mark_verified(source_job, source_url, "source_is_employer_page")
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
        query = (
            f'"{search_term}" "{location}" ({site_filter or board_name}) '
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
    """Live-check discovered URLs and return only active WebClaw-verified postings."""
    jobs_to_verify = list(jobs)
    verified: list[Job] = [job for job in jobs_to_verify if is_webclaw_verified(job)]
    pending = [job for job in jobs_to_verify if not is_webclaw_verified(job)]
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
        return replace(refreshed, raw=raw)

    with ThreadPoolExecutor(max_workers=max(1, min(int(concurrency), 8))) as executor:
        futures = {executor.submit(worker, job): job for job in pending}
        for future in as_completed(futures):
            job = futures[future]
            try:
                verified.append(future.result())
            except Exception as exc:
                errors.append({"job_id": job.id, "url": job.url, "error": str(exc)})
    return verified, errors
