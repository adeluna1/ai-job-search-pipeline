"""Read-only adapter for BarnsL/agent-web-browser's authenticated loopback API."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


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


class AgentWebBrowserClient:
    """Use only safe navigation/read routes from the AWB loopback bridge."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:7896",
        token: str | None = None,
        token_path: Path | None = None,
        timeout: float = 5.0,
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

    def read_job_page(
        self,
        url: str,
        board: str,
        poll_attempts: int = 5,
        poll_delay: float = 0.5,
    ) -> AgentWebBrowserPage:
        """Serialize managed-tab use and return sanitized visible job-page text."""
        with self._session_lock:
            return self._read_job_page_unlocked(
                url,
                board,
                poll_attempts=poll_attempts,
                poll_delay=poll_delay,
            )

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
        for attempt in range(max(1, min(int(poll_attempts), 10))):
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
            text_payload = self._result(self._request("GET", "/page/text"))
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
            raise AgentWebBrowserError(
                f"AWB did not return visible {board} page text after navigation."
            )
        return AgentWebBrowserPage(
            url=str(active_tab.get("url") or target_url),
            title=str(active_tab.get("title") or ""),
            platform=platform,
            text=text,
            text_length=int(text_payload.get("len") or len(text)),
        )
