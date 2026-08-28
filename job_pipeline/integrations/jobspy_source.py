"""JobSpy discovery adapter for Agent A.

The adapter owns every JobSpy-specific assumption. Downstream agents receive
only the pipeline's canonical ``Job`` model, so another discovery repository
can replace JobSpy without changing the A -> B -> C workflow.
"""

from __future__ import annotations

import math
import logging
import queue
import re
import threading
from datetime import date, datetime
from typing import Any, Callable, Protocol

from ..access_policy import access_guard_config, load_policy
from ..jobs import Job, infer_required_years, infer_work_mode
from ..util import canonical_url, normalize_space, stable_id, utc_now


class DiscoveryError(RuntimeError):
    """Raised when an optional discovery provider cannot return usable jobs."""


class _BoardLogCapture(logging.Handler):
    """Capture one JobSpy board's swallowed HTTP errors for run diagnostics."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _board_logger_name(site: str) -> str:
    """Map canonical JobSpy site names to the loggers used by its scrapers."""
    names = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "glassdoor": "Glassdoor",
        "zip_recruiter": "ZipRecruiter",
        "google": "Google",
    }
    return f"JobSpy:{names.get(site, site)}"


def _http_block_status(
    messages: list[str],
    detect_status: list[int],
    human_check_markers: list[str],
) -> str | None:
    """Classify a configured HTTP block or human-verification interstitial."""
    text = " ".join(messages)
    lowered = text.casefold()
    if any(marker.casefold() in lowered for marker in human_check_markers):
        return "blocked_human_check"
    codes = "|".join(re.escape(str(code)) for code in detect_status)
    if not codes:
        return None
    match = re.search(
        rf"(?:status\s+code|response|http)\D{{0,12}}({codes})\b",
        text,
        re.IGNORECASE,
    )
    return f"blocked_{match.group(1)}" if match else None


class DiscoveryProvider(Protocol):
    """Replaceable boundary implemented by job-board discovery integrations."""

    name: str

    def search(
        self,
        search_term: str,
        location: str,
        hours_old: int,
        results_wanted: int,
        sites: list[str],
        country: str = "USA",
        glassdoor_location: str | None = None,
    ) -> list[Job]:
        """Return normalized jobs from one bounded, provider-safe search operation."""


def _clean(value: Any) -> str:
    """Convert pandas/numpy-style missing values and scalar values safely."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = normalize_space(str(value))
    return "" if text.casefold() in {"nan", "nat", "<na>", "none"} else text


def _date_text(value: Any) -> str:
    """Serialize Python and pandas date-like values without requiring pandas."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return str(isoformat())
        except (TypeError, ValueError):
            pass
    return _clean(value)


def _json_safe(value: Any) -> Any:
    """Reduce third-party dataframe values to JSON-compatible primitives."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return _clean(value)


def _salary_text(row: dict[str, Any]) -> str:
    """Format JobSpy's normalized salary columns for the canonical model."""
    minimum = _clean(row.get("min_amount"))
    maximum = _clean(row.get("max_amount"))
    currency = _clean(row.get("currency"))
    interval = _clean(row.get("interval"))
    if minimum and maximum:
        amount = f"{minimum}-{maximum}"
    else:
        amount = minimum or maximum
    return normalize_space(" ".join(part for part in (currency, amount, interval) if part))


def normalize_jobspy_row(row: dict[str, Any]) -> Job:
    """Convert one JobSpy dataframe record into the pipeline's canonical Job."""
    board_url = _clean(row.get("job_url"))
    direct_url = _clean(row.get("job_url_direct"))
    raw_url = direct_url or board_url
    if not raw_url:
        raise DiscoveryError("JobSpy record did not contain a job URL.")
    clean_url = canonical_url(raw_url)
    description = _clean(row.get("description"))
    location = _clean(row.get("location")) or "Unspecified"
    site = _clean(row.get("site")) or "unknown"
    is_remote_value = row.get("is_remote")
    is_remote = is_remote_value is True or _clean(is_remote_value).casefold() == "true"
    if is_remote and "remote" not in location.casefold():
        location = f"Remote; {location}" if location != "Unspecified" else "Remote"
    raw = {str(key): _json_safe(value) for key, value in row.items()}
    raw["jobspy_board_url"] = board_url
    raw["jobspy_direct_url"] = direct_url
    return Job(
        id=stable_id(clean_url),
        url=clean_url,
        title=_clean(row.get("title")) or "Untitled role",
        company=_clean(row.get("company")) or "Unknown company",
        location=location,
        work_mode="remote" if is_remote else infer_work_mode(location, description),
        employment_type=_clean(row.get("job_type")),
        posted_date=_date_text(row.get("date_posted")),
        salary=_salary_text(row),
        description=description,
        source=f"jobspy:{site.casefold()}",
        required_years=infer_required_years(description),
        discovered_at=utc_now(),
        raw=raw,
    )


