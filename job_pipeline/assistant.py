"""Durable queued, image-aware assistant with brokered tool execution.

Conversation state is local SQLite data. Provider credentials are referenced by
environment-variable name and never persisted. Image bytes remain in an
application-owned directory and are sent only when a conversation explicitly
allows provider image upload. Tool calls always pass through ``ToolBroker``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from .tool_broker import (
    ApprovalRequiredError,
    ToolBroker,
    ToolBrokerError,
    ToolCancelledError,
    ToolContext,
)
from .util import redact_secrets, utc_now


MAX_TOOL_ROUNDS = 8
MAX_MESSAGE_CHARS = 32_000
MAX_ATTACHMENTS_PER_MESSAGE = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_CONVERSATION_ATTACHMENT_BYTES = 40 * 1024 * 1024
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})


class AssistantError(RuntimeError):
    """Base class for assistant storage and execution failures."""


class ProviderError(AssistantError):
    """Raised when a configured model provider is unavailable or malformed."""


@dataclass(frozen=True)
class ToolCall:
    """One provider-requested typed tool invocation."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class AssistantResponse:
    """Provider text plus zero or more typed tool requests."""

    content: str
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class AttachmentRecord:
    """Local content-addressed image metadata."""

    id: str
    conversation_id: str
    filename: str
    mime_type: str
    byte_count: int
    digest: str
    local_path: str
    created_at: str


@dataclass(frozen=True)
class QueuedMessage:
    """A durable user or assistant message and its queue state."""

    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    sequence: int
    retry_of: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConversationRecord:
    """Provider, model, title, and image-sharing choice for one transcript."""

    id: str
    title: str
    provider: str
    model: str
    allow_image_upload: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AssistantRequest:
    """Provider-neutral completion request and tool-loop state."""

    model: str
    messages: tuple[Mapping[str, Any], ...]
    tools: tuple[Mapping[str, Any], ...]
    attachments: tuple[AttachmentRecord, ...] = ()
    allow_image_upload: bool = False
    tool_results: tuple[Mapping[str, Any], ...] = ()

    def with_tool_round(
        self,
        response: AssistantResponse,
        results: Sequence[Mapping[str, Any]],
    ) -> "AssistantRequest":
        assistant_message = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            dict(call.arguments), ensure_ascii=False, sort_keys=True
                        ),
                    },
                }
                for call in response.tool_calls
            ],
        }
        tool_messages = tuple(
            {
                "role": "tool",
                "tool_call_id": result["tool_call_id"],
                "content": json.dumps(result["result"], ensure_ascii=False, sort_keys=True),
            }
            for result in results
        )
        return replace(
            self,
            messages=(*self.messages, assistant_message, *tool_messages),
            tool_results=(*self.tool_results, *tuple(results)),
            attachments=(),
        )


class AssistantProvider(Protocol):
    """Minimal provider contract used by the durable queue."""

    name: str

    def readiness(self) -> dict[str, Any]: ...

    def models(self) -> list[str]: ...

    def complete(self, request: AssistantRequest) -> AssistantResponse: ...


ProviderTransport = Callable[[str, str, Mapping[str, str], Any, float], dict[str, Any]]


def _json_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: Any,
    timeout: float,
) -> dict[str, Any]:
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=encoded, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ProviderError("Provider response exceeded the 2 MB cap.")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Provider request failed: {redact_secrets(str(exc))}") from exc
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Provider returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise ProviderError("Provider returned an invalid response object.")
    return value


