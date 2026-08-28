"""Original MIT web reading, extraction, caching, and bounded crawling tools.

This module recreates the useful product-level behavior requested from a
restricted-license research tool without using its source or design. Every
network hop is resolved and checked before connection, the default transport
connects to the validated address, redirects are revalidated, and responses
are bounded before they reach parsers or agent context.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import sqlite3
import ssl
import threading
import time
from dataclasses import asdict, dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit


class WebIntelligenceError(RuntimeError):
    """Base class for web intelligence failures."""


class UnsafeUrlError(WebIntelligenceError):
    """Raised when a URL or resolved address crosses a local trust boundary."""


class DnsPinError(WebIntelligenceError):
    """Raised when the connected peer is outside the validated DNS answer set."""


class ResponseTooLargeError(WebIntelligenceError):
    """Raised before a response larger than the configured cap is parsed."""


class UnsafeContentTypeError(WebIntelligenceError):
    """Raised when a response is not a readable text representation."""


class RedirectLimitError(WebIntelligenceError):
    """Raised when a redirect chain exceeds its configured hop limit."""


@dataclass(frozen=True)
class FetchLimits:
    """Resource ceilings shared by fetch and crawl operations."""

    max_bytes: int = 2_000_000
    timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_pages: int = 20
    max_depth: int = 2

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.timeout_seconds <= 0:
            raise ValueError("Fetch byte and time limits must be positive.")
        if self.max_redirects < 0 or self.max_pages <= 0 or self.max_depth < 0:
            raise ValueError("Redirect, page, and depth limits are invalid.")


@dataclass(frozen=True)
class ResolvedTarget:
    """A normalized public URL and the exact addresses approved for connection."""

    url: str
    hostname: str
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class HttpResponse:
    """Transport response with the actual connected peer address."""

    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    peer_ip: str


@dataclass(frozen=True)
class WebDocument:
    """One bounded fetched document plus extraction and access signals."""

    url: str
    status: int
    mime_type: str
    html: str
    text: str
    title: str
    links_raw: tuple[str, ...]
    metadata: Mapping[str, str]
    robots: str
    challenge_detected: bool
    fetched_at: float
    from_cache: bool = False


Resolver = Callable[[str], Sequence[str]]
Transport = Callable[..., HttpResponse]


def _default_resolver(hostname: str) -> list[str]:
    """Resolve every address family so one unsafe DNS answer fails the request."""
    try:
        records = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Host could not be resolved: {hostname}") from exc
    addresses: list[str] = []
    for record in records:
        address = str(record[4][0]).split("%", 1)[0]
        if address not in addresses:
            addresses.append(address)
    return addresses


class SafeUrlPolicy:
    """Validate public HTTP targets and resolve every address before use."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        allowed_schemes: Sequence[str] = ("http", "https"),
        allowed_ports: Sequence[int] = (80, 443),
    ):
        self.resolver = resolver or _default_resolver
        self.allowed_schemes = frozenset(allowed_schemes)
        self.allowed_ports = frozenset(int(port) for port in allowed_ports)

    @staticmethod
    def _public_address(value: str) -> str:
        try:
            address = ipaddress.ip_address(value.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeUrlError("DNS returned an invalid network address.") from exc
        if not address.is_global:
            raise UnsafeUrlError("Private, loopback, link-local, and reserved targets are blocked.")
        return address.compressed

    def resolve(self, raw_url: str) -> ResolvedTarget:
        """Normalize and resolve one URL, failing closed on any unsafe address."""
        try:
            parsed = urlsplit(str(raw_url).strip())
        except ValueError as exc:
            raise UnsafeUrlError("URL could not be parsed.") from exc
        if parsed.scheme.casefold() not in self.allowed_schemes or not parsed.hostname:
            raise UnsafeUrlError("Only public HTTP and HTTPS URLs are allowed.")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("URL user information is not allowed.")
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname == "localhost" or hostname.endswith(".localhost"):
            raise UnsafeUrlError("Localhost targets are blocked.")
        try:
            port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
        except ValueError as exc:
            raise UnsafeUrlError("URL port is invalid.") from exc
        if port not in self.allowed_ports:
            raise UnsafeUrlError("URL port is outside the public web allowlist.")

        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                raw_addresses = self.resolver(hostname.encode("idna").decode("ascii"))
            except UnsafeUrlError:
                raise
            except Exception as exc:
                raise UnsafeUrlError(f"Host could not be resolved: {hostname}") from exc
            if not raw_addresses:
                raise UnsafeUrlError(f"Host did not resolve: {hostname}")
            addresses = tuple(dict.fromkeys(self._public_address(value) for value in raw_addresses))
        else:
            addresses = (self._public_address(literal.compressed),)

        netloc_host = f"[{hostname}]" if ":" in hostname else hostname
        default_port = 443 if parsed.scheme.casefold() == "https" else 80
        netloc = netloc_host if port == default_port else f"{netloc_host}:{port}"
        normalized = urlunsplit(
            (
                parsed.scheme.casefold(),
                netloc,
                parsed.path or "/",
                parsed.query,
                "",
            )
        )
        return ResolvedTarget(normalized, hostname, addresses)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that dials the address already approved by policy."""

    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to an IP while retaining hostname TLS checks."""

    def __init__(self, host: str, port: int, pinned_ip: str, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def default_transport(
    url: str,
    *,
    timeout_seconds: float,
    max_bytes: int,
    pinned_addresses: Sequence[str],
) -> HttpResponse:
    """Fetch one hop directly through its first validated DNS address."""
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    pinned_ip = str(pinned_addresses[0])
    connection_type = _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    connection = connection_type(parsed.hostname or "", port, pinned_ip, timeout_seconds)
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "ExpedientEmployment/2.0 (+local user agent)",
                "Cache-Control": "no-cache",
                "Host": parsed.netloc,
            },
        )
        raw_response = connection.getresponse()
        headers = {key.casefold(): value for key, value in raw_response.getheaders()}
        claimed = headers.get("content-length", "")
        if claimed.isdigit() and int(claimed) > max_bytes:
            raise ResponseTooLargeError("Response Content-Length exceeds the fetch cap.")
        body = raw_response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ResponseTooLargeError("Response body exceeds the fetch cap.")
        return HttpResponse(
            url=url,
            status=int(raw_response.status),
            headers=headers,
            body=body,
            peer_ip=pinned_ip,
        )
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise WebIntelligenceError(f"Public page fetch failed: {exc}") from exc
    finally:
        connection.close()


