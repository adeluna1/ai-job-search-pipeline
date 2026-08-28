"""Loopback-authenticated control API for Electron and local automation."""

from __future__ import annotations

import argparse
import base64
import binascii
import hmac
import ipaddress
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from .app_tools import JobPipelineToolAdapter
from .assistant import ConversationService, OpenAICompatibleProvider
from .integrations.only_cli import OnlyCliAdapter
from .scheduler import Recurrence, ScheduleService
from .tool_broker import ToolBroker
from .util import redact_secrets
from .web_workflows import WorkflowDefinition, WorkflowRunner, WorkflowStep


MAX_REQUEST_BYTES = 12 * 1024 * 1024


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _public_attachment(value: Any) -> dict[str, Any]:
    payload = _jsonable(value)
    payload.pop("local_path", None)
    return payload


def _workflow_from_payload(payload: Mapping[str, Any]) -> WorkflowDefinition:
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("Workflow steps must be an array.")
    steps = tuple(
        WorkflowStep(
            id=str(item.get("id", "")),
            tool=str(item.get("tool", "")),
            arguments=dict(item.get("arguments") or {}),
            depends_on=tuple(str(value) for value in item.get("depends_on", [])),
            max_attempts=int(item.get("max_attempts", 2)),
        )
        for item in raw_steps
        if isinstance(item, Mapping)
    )
    if len(steps) != len(raw_steps):
        raise ValueError("Every workflow step must be an object.")
    return WorkflowDefinition(str(payload.get("name", "")), steps)


def _recurrence_from_payload(payload: Mapping[str, Any]) -> Recurrence:
    kind = str(payload.get("kind", ""))
    if kind == "interval":
        return Recurrence.interval(int(payload.get("interval_minutes", 0)))
    return Recurrence.daily(
        str(payload.get("local_time", "")),
        str(payload.get("timezone_name", "")),
    )