class OpenAICompatibleProvider:
    """Bounded OpenAI-compatible chat adapter for HTTPS or loopback services."""

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        credential_env: str = "",
        transport: ProviderTransport | None = None,
        timeout_seconds: float = 60,
    ):
        parsed = urlsplit(base_url.rstrip("/"))
        host = (parsed.hostname or "").casefold()
        loopback = host in {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme not in {"http", "https"} or not host:
            raise ProviderError("Provider URL must use HTTP or HTTPS.")
        if parsed.scheme != "https" and not loopback:
            raise ProviderError("Remote providers must use HTTPS.")
        if parsed.username is not None or parsed.password is not None:
            raise ProviderError("Provider URL user information is not allowed.")
        if credential_env and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,71}", credential_env):
            raise ProviderError("Provider credential environment name is invalid.")
        if not name.strip() or len(name) > 80:
            raise ProviderError("Provider name is invalid.")
        self.name = name.strip()
        self.base_url = base_url.rstrip("/")
        self.credential_env = credential_env
        self.transport = transport or _json_transport
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
        self._auto_fallback_model = ""

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.credential_env:
            credential = self._credential()
            if credential:
                headers["Authorization"] = f"Bearer {credential}"
        return headers

    def _credential(self) -> str:
        return os.environ.get(self.credential_env, "").strip() if self.credential_env else ""

    def _redact_provider_value(self, value: Any) -> Any:
        """Remove the active credential from untrusted provider output."""
        credential = self._credential()
        if isinstance(value, str):
            return value.replace(credential, "[REDACTED]") if credential else value
        if isinstance(value, list):
            return [self._redact_provider_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_provider_value(item) for key, item in value.items()}
        return value

    def _credential_configured(self) -> bool:
        return not self.credential_env or bool(self._credential())

    @staticmethod
    def _model_ids(payload: Mapping[str, Any]) -> list[str]:
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise ProviderError("Provider model response is invalid.")
        identifiers = [
            item["id"].strip()
            for item in data
            if isinstance(item, Mapping)
            and isinstance(item.get("id"), str)
            and item["id"].strip()
        ][:200]
        if not identifiers:
            raise ProviderError("Provider model response is invalid.")
        return identifiers

    @staticmethod
    def _probe_failure(exc: Exception) -> tuple[bool, bool, str]:
        message = str(exc).casefold()
        if re.search(r"\b(?:401|403)\b", message) or any(
            marker in message
            for marker in (
                "unauthorized",
                "unauthorised",
                "forbidden",
                "authentication",
                "authorization",
            )
        ):
            return True, False, "Provider authorization failed"
        if any(
            marker in message
            for marker in (
                "connection refused",
                "connection reset",
                "network",
                "timed out",
                "timeout",
                "unreachable",
                "urlopen error",
                "name or service not known",
            )
        ):
            return False, False, "Provider is unreachable"
        return True, True, "Provider response is invalid"

    def readiness(self) -> dict[str, Any]:
        configured = self._credential_configured()
        if not configured:
            return {
                "ready": False,
                "credential_configured": False,
                "reachable": False,
                "authenticated": False,
                "model_count": 0,
                "detail": "Provider credential is not configured",
            }
        try:
            payload = self.transport(
                "GET", f"{self.base_url}/models", self._headers(), None, self.timeout_seconds
            )
        except Exception as exc:
            reachable, authenticated, detail = self._probe_failure(exc)
            return {
                "ready": False,
                "credential_configured": True,
                "reachable": reachable,
                "authenticated": authenticated,
                "model_count": 0,
                "detail": detail,
            }
        try:
            identifiers = self._model_ids(payload)
        except (AttributeError, ProviderError, TypeError):
            return {
                "ready": False,
                "credential_configured": True,
                "reachable": True,
                "authenticated": True,
                "model_count": 0,
                "detail": "Provider response is invalid",
            }
        return {
            "ready": True,
            "credential_configured": True,
            "reachable": True,
            "authenticated": True,
            "model_count": len(identifiers),
            "detail": "Provider ready",
        }

    def models(self) -> list[str]:
        if not self._credential_configured():
            raise ProviderError("Provider credential is not configured.")
        transport_error: str | None = None
        try:
            payload = self.transport(
                "GET", f"{self.base_url}/models", self._headers(), None, self.timeout_seconds
            )
        except Exception as exc:
            _reachable, _authenticated, detail = self._probe_failure(exc)
            transport_error = f"{detail}."
        if transport_error is not None:
            raise ProviderError(transport_error)
        try:
            return self._model_ids(payload)
        except (AttributeError, TypeError):
            pass
        raise ProviderError("Provider model response is invalid.")

    @staticmethod
    def _message_payload(request: AssistantRequest) -> list[dict[str, Any]]:
        messages = [dict(item) for item in request.messages]
        if not request.attachments:
            return messages
        if not messages or messages[-1].get("role") != "user":
            raise ProviderError("Image attachments require a current user message.")
        current = dict(messages[-1])
        original_content = str(current.get("content", ""))
        if not request.allow_image_upload:
            current["content"] = (
                original_content
                + f"\n\n[{len(request.attachments)} local image attachment(s) were not shared.]"
            )
        else:
            content: list[dict[str, Any]] = [{"type": "text", "text": original_content}]
            for attachment in request.attachments:
                data = base64.b64encode(Path(attachment.local_path).read_bytes()).decode("ascii")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{attachment.mime_type};base64,{data}"},
                })
            current["content"] = content
        messages[-1] = current
        return messages

    @staticmethod
    def _auto_fallback_models(model_ids: Sequence[str]) -> list[str]:
        """Return a short, deterministic set of concrete recovery models.

        FreeChain advertises routing aliases alongside concrete models. When
        the ``auto`` route is temporarily unavailable, retrying another alias
        tends to hit the same failed upstream. Prefer small, commonly exposed
        concrete models when present, then retain the provider's advertised
        order. Preview and stealth routes are never selected automatically.
        """
        preferred = (
            "gemini-3.5-flash",
            "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile",
        )
        usable = [
            model_id
            for model_id in model_ids
            if model_id != "auto"
            and not model_id.casefold().startswith("auto/")
            and "stealth" not in model_id.casefold()
            and "preview" not in model_id.casefold()
        ]
        ordered = [model_id for model_id in preferred if model_id in usable]
        ordered.extend(model_id for model_id in usable if model_id not in ordered)
        return ordered[:4]

    def _request_completion(self, body: Mapping[str, Any]) -> AssistantResponse:
        transport_failed = False
        try:
            payload = self.transport(
                "POST",
                f"{self.base_url}/chat/completions",
                self._headers(),
                body,
                self.timeout_seconds,
            )
        except Exception:
            transport_failed = True
        if transport_failed:
            raise ProviderError("Provider completion request failed.")
        message = None
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            pass
        if not isinstance(message, Mapping):
            raise ProviderError("Provider completion response is missing its message.")
        calls: list[ToolCall] = []
        for item in message.get("tool_calls", []) or []:
            try:
                function = item["function"]
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError
                arguments = self._redact_provider_value(arguments)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
            else:
                calls.append(ToolCall(str(item["id"]), str(function["name"]), arguments))
                continue
            raise ProviderError("Provider returned a malformed tool call.")
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise ProviderError("Provider message content is invalid.")
        content = self._redact_provider_value(content)
        return AssistantResponse(content=content[:100_000], tool_calls=tuple(calls))

    def complete(self, request: AssistantRequest) -> AssistantResponse:
        if not self._credential_configured():
            raise ProviderError("Provider credential is not configured.")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item["description"],
                    "parameters": item["input_schema"],
                },
            }
            for item in request.tools
        ]
        body: dict[str, Any] = {"messages": self._message_payload(request)}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        attempted: set[str] = set()
        initial_models = [request.model]
        if request.model == "auto" and self._auto_fallback_model:
            initial_models.insert(0, self._auto_fallback_model)
        last_error = "Provider completion request failed."
        for model_id in initial_models:
            if model_id in attempted:
                continue
            attempted.add(model_id)
            try:
                response = self._request_completion({**body, "model": model_id})
            except ProviderError as exc:
                last_error = str(exc)
                if model_id == self._auto_fallback_model:
                    self._auto_fallback_model = ""
                continue
            if request.model == "auto" and model_id != "auto":
                self._auto_fallback_model = model_id
            return response

        if request.model != "auto":
            raise ProviderError(last_error)

        model_probe_failed = False
        try:
            model_ids = self.models()
        except ProviderError:
            model_probe_failed = True
            model_ids = []
        if not model_probe_failed:
            for model_id in self._auto_fallback_models(model_ids):
                if model_id in attempted:
                    continue
                attempted.add(model_id)
                try:
                    response = self._request_completion({**body, "model": model_id})
                except ProviderError:
                    continue
                self._auto_fallback_model = model_id
                return response
        raise ProviderError("Provider completion request failed.")


