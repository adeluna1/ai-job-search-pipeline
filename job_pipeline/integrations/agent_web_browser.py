"""Read-only adapter for BarnsL/agent-web-browser's authenticated loopback API."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlsplit, urlunsplit


class AgentWebBrowserError(RuntimeError):
    """Raised when the local Agent Web Browser bridge is unsafe or unavailable."""


Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str]], dict[str, Any]]


BOARD_DOMAINS = {
    "glassdoor": ("glassdoor.com",),
    "zip_recruiter": ("ziprecruiter.com",),
}
BOARD_PLATFORMS = {
    "glassdoor": "glassdoor",
    "zip_recruiter": "ziprecruiter",
}
UNSAFE_ENVIRONMENT_FLAGS = (
    "SMAB_ALLOW_ARBITRARY_NAVIGATION",
    "SMAB_UNSAFE_TOOLS_ENABLED",
    "SMAB_EXTENSION_MUTATION_ENABLED",
    "SMAB_ALLOW_WRITES",
)


@dataclass
class AgentWebBrowserPage:
    """Sanitized visible page text returned by the local managed browser."""

    url: str
    title: str
    platform: str
    text: str
    text_length: int


@dataclass
class AgentWebBrowserSearchResult:
    """Read-only links observed on one signed-in first-party board search page."""

    board: str
    query: str
    location: str
    search_url: str
    page_url: str
    title: str
    text_length: int
    job_links: list[str]
    job_link_records: list[dict[str, str]] = field(default_factory=list)


class AgentWebBrowserClient:
    """Use only safe navigation/read routes from the AWB loopback bridge."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7896",
        token: str | None = None,
        token_path: Path | None = None,
        timeout: float = 15.0,
        transport: Transport | None = None,
    ):
        parts = urlsplit(base_url.rstrip("/"))
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "localhost"}
            or (parts.port or 80) != 7896
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise AgentWebBrowserError(
                "Agent Web Browser must use its loopback endpoint http://127.0.0.1:7896."
            )
        self.base_url = f"http://{parts.hostname}:7896"
        self._token = token
        self._token_path = token_path
        self.timeout = max(0.5, min(float(timeout), 30.0))
        self._transport = transport or self._default_transport
        self._session_lock = threading.Lock()
        self._page_cache: dict[tuple[str, str], AgentWebBrowserPage] = {}
        self._search_cache: dict[tuple[str, str, int], AgentWebBrowserSearchResult] = {}
        self._logical_page_reads = 0
        self._duplicate_reads_avoided = 0
        self._budget_exhausted = False
        self._budget_error = ""
        self.assert_safe_mode()

    @staticmethod
    def assert_safe_mode() -> None:
        """Refuse integration when any upstream diagnostic/write gate is enabled."""
        active = [
            name
            for name in UNSAFE_ENVIRONMENT_FLAGS
            if os.environ.get(name, "").strip().casefold() in {"1", "true", "yes", "on"}
        ]
        if active:
            raise AgentWebBrowserError(
                "Agent Web Browser integration requires safe read-only mode; unset: "
                + ", ".join(active)
            )

    @staticmethod
    def default_token_path() -> Path:
        """Resolve the token path implemented by the reviewed upstream source."""
        configured = os.environ.get("SMAB_DATA_DIR", "").strip()
        if configured:
            return Path(configured) / "api-token"
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise AgentWebBrowserError("LOCALAPPDATA is unavailable for the AWB token.")
        return Path(local_app_data) / "agent-web-browser" / "api-token"

    def _load_token(self) -> str:
        """Load the token without including it in diagnostics or error messages."""
        token = (self._token or os.environ.get("SMAB_API_TOKEN", "")).strip()
        path = self._token_path or self.default_token_path()
        if not token and path.exists():
            token = path.read_text(encoding="utf-8").strip()
        if not (
            32 <= len(token) <= 256
            and all(
                character.isascii() and (character.isalnum() or character in "-_")
                for character in token
            )
        ):
            raise AgentWebBrowserError(
                "Agent Web Browser API token is missing or invalid. Start AWB once to create it."
            )
        return token

    def _default_transport(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request_headers = dict(headers)
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AgentWebBrowserError(
                f"Agent Web Browser returned HTTP {exc.code} for {path}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AgentWebBrowserError(
                "Agent Web Browser is not reachable at http://127.0.0.1:7896."
            ) from exc
        except json.JSONDecodeError as exc:
            raise AgentWebBrowserError(
                f"Agent Web Browser returned invalid JSON for {path}."
            ) from exc
        if not isinstance(payload, dict):
            raise AgentWebBrowserError(
                f"Agent Web Browser returned an unexpected response for {path}."
            )
        return payload

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._load_token()}"
        payload = self._transport(method, path, body, headers)
        if payload.get("ok") is False:
            message = str(payload.get("error") or "request was rejected")
            raise AgentWebBrowserError(f"Agent Web Browser {path}: {message}")
        return payload

    def health(self) -> dict[str, Any]:
        """Return the minimal unauthenticated health response."""
        return self._request("GET", "/health", authenticated=False)

    def available(self) -> bool:
        """Return bridge availability without raising on a normal stopped state."""
        try:
            return self.health().get("ok") is True
        except AgentWebBrowserError:
            return False

    def status(self) -> dict[str, Any]:
        """Return protected tab and active-platform status."""
        return self._request("GET", "/status")

    def platforms(self) -> list[dict[str, Any]]:
        """Return reviewed platform metadata from the bridge."""
        payload = self._request("GET", "/platforms")
        values = payload.get("platforms", [])
        return [value for value in values if isinstance(value, dict)]

    def show_window(self) -> None:
        """Show the managed browser for human login, consent, or verification."""
        self._request("POST", "/window/show", {})

    @staticmethod
    def _validate_board_url(url: str, board: str) -> str:
        """Restrict automated navigation to exact Glassdoor/ZipRecruiter HTTPS hosts."""
        if board not in BOARD_DOMAINS:
            raise AgentWebBrowserError(f"Unsupported AWB job board: {board}")
        parts = urlsplit(url)
        host = (parts.hostname or "").casefold()
        allowed = any(
            host == domain or host.endswith(f".{domain}")
            for domain in BOARD_DOMAINS[board]
        )
        if (
            parts.scheme != "https"
            or not allowed
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            raise AgentWebBrowserError(
                f"AWB navigation requires an exact first-party HTTPS {board} URL."
            )
        return url

    @staticmethod
    def _result(payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result", payload)
        return result if isinstance(result, dict) else {}

    @staticmethod
    def build_search_url(
        board: str,
        query: str,
        location: str,
        hours_old: int,
    ) -> str:
        """Construct one reviewed first-party board URL without form interaction."""
        if board not in BOARD_DOMAINS:
            raise AgentWebBrowserError(f"Unsupported AWB job board: {board}")
        clean_query = " ".join(str(query).split())
        clean_location = " ".join(str(location).split())
        if not clean_query or not clean_location:
            raise AgentWebBrowserError("AWB board search requires query and location text.")
        if len(clean_query) > 1600 or len(clean_location) > 200:
            raise AgentWebBrowserError("AWB board search query or location is too long.")
        days = max(1, min(30, (max(1, int(hours_old)) + 23) // 24))
        if board == "glassdoor":
            parameters = {
                "sc.keyword": clean_query,
                "locKeyword": clean_location,
                "fromAge": str(days),
            }
            return "https://www.glassdoor.com/Job/jobs.htm?" + urlencode(parameters)
        # ZipRecruiter's interactive /jobs-search page renders cards without
        # job-link anchors. Its server-rendered /Jobs category route exposes
        # first-party detail links, so use one bounded primary term there.
        quoted_terms = re.findall(r'"([^"\r\n]+)"', clean_query)
        primary_term = (
            quoted_terms[0]
            if " OR " in clean_query.upper() and quoted_terms
            else clean_query.strip('"() ')
        )
        title_slug = re.sub(r"[^A-Za-z0-9]+", "-", primary_term).strip("-")
        location_value = re.sub(
            r"(?i),?\s+California$", ",CA", clean_location
        )
        location_slug = re.sub(r"\s+", "-", location_value).strip("-")
        if not title_slug or not location_slug:
            raise AgentWebBrowserError("ZipRecruiter search path could not be constructed.")
        return (
            "https://www.ziprecruiter.com/Jobs/"
            + quote(title_slug, safe="-")
            + "/-in-"
            + quote(location_slug, safe="-")
            + "?"
            + urlencode({"days": str(days)})
        )

    @staticmethod
    def _is_board_job_url(url: str, board: str) -> bool:
        """Reject navigation/search/category anchors and retain exact job-detail shapes."""
        AgentWebBrowserClient._validate_board_url(url, board)
        parts = urlsplit(url)
        path = parts.path.casefold()
        query_keys = {key.casefold() for key in parse_qs(parts.query)}
        if board == "glassdoor":
            return "/job-listing/" in path or bool(
                {"jl", "joblistingid"}.intersection(query_keys)
            )
        segments = [segment.casefold() for segment in parts.path.split("/") if segment]
        return (
            bool({"jid", "lvk"}.intersection(query_keys))
            or (len(segments) >= 3 and segments[0] == "c" and segments[2] == "job")
            or (len(segments) >= 3 and segments[0] == "jobs")
        )

    @staticmethod
    def _sanitize_board_job_url(url: str, board: str) -> str:
        """Remove board tracking/account tokens while preserving listing identity."""
        AgentWebBrowserClient._validate_board_url(url, board)
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=False)
        if board == "glassdoor":
            allowed = {"jl", "joblistingid"}
        elif any(key.casefold() == "lvk" for key, _ in pairs):
            allowed = {"search", "location", "days", "lvk"}
        else:
            allowed = {"jid"}
        clean_query = urlencode([
            (key, value)
            for key, value in pairs
            if key.casefold() in allowed
        ])
        return urlunsplit(("https", parts.netloc.casefold(), parts.path, clean_query, ""))

    @staticmethod
    def _board_job_key(url: str, board: str) -> str:
        """Collapse alternate board URLs that identify the same listing."""
        query = {
            key.casefold(): values
            for key, values in parse_qs(urlsplit(url).query).items()
        }
        identifiers = (
            ("jl", "joblistingid")
            if board == "glassdoor"
            else ("jid", "lvk")
        )
        for identifier in identifiers:
            values = query.get(identifier, [])
            if values and values[0]:
                return f"{board}:{values[0]}"
        return url

    def _record_read_error(self, exc: Exception) -> None:
        """Track bridge allowance failures without changing candidate disposition."""
        message = str(exc)
        normalized = message.casefold()
        if any(marker in normalized for marker in (
            "hourly", "allowance", "read limit", "budget exhausted", "too many requests",
        )):
            self._budget_exhausted = True
            self._budget_error = message

    def run_diagnostics(self) -> dict[str, Any]:
        """Return run-scoped logical read/cache usage without exposing credentials."""
        return {
            "logical_page_reads": self._logical_page_reads,
            "unique_page_cache_entries": len(self._page_cache),
            "unique_search_cache_entries": len(self._search_cache),
            "duplicate_browser_requests_avoided": self._duplicate_reads_avoided,
            "budget_exhausted": self._budget_exhausted,
            "budget_error": self._budget_error,
            "read_only": True,
        }

    def search_job_links(
        self,
        board: str,
        query: str,
        location: str,
        hours_old: int,
        results_wanted: int = 10,
        poll_attempts: int = 24,
        poll_delay: float = 0.75,
    ) -> AgentWebBrowserSearchResult:
        """Navigate once per unique search URL and cache the read-only result."""
        search_url = self.build_search_url(board, query, location, hours_old)
        limit = max(1, min(int(results_wanted), 50))
        cache_key = (board, search_url, limit)
        with self._session_lock:
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                self._duplicate_reads_avoided += 1
                return cached
            try:
                page = self._read_job_page_unlocked(
                    search_url,
                    board,
                    poll_attempts=poll_attempts,
                    poll_delay=poll_delay,
                )
                link_payload = self._result(self._request("GET", "/page/job-links"))
            except AgentWebBrowserError as exc:
                self._record_read_error(exc)
                raise
            self._logical_page_reads += 1
        if link_payload.get("blocked") is True:
            reason = str(link_payload.get("reason") or "signed-in page blocked access")
            error = AgentWebBrowserError(f"{board} browser circuit opened: {reason}")
            self._record_read_error(error)
            raise error
        expected_platform = BOARD_PLATFORMS[board]
        payload_board = str(link_payload.get("board") or "").casefold()
        if payload_board and payload_board != expected_platform:
            raise AgentWebBrowserError(
                f"{board} browser circuit opened: active page changed platforms"
            )
        job_links: list[str] = []
        job_link_records: list[dict[str, str]] = []
        seen_job_keys: set[str] = set()
        for item in link_payload.get("links", []):
            href = str(item.get("href") if isinstance(item, dict) else item or "").strip()
            link_text = (
                " ".join(str(item.get("text") or "").split())
                if isinstance(item, dict) else ""
            )
            if not href:
                continue
            try:
                if not self._is_board_job_url(href, board):
                    continue
            except AgentWebBrowserError:
                continue
            href = self._sanitize_board_job_url(href, board)
            job_key = self._board_job_key(href, board)
            if job_key not in seen_job_keys:
                seen_job_keys.add(job_key)
                job_links.append(href)
                job_link_records.append({"url": href, "text": link_text})
            if len(job_links) >= limit:
                break
        result = AgentWebBrowserSearchResult(
            board=board,
            query=" ".join(str(query).split()),
            location=" ".join(str(location).split()),
            search_url=search_url,
            page_url=page.url,
            title=page.title,
            text_length=page.text_length,
            job_links=job_links,
            job_link_records=job_link_records,
        )
        with self._session_lock:
            self._search_cache[cache_key] = result
        return result

    def read_job_page(
        self,
        url: str,
        board: str,
        poll_attempts: int = 20,
        poll_delay: float = 0.5,
    ) -> AgentWebBrowserPage:
        """Read each unique board URL once per run and reuse sanitized page text."""
        target_url = self._validate_board_url(url, board)
        cache_key = (board, target_url)
        with self._session_lock:
            cached = self._page_cache.get(cache_key)
            if cached is not None:
                self._duplicate_reads_avoided += 1
                return cached
            try:
                page = self._read_job_page_unlocked(
                    target_url,
                    board,
                    poll_attempts=poll_attempts,
                    poll_delay=poll_delay,
                )
            except AgentWebBrowserError as exc:
                self._record_read_error(exc)
                raise
            self._page_cache[cache_key] = page
            self._logical_page_reads += 1
            return page

    def _read_job_page_unlocked(
        self,
        url: str,
        board: str,
        poll_attempts: int,
        poll_delay: float,
    ) -> AgentWebBrowserPage:
        """Navigate one managed first-party tab while the session lock is held."""
        target_url = self._validate_board_url(url, board)
        platform = BOARD_PLATFORMS[board]
        status = self.status()
        # The upstream tab bar creates its eight default tabs asynchronously. Wait
        # for that short startup window before requesting a job-board tab; otherwise
        # its createTab guard intentionally ignores the concurrent request.
        if status.get("sessionActive") and int(status.get("tabCount") or 0) < 8:
            for _ in range(10):
                time.sleep(0.5)
                status = self.status()
                if int(status.get("tabCount") or 0) >= 8:
                    break
        tabs = status.get("tabs", [])
        matching = next(
            (
                tab
                for tab in tabs
                if isinstance(tab, dict)
                and str(tab.get("platform", "")).casefold() == platform
            ),
            None,
        )
        if matching and matching.get("id") is not None:
            tab_id = int(matching["id"])
            self._request("POST", "/tabs/switch", {"id": tab_id})
            self._request("POST", "/tabs/navigate", {"id": tab_id, "url": target_url})
        else:
            self._request("POST", "/tabs/new", {"count": 1, "url": target_url})

        final_status: dict[str, Any] = {}
        text_payload: dict[str, Any] = {}
        last_read_error = ""
        for attempt in range(max(1, min(int(poll_attempts), 60))):
            if attempt:
                time.sleep(max(0.0, min(float(poll_delay), 2.0)))
            final_status = self.status()
            active_id = final_status.get("activeTab")
            active_tab = next(
                (
                    tab
                    for tab in final_status.get("tabs", [])
                    if isinstance(tab, dict) and tab.get("id") == active_id
                ),
                {},
            )
            if str(active_tab.get("platform", "")).casefold() != platform:
                continue
            if active_tab.get("pageReady", True) is not True:
                continue
            try:
                text_payload = self._result(self._request("GET", "/page/text"))
            except AgentWebBrowserError as exc:
                # The observer may be temporarily absent while WebView2 replaces the
                # document during navigation. Treat that as loading, not as a board block.
                last_read_error = str(exc)
                continue
            if str(text_payload.get("text") or "").strip():
                break

        active_id = final_status.get("activeTab")
        active_tab = next(
            (
                tab
                for tab in final_status.get("tabs", [])
                if isinstance(tab, dict) and tab.get("id") == active_id
            ),
            {},
        )
        text = str(text_payload.get("text") or "").strip()
        if not text:
            detail = f" Last loading error: {last_read_error}" if last_read_error else ""
            raise AgentWebBrowserError(
                f"AWB did not return visible {board} page text after navigation.{detail}"
            )
        return AgentWebBrowserPage(
            url=str(active_tab.get("url") or target_url),
            title=str(active_tab.get("title") or ""),
            platform=platform,
            text=text,
            text_length=int(text_payload.get("len") or len(text)),
        )
