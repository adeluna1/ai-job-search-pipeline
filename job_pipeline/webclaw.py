"""The single subprocess adapter for the separate WebClaw executable."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
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
        self.timeout = timeout
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
        """Use WebClaw's Serper-backed search and return validated organic result objects."""
        args = ["search", query, "--num", str(max(1, min(num, 10))), "--format", "json"]
        if country:
            args.extend(["--country", country])
        if language:
            args.extend(["--lang", language])
        output = self._run(args, timeout=45)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise WebClawError(f"Search returned invalid JSON: {exc}") from exc
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [result for result in results if isinstance(result, dict) and result.get("link")]

    def scrape(self, url: str) -> dict[str, Any]:
        """Extract one public page into WebClaw's JSON metadata/content structure."""
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
