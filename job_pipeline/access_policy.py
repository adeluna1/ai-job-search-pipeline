"""Config-driven access policy: WebClaw hosts, session sites, and access-control routing.

The policy is declarative detection/routing configuration only. When a site
returns an access-control response (HTTP block or human-verification
interstitial), the pipeline stops automated fetching and routes the site to
the user's own authenticated session browser. It never circumvents site
access controls, in line with the project's responsible-use policy.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_POLICY: dict[str, Any] = {
    "webclaw": {"allowed_hosts": "any"},
    "session_sites": {
        "linkedin": {
            "domains": ["linkedin.com"],
            "login_url": "https://www.linkedin.com/login",
        },
        "glassdoor": {
            "domains": ["glassdoor.com"],
            "login_url": "https://www.glassdoor.com/profile/login_input.htm",
        },
        "zip_recruiter": {
            "domains": ["ziprecruiter.com"],
            "login_url": "https://www.ziprecruiter.com/login",
        },
        "indeed": {
            "domains": ["indeed.com"],
            "login_url": "https://secure.indeed.com/auth",
        },
    },
    "access_guard": {
        "detect_status": [400, 401, 403, 429],
        "human_check_markers": [
            "captcha",
            "are you a robot",
            "unusual traffic",
            "verify you are human",
            "security check",
        ],
        "action": "route_to_session_browser",
    },
}


def default_root() -> Path:
    """Return the project root (the folder containing config/ and this package)."""
    return Path(__file__).resolve().parent.parent


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override values onto a copy of the base mapping."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_policy(root: Path | None = None) -> dict[str, Any]:
    """Load config/access_policy.json, falling back to the in-code defaults."""
    path = (root or default_root()) / "config" / "access_policy.json"
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            return _merge(DEFAULT_POLICY, loaded)
    return deepcopy(DEFAULT_POLICY)


def session_sites(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the configured session-site entries keyed by site name."""
    sites = policy.get("session_sites", {})
    return {str(name): value for name, value in sites.items() if isinstance(value, dict)}


def session_site_for_host(host: str, policy: dict[str, Any]) -> str | None:
    """Return the session-site name whose domains match the URL host, if any."""
    normalized = host.casefold()
    for name, entry in session_sites(policy).items():
        domains = entry.get("domains", [])
        if any(
            normalized == str(domain).casefold()
            or normalized.endswith(f".{str(domain).casefold()}")
            for domain in domains
        ):
            return name
    return None


def access_guard_config(policy: dict[str, Any]) -> tuple[list[int], list[str], str]:
    """Return (HTTP statuses to detect, human-verification text markers, routing action)."""
    guard = policy.get("access_guard")
    if not isinstance(guard, dict):
        guard = policy.get("antibot")  # legacy key
    guard = guard if isinstance(guard, dict) else {}
    defaults = DEFAULT_POLICY["access_guard"]
    statuses = [
        int(code)
        for code in guard.get("detect_status", defaults["detect_status"])
        if isinstance(code, int) or (isinstance(code, str) and code.isdigit())
    ]
    markers = [
        str(marker).casefold()
        for marker in guard.get(
            "human_check_markers",
            guard.get("captcha_markers", defaults["human_check_markers"]),  # legacy key
        )
    ]
    action = str(guard.get("action", defaults["action"]))
    return statuses, markers, action


def webclaw_host_allowed(host: str, policy: dict[str, Any]) -> bool:
    """Return whether WebClaw may fetch the host under the configured policy.

    The default policy allows every host ("any"). An explicit host list in
    config/access_policy.json restricts WebClaw to those exact/subdomain hosts.
    """
    webclaw = policy.get("webclaw", {}) if isinstance(policy.get("webclaw"), dict) else {}
    allowed = webclaw.get("allowed_hosts", "any")
    if isinstance(allowed, str):
        return allowed.strip().casefold() == "any"
    normalized = host.casefold()
    return any(
        normalized == str(entry).casefold()
        or normalized.endswith(f".{str(entry).casefold()}")
        for entry in allowed
    )
