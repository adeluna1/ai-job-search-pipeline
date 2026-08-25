"""Shared filesystem, text-normalization, privacy, URL, and logging helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_", "gh_src", "source", "ref", "referrer")


def utc_now() -> str:
    """Return a stable second-precision UTC timestamp for database records."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    """Read a UTF-8 JSON object from disk."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    """Write indented UTF-8 JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_json_atomic(path: Path, value: Any) -> None:
    """Atomically replace a JSON file so interrupted checkpoints stay readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without replacing existing environment values."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def configure_logging(log_path: Path, verbose: bool = False) -> None:
    """Send normal logs to a local file and optionally mirror debug output to stderr."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def normalize_space(value: str | None) -> str:
    """Collapse repeated whitespace and safely normalize a nullable string."""
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_term(value: str | None) -> str:
    """Normalize a phrase for case-insensitive matching while retaining technical symbols."""
    value = normalize_space(value).casefold()
    value = value.replace("&", " and ")
    return re.sub(r"[^a-z0-9+#.]+", " ", value).strip()


def canonical_url(url: str) -> str:
    """Normalize scheme/host/path and remove fragments plus common tracking parameters."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if not netloc and parts.path:
        reparsed = urlsplit(f"https://{parts.path}")
        scheme, netloc, path = reparsed.scheme, reparsed.netloc, reparsed.path
        query = reparsed.query
    else:
        path, query = parts.path, parts.query
    query_items = parse_qsl(query, keep_blank_values=True)
    host = netloc.casefold().split(":", 1)[0]
    if host == "hrmdirect.com" or host.endswith(".hrmdirect.com"):
        requisition_items = [
            (key, value)
            for identifier in ("req", "id")
            for key, value in query_items
            if key.casefold() == identifier and value
        ]
        if requisition_items:
            query_items = requisition_items[:1]
    kept = []
    for key, value in query_items:
        if not any(key.casefold().startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            kept.append((key, value))
    clean_path = re.sub(r"/{2,}", "/", path or "/")
    return urlunsplit((scheme, netloc, clean_path.rstrip("/") or "/", urlencode(kept), ""))


def stable_id(*parts: str) -> str:
    """Create a deterministic, short identifier from normalized string components."""
    joined = "\x1f".join(normalize_term(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    """Deduplicate cleaned strings case-insensitively without changing their first order."""
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = normalize_space(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def redact_secrets(value: str) -> str:
    """Mask common API-key patterns before a subprocess message reaches logs or users."""
    value = re.sub(r"(?i)(api[_-]?key[=:\s]+)[^\s]+", r"\1[REDACTED]", value)
    value = re.sub(r"\b(?:sk|wc)_[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
    return value