class WebCache:
    """SQLite document cache isolated from assistant transcripts and audit logs."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS web_documents (
                url TEXT PRIMARY KEY,
                document_json TEXT NOT NULL,
                fetched_at REAL NOT NULL
            )
            """
        )
        self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.commit()
            self.connection.close()

    def get(self, url: str, freshness_seconds: int) -> WebDocument | None:
        """Return a fresh cached document, or None when absent or stale."""
        if freshness_seconds <= 0:
            return None
        with self._lock:
            row = self.connection.execute(
                "SELECT document_json, fetched_at FROM web_documents WHERE url=?", (url,)
            ).fetchone()
        if not row or time.time() - float(row[1]) > freshness_seconds:
            return None
        payload = json.loads(str(row[0]))
        payload["links_raw"] = tuple(payload.get("links_raw", []))
        return WebDocument(**payload)

    def put(self, cache_key: str, document: WebDocument) -> None:
        """Replace one cache record atomically with its bounded document."""
        payload = asdict(replace(document, from_cache=False))
        with self._lock:
            self.connection.execute(
                """
                INSERT INTO web_documents(url, document_json, fetched_at)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    document_json=excluded.document_json,
                    fetched_at=excluded.fetched_at
                """,
                (
                    cache_key,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    document.fetched_at,
                ),
            )
            self.connection.commit()