def normalize_us_city_location(location: str) -> str:
    """Return a direct Bay Area city with the state name written in full."""
    value = normalize_space(location)
    aliases = {
        "bay area": "San Francisco, California",
        "san francisco bay area": "San Francisco, California",
        "sf bay area": "San Francisco, California",
        "silicon valley": "San Jose, California",
        "san francisco": "San Francisco, California",
        "san francisco, ca": "San Francisco, California",
        "san francisco california": "San Francisco, California",
        "san francisco, california": "San Francisco, California",
        "san jose": "San Jose, California",
        "san jose, ca": "San Jose, California",
        "san jose california": "San Jose, California",
        "san jose, california": "San Jose, California",
    }
    return aliases.get(value.casefold(), value)


def normalize_glassdoor_location(location: str) -> str:
    """Translate broad Bay Area labels into direct Glassdoor city searches."""
    return normalize_us_city_location(location)


class JobSpySource:
    """Agent A discovery provider backed by speedyapply/JobSpy."""

    name = "jobspy"
    supported_sites = ("linkedin", "indeed", "glassdoor", "zip_recruiter", "google")

    def __init__(
        self,
        scraper: Callable[..., Any] | None = None,
        *,
        board_timeout_seconds: float = 45,
    ):
        self._scraper = scraper
        self.board_timeout_seconds = max(0.1, float(board_timeout_seconds))
        self.last_diagnostics: dict[str, Any] = {}
        policy = load_policy()
        self._guard_statuses, self._guard_markers, self._guard_action = (
            access_guard_config(policy)
        )

    def _scrape_with_timeout(
        self, scraper: Callable[..., Any], options: dict[str, Any]
    ) -> Any:
        """Run one provider call in a daemon thread with a hard wall-clock limit."""
        outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                outcome.put(("result", scraper(**options)))
            except BaseException as exc:
                outcome.put(("error", exc))

        worker = threading.Thread(
            target=invoke,
            name=f"jobspy-{options['site_name'][0]}",
            daemon=True,
        )
        worker.start()
        try:
            kind, value = outcome.get(timeout=self.board_timeout_seconds)
        except queue.Empty as exc:
            site = options["site_name"][0]
            raise TimeoutError(
                f"{site} exceeded the {self.board_timeout_seconds:g}s board timeout"
            ) from exc
        if kind == "error":
            raise value
        return value

    def _load_scraper(self) -> Callable[..., Any]:
        """Import JobSpy lazily so the base CLI remains dependency-free."""
        if self._scraper is not None:
            return self._scraper
        try:
            from jobspy import scrape_jobs
        except ImportError as exc:
            raise DiscoveryError(
                "JobSpy is not installed. Run scripts/install-agent-integrations.ps1 -JobSpy."
            ) from exc
        return scrape_jobs

    def search(
        self,
        search_term: str,
        location: str,
        hours_old: int,
        results_wanted: int,
        sites: list[str],
        country: str = "USA",
        glassdoor_location: str | None = None,
    ) -> list[Job]:
        """Run each board with only its supported location parameters."""
        selected = [site.casefold() for site in sites]
        invalid = sorted(set(selected) - set(self.supported_sites))
        if invalid:
            raise DiscoveryError("Unsupported JobSpy site(s): " + ", ".join(invalid))
        query_locations: dict[str, str] = {}
        calls: list[tuple[str, str]] = []
        for site in selected:
            requested_location = (
                glassdoor_location if site == "glassdoor" and glassdoor_location else location
            )
            call_location = (
                normalize_us_city_location(requested_location)
                if site in {"indeed", "glassdoor", "zip_recruiter"}
                else normalize_space(requested_location)
            )
            query_locations[site] = call_location
            calls.append((site, call_location))

        rows: list[dict[str, Any]] = []
        provider_errors: list[str] = []
        board_logs: dict[str, list[str]] = {}
        board_status: dict[str, str] = {}
        attempts_by_site: dict[str, int] = {}
        scraper = self._load_scraper()
        for call_site, call_location in calls:
            attempts_by_site[call_site] = 1
            scraper_options = {
                "site_name": [call_site],
                "search_term": search_term,
                "location": call_location,
                "results_wanted": max(1, min(int(results_wanted), 50)),
                "hours_old": max(1, int(hours_old)),
                "linkedin_fetch_description": True,
            }
            if call_site in {"indeed", "glassdoor"}:
                scraper_options["country_indeed"] = country
            capture = _BoardLogCapture()
            board_logger = logging.getLogger(_board_logger_name(call_site))
            board_logger.addHandler(capture)
            try:
                result = self._scrape_with_timeout(scraper, scraper_options)
            except TimeoutError as exc:
                provider_errors.append(f"{call_site}: {exc}")
                board_status[call_site] = "timed_out"
                continue
            except Exception as exc:  # third-party providers expose heterogeneous errors
                provider_errors.append(f"{call_site}: {exc}")
                board_status[call_site] = "error"
                continue
            finally:
                board_logger.removeHandler(capture)
                board_logs[call_site] = capture.messages
            if isinstance(result, list):
                call_rows = result
            elif hasattr(result, "to_dict"):
                call_rows = result.to_dict(orient="records")
            else:
                provider_errors.append(
                    f"{call_site}: JobSpy returned an unsupported result type"
                )
                board_status[call_site] = "error"
                continue
            rows.extend(call_rows)
            blocked_status = _http_block_status(
                capture.messages,
                self._guard_statuses,
                self._guard_markers,
            )
            if blocked_status:
                board_status[call_site] = blocked_status
            elif call_rows:
                board_status[call_site] = "ok"
            else:
                board_status[call_site] = "empty"
        jobs: list[Job] = []
        errors: list[str] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"row {index} was not an object")
                continue
            try:
                jobs.append(normalize_jobspy_row(row))
            except DiscoveryError as exc:
                errors.append(f"row {index}: {exc}")
        counts: dict[str, int] = {}
        for job in jobs:
            site = job.source.removeprefix("jobspy:")
            counts[site] = counts.get(site, 0) + 1
        sites_with_results = [site for site in selected if counts.get(site, 0) > 0]
        sites_without_results = [site for site in selected if counts.get(site, 0) == 0]
        for site in selected:
            if counts.get(site, 0) > 0:
                board_status[site] = "ok"
            elif site not in board_status:
                board_status[site] = "error"
        blocked_sites = [
            site
            for site, status in board_status.items()
            if status.startswith("blocked_") or status == "timed_out"
        ]
        self.last_diagnostics = {
            "provider": self.name,
            "requested_sites": selected,
            "query_locations_by_site": query_locations,
            "parameter_strategy_by_site": {
                site: (
                    "country_indeed_plus_full_city_state"
                    if site in {"indeed", "glassdoor"}
                    else "location_only_full_city_state"
                    if site == "zip_recruiter"
                    else "provider_default"
                )
                for site in selected
            },
            "result_counts_by_site": counts,
            "attempts_by_site": attempts_by_site,
            "status_by_site": board_status,
            "sites_with_results": sites_with_results,
            "sites_without_results": sites_without_results,
            "blocked_sites": blocked_sites,
            "access_guard": {
                "detect_status": self._guard_statuses,
                "human_check_markers": self._guard_markers,
                "action": self._guard_action,
                "policy": "detect, classify, and route to the user's session browser; "
                "circumventing site access controls is out of scope",
            },
            "circuit_breakers": {
                site: {
                    "open": site in blocked_sites,
                    "reason": board_status[site] if site in blocked_sites else "",
                    "action": self._guard_action if site in blocked_sites else "",
                    "retry_in_current_run": False if site in blocked_sites else None,
                }
                for site in selected
            },
            "captured_board_logs": {
                site: messages[-5:] for site, messages in board_logs.items() if messages
            },
            "provider_errors": provider_errors,
            "normalization_errors": errors,
            "fallback_sites": sites_without_results,
            "fallback_recommended": bool(sites_without_results),
            "note": (
                "Every board call has a hard wall-clock timeout. Configured access-control "
                "responses and human-verification markers open that board's circuit breaker "
                "for the current run and route it to the user's session browser. Empty, "
                "blocked, timed-out, and errored boards are eligible for fallback."
            ),
        }
        return jobs
