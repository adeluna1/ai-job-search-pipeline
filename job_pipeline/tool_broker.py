"""Typed, policy-aware tool execution for assistants and scheduled workflows.

The broker is the single authority boundary between model-requested tool calls
and application capabilities. It accepts registered names and structured JSON
arguments only, enforces exact approval for representational actions, caps
outputs, and writes content-free audit metadata to ``JobStore``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Mapping

from .util import redact_secrets


class ToolBrokerError(RuntimeError):
    """Base class for bounded tool broker failures."""


class UnknownToolError(ToolBrokerError):
    """Raised when an unregistered tool name is requested."""


class InvalidToolArgumentsError(ToolBrokerError):
    """Raised before execution when structured arguments violate the tool schema."""


class ApprovalRequiredError(ToolBrokerError):
    """Raised when an external action lacks its exact invocation approval."""


class ToolTimeoutError(ToolBrokerError):
    """Raised when a tool does not finish within its registered deadline."""


class ToolCancelledError(ToolBrokerError):
    """Raised when a caller cancels before tool execution begins."""


class ToolOutputTooLargeError(ToolBrokerError):
    """Raised before an oversized tool result reaches a model or renderer."""


class ToolExecutionError(ToolBrokerError):
    """Raised when a registered handler fails."""


class ToolPolicy(StrEnum):
    """Authority classes used by assistants, schedules, and approval surfaces."""

    READ = "read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_DRAFT = "external_draft"
    EXTERNAL_ACTION = "external_action"


@dataclass(frozen=True)
class ToolResult:
    """Structured data returned by a registered tool handler."""

    data: Any = None
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolContext:
    """Per-invocation actor, request, approval, cancellation, and audit context."""

    actor: str
    request_id: str
    store: Any | None = None
    approval_digest: str = ""
    cancel_event: threading.Event | None = None


ToolHandler = Callable[[dict[str, Any], ToolContext], ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """One explicitly registered tool contract."""

    name: str
    description: str
    policy: ToolPolicy
    input_schema: dict[str, Any]
    handler: ToolHandler
    timeout_seconds: float = 30.0
    max_output_bytes: int = 262_144

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 128:
            raise ValueError("Tool names must contain between 1 and 128 characters.")
        if self.timeout_seconds <= 0:
            raise ValueError("Tool timeout must be positive.")
        if self.max_output_bytes <= 0:
            raise ValueError("Tool output cap must be positive.")


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise InvalidToolArgumentsError("Tool arguments must be JSON serializable.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate_value(value: Any, schema: Mapping[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected and not _matches_type(value, str(expected)):
        raise InvalidToolArgumentsError(f"{path} must be {expected}.")
    if "enum" in schema and value not in schema["enum"]:
        raise InvalidToolArgumentsError(f"{path} is not an allowed value.")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise InvalidToolArgumentsError(f"{path} is too short.")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise InvalidToolArgumentsError(f"{path} is too long.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise InvalidToolArgumentsError(f"{path} is below its minimum.")
        if "maximum" in schema and value > schema["maximum"]:
            raise InvalidToolArgumentsError(f"{path} exceeds its maximum.")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise InvalidToolArgumentsError(f"{path} has too many items.")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_value(item, item_schema, f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, Mapping) else {}
        for required in schema.get("required", []):
            if required not in value:
                raise InvalidToolArgumentsError(f"{path}.{required} is required.")
        if schema.get("additionalProperties") is False:
            unexpected = sorted(set(value) - set(properties))
            if unexpected:
                raise InvalidToolArgumentsError(
                    f"{path} contains unsupported field: {unexpected[0]}."
                )
        for key, item in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, Mapping):
                _validate_value(item, child_schema, f"{path}.{key}")


class ToolBroker:
    """Register and invoke typed tools through one policy and audit boundary."""

    def __init__(self, specs: list[ToolSpec] | tuple[ToolSpec, ...] | None = None):
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs or ():
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        """Register one unique tool specification."""
        if spec.name in self._specs:
            raise ValueError(f"Tool is already registered: {spec.name}")
        self._specs[spec.name] = spec

    def list_tools(self) -> list[dict[str, Any]]:
        """Return model-safe contracts without exposing Python handlers."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "policy": spec.policy.value,
                "input_schema": spec.input_schema,
            }
            for spec in sorted(self._specs.values(), key=lambda item: item.name)
        ]

    @staticmethod
    def approval_digest(tool_name: str, arguments: Mapping[str, Any]) -> str:
        """Bind a human approval to one exact tool name and argument object."""
        return _digest({"tool": tool_name, "arguments": dict(arguments)})

    def _audit(
        self,
        spec: ToolSpec,
        context: ToolContext,
        arguments_digest: str,
        *,
        status: str,
        started: float,
        result_digest: str = "",
        summary: str = "",
    ) -> None:
        if context.store is None:
            return
        context.store.record_tool_invocation(
            request_id=context.request_id,
            actor=context.actor,
            tool_name=spec.name,
            policy=spec.policy.value,
            status=status,
            arguments_digest=arguments_digest,
            result_digest=result_digest,
            summary=redact_secrets(summary).replace("\r", " ").replace("\n", " ")[:500],
            duration_ms=round((time.monotonic() - started) * 1000),
        )

    def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Validate, authorize, execute, cap, and audit one registered tool call."""
        spec = self._specs.get(tool_name)
        if spec is None:
            raise UnknownToolError(f"Unknown tool: {tool_name}")
        started = time.monotonic()
        normalized_arguments = dict(arguments)
        arguments_digest = _digest(normalized_arguments)

        try:
            _validate_value(normalized_arguments, spec.input_schema, "arguments")
        except InvalidToolArgumentsError as exc:
            self._audit(
                spec,
                context,
                arguments_digest,
                status="invalid_arguments",
                started=started,
                summary=str(exc),
            )
            raise

        if context.cancel_event is not None and context.cancel_event.is_set():
            self._audit(
                spec,
                context,
                arguments_digest,
                status="cancelled",
                started=started,
                summary="Cancelled before execution.",
            )
            raise ToolCancelledError("Tool call was cancelled before execution.")

        if spec.policy is ToolPolicy.EXTERNAL_ACTION:
            expected = self.approval_digest(spec.name, normalized_arguments)
            if not context.approval_digest or not hmac.compare_digest(
                context.approval_digest, expected
            ):
                self._audit(
                    spec,
                    context,
                    arguments_digest,
                    status="approval_required",
                    started=started,
                    summary="Exact approval is required.",
                )
                raise ApprovalRequiredError(
                    "This external action requires approval for its exact arguments."
                )

        outcome: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def execute() -> None:
            try:
                outcome.put(("result", spec.handler(normalized_arguments, context)))
            except BaseException as exc:
                outcome.put(("error", exc))

        worker = threading.Thread(
            target=execute,
            name=f"tool-{spec.name[:48]}",
            daemon=True,
        )
        worker.start()
        try:
            kind, value = outcome.get(timeout=spec.timeout_seconds)
        except queue.Empty as exc:
            self._audit(
                spec,
                context,
                arguments_digest,
                status="timed_out",
                started=started,
                summary=f"Tool exceeded {spec.timeout_seconds:g} seconds.",
            )
            raise ToolTimeoutError(
                f"Tool exceeded its {spec.timeout_seconds:g} second deadline."
            ) from exc

        if kind == "error":
            message = redact_secrets(str(value))
            self._audit(
                spec,
                context,
                arguments_digest,
                status="failed",
                started=started,
                summary=message,
            )
            raise ToolExecutionError(message) from value
        if not isinstance(value, ToolResult):
            self._audit(
                spec,
                context,
                arguments_digest,
                status="failed",
                started=started,
                summary="Handler returned an invalid result type.",
            )
            raise ToolExecutionError("Tool handler returned an invalid result type.")

        serialized = _stable_json({"data": value.data, "metadata": dict(value.metadata)})
        if len(serialized.encode("utf-8")) > spec.max_output_bytes:
            self._audit(
                spec,
                context,
                arguments_digest,
                status="output_too_large",
                started=started,
                result_digest=_digest(serialized),
                summary="Tool result exceeded its output cap.",
            )
            raise ToolOutputTooLargeError("Tool result exceeded its registered output cap.")

        self._audit(
            spec,
            context,
            arguments_digest,
            status="succeeded",
            started=started,
            result_digest=_digest(serialized),
            summary=value.summary,
        )
        return value