class _DocumentParser(HTMLParser):
    """Extract visible text, metadata, headings, and links with no script execution."""

    blocked_tags = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked_depth = 0
        self.title_depth = 0
        self.heading_tag = ""
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.heading_parts: dict[str, list[str]] = {}
        self.links: list[str] = []
        self.metadata: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in self.blocked_tags:
            self.blocked_depth += 1
            return
        if self.blocked_depth:
            return
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if lowered == "title":
            self.title_depth += 1
        if lowered in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_tag = lowered
        if lowered == "a" and attributes.get("href"):
            self.links.append(attributes["href"])
        if lowered == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            content = attributes.get("content", "").strip()
            if name and content and name not in self.metadata:
                self.metadata[name] = content

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self.blocked_tags:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if lowered == "title":
            self.title_depth = max(0, self.title_depth - 1)
        if lowered == self.heading_tag:
            self.heading_tag = ""

    def handle_data(self, data: str) -> None:
        if self.blocked_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self.text_parts.append(text)
        if self.title_depth:
            self.title_parts.append(text)
        if self.heading_tag:
            self.heading_parts.setdefault(self.heading_tag, []).append(text)


def _parse_document(html: str) -> _DocumentParser:
    parser = _DocumentParser()
    parser.feed(html)
    parser.close()
    return parser


_READABLE_MIME = re.compile(
    r"^(?:text/|application/(?:json|xml|xhtml\+xml|javascript|[\w.+-]+\+(?:json|xml)))",
    re.IGNORECASE,
)
_CHALLENGE_MARKERS = (
    "verify you are human",
    "are you a robot",
    "unusual traffic",
    "security check",
    "access denied",
    "enable javascript to continue",
    "captcha",
)


