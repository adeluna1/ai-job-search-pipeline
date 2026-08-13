"""Hard geographic eligibility gates for requested job-search locations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .jobs import Job
from .util import normalize_term


BAY_AREA_TERMS = {
    "bay area", "san francisco bay area", "silicon valley", "south bay",
    "san francisco", "south san francisco", "san jose", "oakland", "berkeley",
    "alameda", "emeryville", "daly city", "san mateo", "redwood city",
    "menlo park", "palo alto", "mountain view", "sunnyvale", "santa clara",
    "fremont", "hayward", "walnut creek", "concord", "pleasanton",
    "san ramon", "cupertino", "milpitas", "newark", "union city",
    "foster city", "burlingame", "san bruno", "san carlos", "san rafael",
    "marin",
}

SAN_JOSE_TERMS = {
    "san jose", "south bay", "silicon valley", "santa clara", "sunnyvale",
    "cupertino", "milpitas", "mountain view", "campbell", "los gatos",
}

SACRAMENTO_METRO_TERMS = {
    "sacramento", "roseville", "rocklin", "folsom", "rancho cordova",
}
SOUTH_BAY_TERMS = {
    "san jose", "santa clara", "sunnyvale", "cupertino", "milpitas",
    "mountain view", "campbell", "los gatos",
}
EAST_BAY_TERMS = {
    "oakland", "berkeley", "alameda", "emeryville", "fremont", "hayward",
    "walnut creek", "concord", "pleasanton", "san ramon", "newark",
    "union city",
}
SAN_FRANCISCO_PENINSULA_TERMS = {
    "san francisco", "south san francisco", "daly city", "san mateo",
    "redwood city", "menlo park", "palo alto", "foster city", "burlingame",
    "san bruno", "san carlos",
}

REMOTE_BROAD_TERMS = {
    "united states", "usa", "us", "nationwide", "anywhere",
    "california", "ca",
}


@dataclass(frozen=True)
class GeographyDecision:
    """Explain whether a verified posting is inside the requested search area."""

    eligible: bool
    reason: str


def _contains_term(text: str, terms: Iterable[str]) -> bool:
    normalized = f" {normalize_term(text)} "
    return any(f" {normalize_term(term)} " in normalized for term in terms)


def _requested_terms(locations: Iterable[str]) -> set[str]:
    terms: set[str] = set()
    for location in locations:
        normalized = normalize_term(location)
        if not normalized:
            continue
        if not normalized.startswith("remote "):
            terms.add(normalized)
        if "bay area" in normalized or "san francisco bay" in normalized:
            terms.update(BAY_AREA_TERMS)
        if "san jose" in normalized or "south bay" in normalized:
            terms.update(SAN_JOSE_TERMS)
            terms.update(SOUTH_BAY_TERMS)
        if "oakland" in normalized or "east bay" in normalized:
            terms.update(EAST_BAY_TERMS)
        if "san francisco" in normalized or "peninsula" in normalized:
            terms.update(SAN_FRANCISCO_PENINSULA_TERMS)
        if "sacramento" in normalized:
            terms.update(SACRAMENTO_METRO_TERMS)
        if normalized in {"united states", "usa", "us"}:
            terms.update(REMOTE_BROAD_TERMS)
        if normalized == "california":
            terms.update({"california", "ca"})
    return terms


def evaluate_geography(job: Job, requested_locations: Iterable[str]) -> GeographyDecision:
    """Apply a conservative location gate after employer-page verification.

    Onsite and hybrid jobs must name an assigned city/metro in the requested scope.
    Remote jobs must either name that scope or be available broadly in the US or
    California. Unknown, unrelated, or state-restricted remote locations fail.
    """
    locations = [item for item in requested_locations if normalize_term(item)]
    if not locations:
        return GeographyDecision(False, "No requested location was supplied.")

    terms = _requested_terms(locations)
    location_text = job.location or ""
    work_mode = normalize_term(job.work_mode)
    raw_text = " ".join(
        str(value)
        for key, value in job.raw.items()
        if key in {"location", "job_location", "applicant_location_requirements"}
    )
    evidence = f"{location_text} {raw_text}"
    if not normalize_term(evidence) or normalize_term(location_text) in {
        "unspecified", "unknown", "n a", "not specified",
    }:
        return GeographyDecision(False, "Posting location is unknown or unspecified.")

    if terms and _contains_term(evidence, terms):
        return GeographyDecision(True, "Posting names a requested city or metro.")

    remote = "remote" in work_mode or _contains_term(evidence, {"remote"})
    normalized_requests = {normalize_term(item) for item in locations}
    remote_us_requested = bool(normalized_requests.intersection({
        "remote united states", "remote us", "remote usa",
    }))
    remote_ca_requested = bool(normalized_requests.intersection({
        "remote california", "remote ca",
    }))
    non_remote_scope_requested = any(
        not value.startswith("remote ") for value in normalized_requests
    )
    if remote and remote_us_requested and _contains_term(
        evidence, {"united states", "usa", "us", "nationwide", "anywhere"}
    ):
        return GeographyDecision(True, "Remote posting explicitly allows nationwide US work.")
    if remote and remote_ca_requested and _contains_term(evidence, {"california", "ca"}):
        return GeographyDecision(True, "Remote posting explicitly allows California work.")
    if remote and non_remote_scope_requested and _contains_term(evidence, REMOTE_BROAD_TERMS):
        return GeographyDecision(True, "Remote posting is broadly available in the US or California.")

    requested = ", ".join(locations)
    return GeographyDecision(
        False,
        f"Posting location '{job.location}' is outside requested scope: {requested}.",
    )


def partition_by_geography(
    jobs: Iterable[Job], requested_locations: Iterable[str]
) -> tuple[list[Job], list[tuple[Job, GeographyDecision]]]:
    """Split jobs into geographically eligible and rejected collections."""
    eligible: list[Job] = []
    rejected: list[tuple[Job, GeographyDecision]] = []
    locations = list(requested_locations)
    for job in jobs:
        decision = evaluate_geography(job, locations)
        if decision.eligible:
            eligible.append(job)
        else:
            rejected.append((job, decision))
    return eligible, rejected
