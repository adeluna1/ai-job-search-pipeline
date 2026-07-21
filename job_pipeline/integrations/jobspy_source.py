"""JobSpy discovery adapter for Agent A.

The adapter owns every JobSpy-specific assumption. Downstream agents receive
only the pipeline's canonical ``Job`` model, so another discovery repository
can replace JobSpy without changing the A -> B -> C workflow.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Callable, Protocol

from ..jobs import Job, infer_required_years, infer_work_mode
from ..util import canonical_url, normalize_space, stable_id, utc_now


class DiscoveryError(RuntimeError):
    """Raised when an optional discovery provider cannot return usable jobs."""


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
    ) -> list[Job]:
        """Return normalized jobs from one bounded discovery request."""


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


class JobSpySource:
    """Agent A discovery provider backed by speedyapply/JobSpy."""

    name = "jobspy"
    supported_sites = ("linkedin", "indeed", "glassdoor", "zip_recruiter", "google")

    def __init__(self, scraper: Callable[..., Any] | None = None):
        self._scraper = scraper
        self.last_diagnostics: dict[str, Any] = {}

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
    ) -> list[Job]:
        """Run all selected boards in one JobSpy call and normalize the dataframe."""
        selected = [site.casefold() for site in sites]
        invalid = sorted(set(selected) - set(self.supported_sites))
        if invalid:
            raise DiscoveryError("Unsupported JobSpy site(s): " + ", ".join(invalid))
        try:
            result = self._load_scraper()(
                site_name=selected,
                search_term=search_term,
                location=location,
                results_wanted=max(1, min(int(results_wanted), 50)),
                hours_old=max(1, int(hours_old)),
                country_indeed=country,
                linkedin_fetch_description=True,
            )
        except Exception as exc:  # third-party providers expose heterogeneous errors
            raise DiscoveryError(f"JobSpy search failed: {exc}") from exc
        if isinstance(result, list):
            rows = result
        elif hasattr(result, "to_dict"):
            rows = result.to_dict(orient="records")
        else:
            raise DiscoveryError("JobSpy returned an unsupported result type.")
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
        self.last_diagnostics = {
            "provider": self.name,
            "requested_sites": selected,
            "result_counts_by_site": counts,
            "sites_with_results": sites_with_results,
            "sites_without_results": sites_without_results,
            "normalization_errors": errors,
            "fallback_recommended": len(sites_with_results) <= len(selected) / 2,
            "note": (
                "A site with zero records may have no matching roles or may have rejected the request; "
                "review JobSpy logs before selecting a fallback provider."
            ),
        }
        return jobs