class WebIntelligence:
    """Fetch, extract, link, and crawl public pages under explicit limits."""

    redirect_statuses = frozenset({301, 302, 303, 307, 308})

    def __init__(
        self,
        *,
        policy: SafeUrlPolicy | None = None,
        transport: Transport | None = None,
        cache: WebCache | None = None,
        limits: FetchLimits | None = None,
    ):
        self.policy = policy or SafeUrlPolicy()
        self.transport = transport or default_transport
        self.cache = cache
        self.limits = limits or FetchLimits()

    @staticmethod
    def _decode(body: bytes, content_type: str) -> str:
        match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
        charset = match.group(1) if match else "utf-8"
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    def fetch(self, url: str, *, freshness_seconds: int = 0) -> WebDocument:
        """Fetch one public document after cache, URL, DNS, redirect, and body checks."""
        initial = self.policy.resolve(url)
        if self.cache is not None:
            cached = self.cache.get(initial.url, freshness_seconds)
            if cached is not None:
                return replace(cached, from_cache=True)

        current = initial
        for redirect_count in range(self.limits.max_redirects + 1):
            response = self.transport(
                current.url,
                timeout_seconds=self.limits.timeout_seconds,
                max_bytes=self.limits.max_bytes,
                pinned_addresses=current.addresses,
            )
            if response.url != current.url:
                returned_target = self.policy.resolve(response.url)
                if returned_target.url != current.url:
                    raise DnsPinError("Transport followed an unapproved URL outside redirect control.")
            try:
                peer = ipaddress.ip_address(response.peer_ip).compressed
            except ValueError as exc:
                raise DnsPinError("Transport did not report a valid connected peer.") from exc
            if peer not in current.addresses:
                raise DnsPinError("Connected peer does not match the validated DNS addresses.")

            headers = {str(key).casefold(): str(value) for key, value in response.headers.items()}
            if response.status in self.redirect_statuses:
                location = headers.get("location", "").strip()
                if not location:
                    raise WebIntelligenceError("Redirect response omitted its Location header.")
                if redirect_count >= self.limits.max_redirects:
                    raise RedirectLimitError("Public page redirect limit was exceeded.")
                current = self.policy.resolve(urljoin(current.url, location))
                continue

            claimed = headers.get("content-length", "")
            if claimed.isdigit() and int(claimed) > self.limits.max_bytes:
                raise ResponseTooLargeError("Response Content-Length exceeds the fetch cap.")
            if len(response.body) > self.limits.max_bytes:
                raise ResponseTooLargeError("Response body exceeds the fetch cap.")
            content_type = headers.get("content-type", "text/plain")
            mime_type = content_type.split(";", 1)[0].strip().casefold()
            if not _READABLE_MIME.match(mime_type):
                raise UnsafeContentTypeError(f"Response type is not readable text: {mime_type}")
            html = self._decode(response.body, content_type)
            parsed = _parse_document(html)
            text = " ".join(parsed.text_parts)
            robots = parsed.metadata.get("robots", "")
            challenge = any(marker in text.casefold() for marker in _CHALLENGE_MARKERS)
            document = WebDocument(
                url=current.url,
                status=int(response.status),
                mime_type=mime_type,
                html=html,
                text=text,
                title=" ".join(parsed.title_parts),
                links_raw=tuple(parsed.links),
                metadata=dict(parsed.metadata),
                robots=robots,
                challenge_detected=challenge,
                fetched_at=time.time(),
            )
            if self.cache is not None:
                self.cache.put(initial.url, document)
            return document
        raise RedirectLimitError("Public page redirect limit was exceeded.")

    def extract(
        self,
        document: WebDocument,
        fields: Mapping[str, str],
    ) -> dict[str, str]:
        """Extract named fields with a small non-executable selector grammar."""
        if len(fields) > 100:
            raise WebIntelligenceError("Extraction field count exceeds the limit.")
        parsed = _parse_document(document.html)
        output: dict[str, str] = {}
        for name, selector in fields.items():
            if len(name) > 128 or len(selector) > 512:
                raise WebIntelligenceError("Extraction field name or selector is too long.")
            if selector == "title":
                value = document.title
            elif selector == "text":
                value = document.text
            elif selector.startswith("meta:"):
                value = str(document.metadata.get(selector[5:].casefold(), ""))
            elif selector.startswith("heading:"):
                tag = selector[8:].casefold()
                if tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                    raise WebIntelligenceError("Heading selector is invalid.")
                value = " ".join(parsed.heading_parts.get(tag, []))
            elif selector.startswith("regex:"):
                pattern = selector[6:]
                if len(pattern) > 256:
                    raise WebIntelligenceError("Extraction regex is too long.")
                try:
                    match = re.search(pattern, document.text, re.IGNORECASE)
                except re.error as exc:
                    raise WebIntelligenceError("Extraction regex is invalid.") from exc
                value = match.group(0) if match else ""
            else:
                raise WebIntelligenceError(f"Unsupported extraction selector: {selector}")
            output[str(name)] = re.sub(r"\s+", " ", value).strip()
        return output

    def links(self, document: WebDocument) -> list[str]:
        """Return unique, policy-safe absolute links in document order."""
        output: list[str] = []
        for raw_link in document.links_raw:
            candidate = urljoin(document.url, raw_link)
            try:
                resolved = self.policy.resolve(candidate)
            except UnsafeUrlError:
                continue
            if resolved.url not in output:
                output.append(resolved.url)
        return output

    def crawl(self, start_url: str, *, same_site: bool = True) -> list[WebDocument]:
        """Breadth-first crawl under fixed page, depth, and optional host limits."""
        start = self.policy.resolve(start_url)
        start_host = start.hostname
        pending: list[tuple[str, int]] = [(start.url, 0)]
        seen: set[str] = set()
        documents: list[WebDocument] = []
        while pending and len(documents) < self.limits.max_pages:
            current_url, depth = pending.pop(0)
            if current_url in seen:
                continue
            seen.add(current_url)
            document = self.fetch(current_url)
            documents.append(document)
            if depth >= self.limits.max_depth:
                continue
            for link in self.links(document):
                target = self.policy.resolve(link)
                if same_site and target.hostname != start_host:
                    continue
                if target.url not in seen and all(item[0] != target.url for item in pending):
                    pending.append((target.url, depth + 1))
        return documents