class ConversationService:
    """Own assistant persistence, message queues, attachments, and tool loops."""

    def __init__(
        self,
        database_path: Path,
        attachment_root: Path,
        *,
        providers: Mapping[str, AssistantProvider],
        broker: ToolBroker,
    ):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        attachment_root.mkdir(parents=True, exist_ok=True)
        self.attachment_root = attachment_root.resolve()
        self._providers = dict(providers)
        self.broker = broker
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                allow_image_upload INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                retry_of TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(conversation_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS assistant_attachments (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                digest TEXT NOT NULL,
                local_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message_attachments (
                message_id TEXT NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
                attachment_id TEXT NOT NULL REFERENCES assistant_attachments(id) ON DELETE CASCADE,
                PRIMARY KEY(message_id, attachment_id)
            );
            CREATE TABLE IF NOT EXISTS assistant_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_tool_invocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                policy TEXT NOT NULL,
                status TEXT NOT NULL,
                arguments_digest TEXT NOT NULL,
                result_digest TEXT NOT NULL,
                summary TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(12)}"

    def close(self) -> None:
        with self._lock:
            self.connection.commit()
            self.connection.close()

    def create_conversation(
        self,
        provider: str,
        model: str,
        title: str = "New conversation",
        *,
        allow_image_upload: bool = False,
    ) -> ConversationRecord:
        if provider not in self._providers:
            raise ValueError("Unknown assistant provider.")
        if not model.strip() or len(model) > 200:
            raise ValueError("Assistant model is invalid.")
        now = utc_now()
        identifier = self._id("conversation")
        self.connection.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                title.strip()[:200] or "New conversation",
                provider,
                model.strip(),
                int(allow_image_upload),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.conversation(identifier)

    def conversation(self, conversation_id: str) -> ConversationRecord:
        row = self.connection.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if not row:
            raise ValueError("Conversation does not exist.")
        return ConversationRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            allow_image_upload=bool(row["allow_image_upload"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def conversations(self) -> list[ConversationRecord]:
        rows = self.connection.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC, id"
        ).fetchall()
        return [self.conversation(str(row["id"])) for row in rows]

    def providers(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for name, provider in sorted(self._providers.items()):
            try:
                readiness = provider.readiness()
            except Exception as exc:
                readiness = {"ready": False, "detail": redact_secrets(str(exc))[:300]}
            output.append({"name": name, **dict(readiness)})
        return output

    def provider_models(self, provider: str) -> list[str]:
        if provider not in self._providers:
            raise ValueError("Unknown assistant provider.")
        return self._providers[provider].models()

    def _next_sequence(self, conversation_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_messages WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _message(row: sqlite3.Row) -> QueuedMessage:
        return QueuedMessage(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            status=str(row["status"]),
            sequence=int(row["sequence"]),
            retry_of=str(row["retry_of"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def message(self, message_id: str) -> QueuedMessage:
        row = self.connection.execute(
            "SELECT * FROM assistant_messages WHERE id=?", (message_id,)
        ).fetchone()
        if not row:
            raise ValueError("Assistant message does not exist.")
        return self._message(row)

    def messages(self, conversation_id: str) -> list[QueuedMessage]:
        rows = self.connection.execute(
            "SELECT * FROM assistant_messages WHERE conversation_id=? ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        return [self._message(row) for row in rows]

    def queue(self, conversation_id: str) -> list[QueuedMessage]:
        rows = self.connection.execute(
            "SELECT * FROM assistant_messages WHERE conversation_id=? AND role='user' AND status='queued' ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        return [self._message(row) for row in rows]

    def attach(
        self,
        conversation_id: str,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> AttachmentRecord:
        self.conversation(conversation_id)
        normalized_mime = mime_type.casefold().strip()
        if normalized_mime not in ALLOWED_IMAGE_MIME_TYPES:
            raise ValueError("Assistant attachments must be PNG, JPEG, WebP, or GIF images.")
        if not content or len(content) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Assistant image attachment size is invalid.")
        current_bytes = int(self.connection.execute(
            "SELECT COALESCE(SUM(byte_count), 0) FROM assistant_attachments WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()[0])
        if current_bytes + len(content) > MAX_CONVERSATION_ATTACHMENT_BYTES:
            raise ValueError("Conversation attachment storage cap would be exceeded.")
        digest = hashlib.sha256(content).hexdigest()
        extension = mimetypes.guess_extension(normalized_mime) or ".img"
        identifier = self._id("attachment")
        conversation_dir = (self.attachment_root / conversation_id).resolve()
        if self.attachment_root not in conversation_dir.parents:
            raise ValueError("Attachment path is outside application storage.")
        conversation_dir.mkdir(parents=True, exist_ok=True)
        local_path = conversation_dir / f"{digest}{extension}"
        if not local_path.exists():
            local_path.write_bytes(content)
        now = utc_now()
        safe_filename = Path(filename).name[:200] or f"image{extension}"
        self.connection.execute(
            "INSERT INTO assistant_attachments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier,
                conversation_id,
                safe_filename,
                normalized_mime,
                len(content),
                digest,
                str(local_path),
                now,
            ),
        )
        self.connection.commit()
        return self._attachment(identifier)

    def _attachment(self, attachment_id: str) -> AttachmentRecord:
        row = self.connection.execute(
            "SELECT * FROM assistant_attachments WHERE id=?", (attachment_id,)
        ).fetchone()
        if not row:
            raise ValueError("Assistant attachment does not exist.")
        return AttachmentRecord(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"]),
            byte_count=int(row["byte_count"]),
            digest=str(row["digest"]),
            local_path=str(row["local_path"]),
            created_at=str(row["created_at"]),
        )

    def attachments(self, message_id: str) -> list[AttachmentRecord]:
        rows = self.connection.execute(
            "SELECT attachment_id FROM message_attachments WHERE message_id=? ORDER BY rowid",
            (message_id,),
        ).fetchall()
        return [self._attachment(str(row["attachment_id"])) for row in rows]

    def enqueue(
        self,
        conversation_id: str,
        content: str,
        attachment_ids: Sequence[str] = (),
        *,
        retry_of: str = "",
    ) -> QueuedMessage:
        self.conversation(conversation_id)
        normalized = str(content).strip()
        if not normalized or len(normalized) > MAX_MESSAGE_CHARS:
            raise ValueError("Assistant message must contain between 1 and 32000 characters.")
        if len(attachment_ids) > MAX_ATTACHMENTS_PER_MESSAGE:
            raise ValueError("A message can contain at most five images.")
        unique_attachments = list(dict.fromkeys(attachment_ids))
        for attachment_id in unique_attachments:
            if self._attachment(attachment_id).conversation_id != conversation_id:
                raise ValueError("Attachment belongs to another conversation.")
        now = utc_now()
        identifier = self._id("message")
        self.connection.execute(
            "INSERT INTO assistant_messages VALUES (?, ?, 'user', ?, 'queued', ?, ?, ?, ?)",
            (
                identifier,
                conversation_id,
                normalized,
                self._next_sequence(conversation_id),
                retry_of,
                now,
                now,
            ),
        )
        self.connection.executemany(
            "INSERT INTO message_attachments(message_id, attachment_id) VALUES (?, ?)",
            [(identifier, item) for item in unique_attachments],
        )
        self.connection.execute(
            "UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id)
        )
        self.connection.commit()
        self._event(conversation_id, identifier, "message_queued", {"attachment_count": len(unique_attachments)})
        return self.message(identifier)

    def edit(self, message_id: str, content: str) -> QueuedMessage:
        message = self.message(message_id)
        normalized = str(content).strip()
        if message.role != "user" or message.status != "queued":
            raise ValueError("Only queued user messages can be edited.")
        if not normalized or len(normalized) > MAX_MESSAGE_CHARS:
            raise ValueError("Assistant message must contain between 1 and 32000 characters.")
        self.connection.execute(
            "UPDATE assistant_messages SET content=?, updated_at=? WHERE id=?",
            (normalized, utc_now(), message_id),
        )
        self.connection.commit()
        self._event(message.conversation_id, message.id, "message_edited", {})
        return self.message(message_id)

    def cancel(self, message_id: str) -> QueuedMessage:
        message = self.message(message_id)
        if message.role != "user" or message.status not in {"queued", "processing"}:
            raise ValueError("Only queued or processing user messages can be cancelled.")
        event = self._cancel_events.get(message_id)
        if event is not None:
            event.set()
        self.connection.execute(
            "UPDATE assistant_messages SET status='cancelled', updated_at=? WHERE id=?",
            (utc_now(), message_id),
        )
        self.connection.commit()
        self._event(message.conversation_id, message.id, "message_cancelled", {})
        return self.message(message_id)

    def retry(self, message_id: str) -> QueuedMessage:
        message = self.message(message_id)
        if message.role != "user" or message.status not in {
            "cancelled", "failed", "awaiting_approval", "needs_handoff"
        }:
            raise ValueError("Only stopped user messages can be retried.")
        return self.enqueue(
            message.conversation_id,
            message.content,
            [item.id for item in self.attachments(message.id)],
            retry_of=message.id,
        )

    def clear_transcript(self, conversation_id: str) -> None:
        self.conversation(conversation_id)
        paths = [
            Path(str(row["local_path"]))
            for row in self.connection.execute(
                "SELECT local_path FROM assistant_attachments WHERE conversation_id=?",
                (conversation_id,),
            ).fetchall()
        ]
        self.connection.execute(
            "DELETE FROM assistant_events WHERE conversation_id=?", (conversation_id,)
        )
        self.connection.execute(
            "DELETE FROM assistant_messages WHERE conversation_id=?", (conversation_id,)
        )
        self.connection.execute(
            "DELETE FROM assistant_attachments WHERE conversation_id=?", (conversation_id,)
        )
        self.connection.commit()
        for path in paths:
            try:
                resolved = path.resolve()
                if self.attachment_root in resolved.parents and resolved.is_file():
                    resolved.unlink()
            except OSError:
                continue

    def _event(
        self,
        conversation_id: str,
        message_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        self.connection.execute(
            "INSERT INTO assistant_events(conversation_id, message_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                message_id,
                event_type,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                utc_now(),
            ),
        )
        self.connection.commit()

    def events(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT id, message_id, event_type, payload_json, created_at FROM assistant_events WHERE conversation_id=? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "message_id": str(row["message_id"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def record_tool_invocation(self, **values: Any) -> int:
        """Accept broker audit metadata without storing tool arguments or content."""
        cursor = self.connection.execute(
            """
            INSERT INTO assistant_tool_invocations(
                request_id, actor, tool_name, policy, status, arguments_digest,
                result_digest, summary, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(values["request_id"]),
                str(values["actor"]),
                str(values["tool_name"]),
                str(values["policy"]),
                str(values["status"]),
                str(values["arguments_digest"]),
                str(values.get("result_digest", "")),
                redact_secrets(str(values.get("summary", "")))[:500],
                max(0, int(values.get("duration_ms", 0))),
                utc_now(),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def tool_invocations(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM assistant_tool_invocations ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def _set_status(self, message_id: str, status: str) -> QueuedMessage:
        self.connection.execute(
            "UPDATE assistant_messages SET status=?, updated_at=? WHERE id=?",
            (status, utc_now(), message_id),
        )
        self.connection.commit()
        return self.message(message_id)

    def _history(self, message: QueuedMessage) -> tuple[Mapping[str, Any], ...]:
        rows = self.connection.execute(
            """
            SELECT role, content FROM assistant_messages
            WHERE conversation_id=? AND sequence<=? AND (
                (role='user' AND (status='completed' OR id=?))
                OR (role='assistant' AND status='completed')
            ) ORDER BY sequence
            """,
            (message.conversation_id, message.sequence, message.id),
        ).fetchall()
        return tuple({"role": str(row["role"]), "content": str(row["content"])} for row in rows)

    def _assistant_reply(self, message: QueuedMessage, content: str) -> QueuedMessage:
        now = utc_now()
        identifier = self._id("message")
        self.connection.execute(
            "INSERT INTO assistant_messages VALUES (?, ?, 'assistant', ?, 'completed', ?, '', ?, ?)",
            (
                identifier,
                message.conversation_id,
                content[:100_000],
                self._next_sequence(message.conversation_id),
                now,
                now,
            ),
        )
        self.connection.commit()
        return self.message(identifier)

    def run_next(self, conversation_id: str) -> QueuedMessage | None:
        """Run the oldest queued message through at most eight provider tool rounds."""
        with self._lock:
            queue = self.queue(conversation_id)
            if not queue:
                return None
            message = queue[0]
            conversation = self.conversation(conversation_id)
            provider = self._providers[conversation.provider]
            cancel_event = threading.Event()
            self._cancel_events[message.id] = cancel_event
            message = self._set_status(message.id, "processing")
            self._event(conversation_id, message.id, "message_start", {})
            request = AssistantRequest(
                model=conversation.model,
                messages=self._history(message),
                tools=tuple(self.broker.list_tools()),
                attachments=tuple(self.attachments(message.id)),
                allow_image_upload=conversation.allow_image_upload,
            )
            try:
                for _round_index in range(MAX_TOOL_ROUNDS):
                    if cancel_event.is_set():
                        self._set_status(message.id, "cancelled")
                        return self.message(message.id)
                    response = provider.complete(request)
                    if not response.tool_calls:
                        self._assistant_reply(message, response.content)
                        self._set_status(message.id, "completed")
                        self._event(conversation_id, message.id, "message_complete", {})
                        return self.message(message.id)
                    results: list[dict[str, Any]] = []
                    for call in response.tool_calls:
                        if cancel_event.is_set():
                            raise ToolCancelledError("Assistant message was cancelled.")
                        self._event(
                            conversation_id,
                            message.id,
                            "tool_start",
                            {"tool_call_id": call.id, "tool_name": call.name},
                        )
                        context = ToolContext(
                            actor="assistant",
                            request_id=f"assistant:{message.id}:{call.id}",
                            store=self,
                            cancel_event=cancel_event,
                        )
                        try:
                            result = self.broker.invoke(call.name, call.arguments, context)
                        except ApprovalRequiredError:
                            self._set_status(message.id, "awaiting_approval")
                            self._event(
                                conversation_id,
                                message.id,
                                "approval_required",
                                {"tool_call_id": call.id, "tool_name": call.name},
                            )
                            return self.message(message.id)
                        result_payload = {
                            "data": result.data,
                            "metadata": dict(result.metadata),
                            "summary": redact_secrets(result.summary)[:500],
                        }
                        self._event(
                            conversation_id,
                            message.id,
                            "tool_result",
                            {
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "summary": redact_secrets(result.summary)[:300],
                            },
                        )
                        if isinstance(result.data, Mapping) and (
                            result.data.get("browser_handoff_required")
                            or result.data.get("status") in {"challenge", "login_required"}
                        ):
                            self._set_status(message.id, "needs_handoff")
                            self._event(
                                conversation_id,
                                message.id,
                                "browser_handoff_required",
                                {"tool_call_id": call.id, "tool_name": call.name},
                            )
                            return self.message(message.id)
                        results.append({
                            "tool_call_id": call.id,
                            "tool_name": call.name,
                            "result": result_payload,
                        })
                    request = request.with_tool_round(response, results)
                raise AssistantError("Assistant tool round limit exceeded.")
            except ToolCancelledError:
                self._set_status(message.id, "cancelled")
                self._event(conversation_id, message.id, "message_cancelled", {})
                return self.message(message.id)
            except (ProviderError, ToolBrokerError, AssistantError, ValueError) as exc:
                self._set_status(message.id, "failed")
                self._event(
                    conversation_id,
                    message.id,
                    "message_failed",
                    {"summary": redact_secrets(str(exc))[:300]},
                )
                return self.message(message.id)
            finally:
                self._cancel_events.pop(message.id, None)
