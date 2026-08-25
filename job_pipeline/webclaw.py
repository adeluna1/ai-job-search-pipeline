"""The single subprocess adapter for the separate WebClaw executable."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .util import redact_secrets


LOGGER = logging.getLogger(__name__)


class WebClawError(RuntimeError):
    """Raised when the separate WebClaw executable cannot complete a request."""


class WebClawClient:
    """Invoke WebClaw and validate its machine-readable JSON boundaries."""
    def __init__(self, project_root: Path, binary: str | None = None, timeout: int = 60):
        """Resolve the executable once and retain a default request timeout."""
        self.project_root = project_root
        try:
            timeout = int(os.environ.get("WEBCLAW_TIMEOUT_SECONDS", str(timeout)))
        except ValueError:
            pass
        self.timeout = max(5, min(timeout, 120))
        self.binary = self._resolve_binary(binary)

    def _resolve_binary(self, explicit: str | None) -> str:
        """Find WebClaw from an explicit flag, environment, local tools, or PATH."""
        candidates = [
            explicit,
            os.environ.get("WEBCLAW_BIN"),
            str(self.project_root / "tools" / "webclaw" / "webclaw.exe"),
            str(self.project_root / "tools" / "webclaw" / "webclaw"),
            shutil.which("webclaw"),
            shutil.which("webclaw.exe"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists() or shutil.which(candidate):
                return str(path if path.exists() else candidate)
        raise WebClawError(
            "WebClaw was not found. Run scripts/install-webclaw.ps1 or set WEBCLAW_BIN."
        )

    def _run(self, args: list[str], stdin_text: str | None = None, timeout: int | None = None) -> str:
        """Run WebClaw safely, isolate stderr, redact secrets, and surface concise errors."""
        command = [self.binary, *args]
        LOGGER.debug("Running WebClaw: %s", " ".join(command[:4]))
        try:
            result = subprocess.run(
                command,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout or self.timeout,
                check=False,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise WebClawError(f"WebClaw timed out after {exc.timeout} seconds.") from exc
        except OSError as exc:
            raise WebClawError(f"Could not start WebClaw: {exc}") from exc

        if result.stderr:
            LOGGER.debug("WebClaw stderr: %s", redact_secrets(result.stderr.strip()))
        if result.returncode != 0:
            message = redact_secrets(result.stderr.strip() or result.stdout.strip() or "unknown error")
            raise WebClawError(f"WebClaw failed ({result.returncode}): {message}")
        return result.stdout.strip()

    def version(self) -> str:
        """Return the installed WebClaw version string."""
        return self._run(["--version"], timeout=15)

    def search(
        self,
        query: str,
        num: int = 8,
        country: str | None = "us",
        language: str | None = "en",
    ) -> list[dict[str, Any]]:
        """Use Tavily for discovery and employer-page extraction."""
        tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if tavily_key:
            payload = json.dumps({
                "query": query, "search_depth": "basic", "topic": "general",
                "max_results": max(1, min(int(num), 10)),
                "include_answer": False, "include_raw_content": False,
            }).encode("utf-8")
            request = urllib.request.Request(
                "https://api.tavily.com/search", data=payload,
                headers={"Authorization": f"Bearer {tavily_key}", "Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    raw = response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                detail = exc.read(1024).decode("utf-8", errors="replace")
                raise WebClawError(f"Tavily search returned HTTP {exc.code}: {redact_secrets(detail)}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise WebClawError(f"Tavily search failed: {exc}") from exc
            try:
                result_payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise WebClawError(f"Tavily search returned invalid JSON: {exc}") from exc
            results = result_payload.get("results", []) if isinstance(result_payload, dict) else []
            return [{"title": item.get("title", ""), "link": item.get("url", ""), "snippet": item.get("content", ""), "score": item.get("score")}
                    for item in results if isinstance(item, dict) and item.get("url")]
        raise WebClawError("Tavily search is not configured. Set TAVILY_API_KEY before running discovery.")

    def scrape(self, url: str) -> dict[str, Any]:
        """Extract one public page into WebClaw's JSON metadata/content structure."""
        tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
        if tavily_key:
            request = urllib.request.Request(
                "https://api.tavily.com/extract",
                data=json.dumps({"urls": [url], "extract_depth": "basic"}).encode("utf-8"),
                headers={"Authorization": f"Bearer {tavily_key}", "Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=min(self.timeout, 45)) as response:
                    payload = json.loads(response.read().decode("utf-8", errors="replace"))
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                raise WebClawError(f"Tavily extraction failed for {url}: {exc}") from exc
            results = payload.get("results", []) if isinstance(payload, dict) else []
            item = results[0] if results and isinstance(results[0], dict) else {}
            return {"url": item.get("url", url), "content": item.get("raw_content", item.get("content", "")), "title": item.get("title", "")}
        output = self._run(
            [url, "--format", "json", "--only-main-content", "--timeout", str(self.timeout)],
            timeout=self.timeout + 15,
        )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise WebClawError(f"Scrape returned invalid JSON for {url}: {exc}") from exc
        if not isinstance(payload, dict):
            raise WebClawError(f"Scrape returned an unexpected JSON shape for {url}.")
        return payload

    def probe(self, url: str, max_bytes: int = 524_288) -> dict[str, Any]:
        """Fetch a job URL without cache and expose its final redirect target.

        Search indexes and extraction caches can retain a full job description after
        the employer closes the requisition. This lightweight second channel makes
        redirect-to-index and explicit expiry responses visible to the verifier.
        """
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "User-Agent": "Mozilla/5.0 (compatible; AIJobSearchPipeline/1.0)",
            },
            method="GET",
        )
        limit = max(1, min(int(max_bytes), 1_048_576))
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 30)) as response:
                body = response.read(limit)
                return {
                    "requested_url": url,
                    "final_url": response.geturl(),
                    "status": int(getattr(response, "status", 200)),
                    "content_type": str(response.headers.get("Content-Type", "")),
                    "body": body.decode("utf-8", errors="replace"),
                }
        except urllib.error.HTTPError as exc:
            return {
                "requested_url": url,
                "final_url": exc.geturl(),
                "status": int(exc.code),
                "content_type": str(exc.headers.get("Content-Type", "")),
                "body": exc.read(limit).decode("utf-8", errors="replace"),
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WebClawError(f"Fresh application probe failed for {url}: {exc}") from exc

    def extract_json_from_text(
        self,
        text: str,
        schema_path: Path,
        provider: str | None = None,
        model: str | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        """Pass local HTML/text through WebClaw's schema-based optional LLM provider chain."""
        args = ["--stdin", "--extract-json", f"@{schema_path}"]
        if provider:
            args.extend(["--llm-provider", provider])
        if model:
            args.extend(["--llm-model", model])
        output = self._run(args, stdin_text=text, timeout=timeout)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise WebClawError(f"LLM extraction returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise WebClawError("LLM extraction returned an unexpected JSON shape.")
        return payload