class ControlApplication:
    """Route-level adapter over assistant, scheduler, workflow, and tool services."""

    def __init__(
        self,
        assistant: ConversationService,
        scheduler: ScheduleService,
        broker: ToolBroker,
    ):
        self.assistant = assistant
        self.scheduler = scheduler
        self.broker = broker

    def get(self, path: str) -> tuple[int, Any]:
        if path == "/v1/health":
            return 200, {"ok": True, "service": "expedient-control", "schema_version": 1}
        if path == "/v1/providers":
            return 200, self.assistant.providers()
        provider_match = re.fullmatch(r"/v1/providers/([^/]+)/models", path)
        if provider_match:
            return 200, self.assistant.provider_models(unquote(provider_match.group(1)))
        if path == "/v1/tools":
            return 200, self.broker.list_tools()
        if path == "/v1/conversations":
            return 200, _jsonable(self.assistant.conversations())
        conversation_messages = re.fullmatch(r"/v1/conversations/([^/]+)/messages", path)
        if conversation_messages:
            return 200, _jsonable(
                self.assistant.messages(unquote(conversation_messages.group(1)))
            )
        conversation_events = re.fullmatch(r"/v1/conversations/([^/]+)/events", path)
        if conversation_events:
            return 200, self.assistant.events(unquote(conversation_events.group(1)))
        conversation_queue = re.fullmatch(r"/v1/conversations/([^/]+)/queue", path)
        if conversation_queue:
            return 200, _jsonable(self.assistant.queue(unquote(conversation_queue.group(1))))
        if path == "/v1/schedules":
            return 200, _jsonable(self.scheduler.list())
        history_match = re.fullmatch(r"/v1/schedules/(\d+)/history", path)
        if history_match:
            return 200, self.scheduler.history(int(history_match.group(1)))
        raise KeyError(path)

    def post(self, path: str, payload: Mapping[str, Any]) -> tuple[int, Any]:
        if path == "/v1/conversations":
            value = self.assistant.create_conversation(
                str(payload.get("provider", "")),
                str(payload.get("model", "")),
                str(payload.get("title", "New conversation")),
                allow_image_upload=bool(payload.get("allow_image_upload", False)),
            )
            return 201, _jsonable(value)
        attachment_match = re.fullmatch(r"/v1/conversations/([^/]+)/attachments", path)
        if attachment_match:
            encoded = payload.get("data_base64")
            if not isinstance(encoded, str):
                raise ValueError("Attachment data must be base64 text.")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Attachment data is invalid base64.") from exc
            value = self.assistant.attach(
                unquote(attachment_match.group(1)),
                str(payload.get("filename", "image")),
                str(payload.get("mime_type", "")),
                content,
            )
            return 201, _public_attachment(value)
        enqueue_match = re.fullmatch(r"/v1/conversations/([^/]+)/messages", path)
        if enqueue_match:
            attachment_ids = payload.get("attachment_ids", [])
            if not isinstance(attachment_ids, list):
                raise ValueError("Attachment identifiers must be an array.")
            value = self.assistant.enqueue(
                unquote(enqueue_match.group(1)),
                str(payload.get("content", "")),
                [str(item) for item in attachment_ids],
            )
            return 202, _jsonable(value)
        run_match = re.fullmatch(r"/v1/conversations/([^/]+)/run", path)
        if run_match:
            value = self.assistant.run_next(unquote(run_match.group(1)))
            return 200, _jsonable(value)
        cancel_match = re.fullmatch(r"/v1/messages/([^/]+)/cancel", path)
        if cancel_match:
            return 200, _jsonable(self.assistant.cancel(unquote(cancel_match.group(1))))
        retry_match = re.fullmatch(r"/v1/messages/([^/]+)/retry", path)
        if retry_match:
            return 202, _jsonable(self.assistant.retry(unquote(retry_match.group(1))))
        if path == "/v1/workflows/dry-run":
            definition = _workflow_from_payload(payload)
            result = self.scheduler.runner.run(
                definition,
                self._workflow_context("dry-run"),
                dry_run=True,
            )
            return 200, _jsonable(result)
        if path == "/v1/workflows/run":
            definition = _workflow_from_payload(payload)
            result = self.scheduler.runner.run(
                definition,
                self._workflow_context("interactive-run"),
            )
            return 200, _jsonable(result)
        if path == "/v1/schedules":
            workflow = payload.get("workflow")
            recurrence = payload.get("recurrence")
            if not isinstance(workflow, Mapping) or not isinstance(recurrence, Mapping):
                raise ValueError("Schedule workflow and recurrence are required.")
            value = self.scheduler.create(
                str(payload.get("name", "")),
                _workflow_from_payload(workflow),
                _recurrence_from_payload(recurrence),
                enabled=bool(payload.get("enabled", True)),
            )
            return 201, _jsonable(value)
        schedule_toggle = re.fullmatch(r"/v1/schedules/(\d+)/enabled", path)
        if schedule_toggle:
            return 200, _jsonable(
                self.scheduler.set_enabled(
                    int(schedule_toggle.group(1)), bool(payload.get("enabled", False))
                )
            )
        if path == "/v1/schedules/run-due":
            return 200, self.scheduler.run_due(now=datetime.now(timezone.utc))
        raise KeyError(path)

    @staticmethod
    def _workflow_context(label: str):
        from .tool_broker import ToolContext

        return ToolContext(actor="control-service", request_id=f"control:{label}")

    def patch(self, path: str, payload: Mapping[str, Any]) -> tuple[int, Any]:
        edit_match = re.fullmatch(r"/v1/messages/([^/]+)", path)
        if edit_match:
            return 200, _jsonable(
                self.assistant.edit(
                    unquote(edit_match.group(1)), str(payload.get("content", ""))
                )
            )
        raise KeyError(path)

    def delete(self, path: str) -> tuple[int, Any]:
        clear_match = re.fullmatch(r"/v1/conversations/([^/]+)/messages", path)
        if clear_match:
            self.assistant.clear_transcript(unquote(clear_match.group(1)))
            return 200, {"cleared": True}
        raise KeyError(path)


class _Handler(BaseHTTPRequestHandler):
    server_version = "ExpedientControl/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    @property
    def control_server(self) -> "ControlServer":
        return self.server  # type: ignore[return-value]

    def _authorized(self) -> bool:
        expected = f"Bearer {self.control_server.token}"
        actual = self.headers.get("Authorization", "")
        return hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8"))

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Mapping[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Request Content-Length is invalid.") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise OverflowError("Request body exceeds the service cap.")
        data = self.rfile.read(length)
        try:
            payload = json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid JSON.") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("Request JSON must be an object.")
        return payload

    def _dispatch(self, method: str) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        path = urlsplit(self.path).path.rstrip("/") or "/"
        try:
            if method == "GET":
                status, result = self.control_server.application.get(path)
            elif method == "POST":
                status, result = self.control_server.application.post(path, self._body())
            elif method == "PATCH":
                status, result = self.control_server.application.patch(path, self._body())
            elif method == "DELETE":
                status, result = self.control_server.application.delete(path)
            else:
                self._send(405, {"error": "method_not_allowed"})
                return
        except OverflowError:
            self.close_connection = True
            self._send(413, {"error": "request_too_large"})
        except KeyError:
            self._send(404, {"error": "not_found"})
        except ValueError as exc:
            self._send(400, {"error": redact_secrets(str(exc))[:500]})
        except Exception as exc:
            self._send(500, {"error": redact_secrets(str(exc))[:500]})
        else:
            self._send(status, result)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


class ControlServer(ThreadingHTTPServer):
    """HTTP server restricted to a loopback interface and random bearer token."""

    daemon_threads = True

    def __init__(
        self,
        application: ControlApplication,
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ):
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host.casefold() == "localhost"
        if not loopback:
            raise ValueError("Control service must bind to a loopback address.")
        if not token:
            raise ValueError("Control service bearer token is required.")
        self.application = application
        self.token = token
        super().__init__((host, int(port)), _Handler)


@dataclass
class ControlRuntime:
    """Owned backend components closed together on service shutdown."""

    application: ControlApplication
    assistant: ConversationService
    scheduler: ScheduleService
    workflow: WorkflowRunner

    def close(self) -> None:
        self.scheduler.close()
        self.workflow.close()
        self.assistant.close()


def build_default_runtime(project_root: Path, data_root: Path) -> ControlRuntime:
    """Compose providers, only-cli tools, workflows, schedules, and conversation state."""
    project_root = project_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    only_cli = OnlyCliAdapter(
        project_root,
        node_binary=os.environ.get("ONLY_CLI_NODE") or None,
        cli_entry=Path(os.environ["ONLY_CLI_ENTRY"]) if os.environ.get("ONLY_CLI_ENTRY") else None,
        session_dir=data_root / "only-cli",
    )
    job_tools = JobPipelineToolAdapter(project_root)
    broker = ToolBroker([*only_cli.tool_specs(), *job_tools.tool_specs()])
    provider_url = os.environ.get("EXPEDIENT_PROVIDER_URL", "http://127.0.0.1:4853/v1")
    provider_key_env = os.environ.get("EXPEDIENT_PROVIDER_KEY_ENV", "FREECHAIN_ACCESS_KEY")
    providers = {
        "FreeChain": OpenAICompatibleProvider(
            "FreeChain",
            provider_url,
            credential_env=provider_key_env,
        )
    }
    assistant = ConversationService(
        data_root / "assistant.sqlite3",
        data_root / "attachments",
        providers=providers,
        broker=broker,
    )
    workflow = WorkflowRunner(broker, data_root / "workflows.sqlite3")
    scheduler = ScheduleService(data_root / "schedules.sqlite3", workflow, broker)
    return ControlRuntime(
        application=ControlApplication(assistant, scheduler, broker),
        assistant=assistant,
        scheduler=scheduler,
        workflow=workflow,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Expedient control service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)
    token = os.environ.get("EXPEDIENT_CONTROL_TOKEN") or secrets.token_urlsafe(32)
    data_root = args.data_root or Path(
        os.environ.get("EXPEDIENT_DATA_DIR", str(args.project_root / "data" / "control"))
    )
    runtime = build_default_runtime(args.project_root, data_root)
    server = ControlServer(runtime.application, token, host=args.host, port=args.port)
    print(json.dumps({
        "event": "expedient_control_ready",
        "host": server.server_address[0],
        "port": server.server_address[1],
    }), flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
