"""HTTP boundary tests for the loopback-authenticated control service."""

from __future__ import annotations

import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from job_pipeline.assistant import AssistantResponse, ConversationService
from job_pipeline.scheduler import ScheduleService
from job_pipeline.service import ControlApplication, ControlServer, build_default_runtime
from job_pipeline.tool_broker import ToolBroker, ToolPolicy, ToolResult, ToolSpec
from job_pipeline.web_workflows import WorkflowRunner


class EchoProvider:
    name = "echo"

    def readiness(self):
        return {"ready": True, "detail": "test ready"}

    def models(self):
        return ["echo-model"]

    def complete(self, request):
        return AssistantResponse("echo: " + str(request.messages[-1]["content"]))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.broker = ToolBroker([
            ToolSpec(
                name="test.read",
                description="Return a bounded local test value.",
                policy=ToolPolicy.READ,
                input_schema={"type": "object", "additionalProperties": False},
                handler=lambda _arguments, _context: ToolResult(data={"ok": True}),
            )
        ])
        self.assistant = ConversationService(
            root / "assistant.sqlite3",
            root / "attachments",
            providers={"echo": EchoProvider()},
            broker=self.broker,
        )
        self.workflow = WorkflowRunner(self.broker, root / "workflows.sqlite3")
        self.scheduler = ScheduleService(root / "schedules.sqlite3", self.workflow, self.broker)
        application = ControlApplication(self.assistant, self.scheduler, self.broker)
        self.server = ControlServer(application, "test-token", host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.scheduler.close()
        self.workflow.close()
        self.assistant.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token="test-token", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        parsed = json.loads(data) if data else None
        return response.status, parsed

    def test_missing_and_invalid_bearer_tokens_are_rejected(self) -> None:
        self.assertEqual(self.request("GET", "/v1/health", token=None)[0], 401)
        self.assertEqual(self.request("GET", "/v1/health", token="wrong")[0], 401)
        self.assertEqual(self.request("GET", "/v1/health")[0], 200)

    def test_conversation_attachment_queue_run_and_events_routes(self) -> None:
        status, created = self.request("POST", "/v1/conversations", {
            "provider": "echo",
            "model": "echo-model",
            "title": "Test",
        })
        self.assertEqual(status, 201)
        conversation_id = created["id"]
        status, attachment = self.request(
            "POST",
            f"/v1/conversations/{conversation_id}/attachments",
            {
                "filename": "context.png",
                "mime_type": "image/png",
                "data_base64": base64.b64encode(b"\x89PNGtest").decode("ascii"),
            },
        )
        self.assertEqual(status, 201)
        status, queued = self.request(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            {"content": "hello", "attachment_ids": [attachment["id"]]},
        )
        self.assertEqual(status, 202)
        self.assertEqual(queued["status"], "queued")
        status, completed = self.request("POST", f"/v1/conversations/{conversation_id}/run", {})
        self.assertEqual(status, 200)
        self.assertEqual(completed["status"], "completed")
        messages = self.request("GET", f"/v1/conversations/{conversation_id}/messages")[1]
        self.assertEqual(messages[-1]["role"], "assistant")
        serialized_events = json.dumps(
            self.request("GET", f"/v1/conversations/{conversation_id}/events")[1]
        )
        self.assertNotIn("data_base64", serialized_events)
        self.assertNotIn("PNGtest", serialized_events)

    def test_invalid_json_unknown_routes_and_oversized_bodies_are_bounded(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "POST",
            "/v1/conversations",
            body=b"{bad",
            headers={"Authorization": "Bearer test-token", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        connection.close()
        self.assertEqual(self.request("GET", "/v1/not-real")[0], 404)

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "POST",
            "/v1/conversations",
            body=b"x",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "Content-Length": str(12 * 1024 * 1024 + 1),
            },
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 413)
        connection.close()

    def test_non_loopback_bind_is_rejected(self) -> None:
        application = ControlApplication(self.assistant, self.scheduler, self.broker)
        with self.assertRaises(ValueError):
            ControlServer(application, "token", host="0.0.0.0", port=0)

    def test_schedule_route_uses_thread_safe_storage(self) -> None:
        status, created = self.request("POST", "/v1/schedules", {
            "name": "Threaded schedule",
            "workflow": {
                "name": "threaded-read",
                "steps": [{"id": "read", "tool": "test.read", "arguments": {}}],
            },
            "recurrence": {"kind": "interval", "interval_minutes": 30},
            "enabled": True,
        })
        self.assertEqual(status, 201)
        self.assertEqual(created["name"], "Threaded schedule")

    def test_default_runtime_targets_freechain_with_its_credential_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            runtime = build_default_runtime(Path(directory), Path(directory) / "data")
            try:
                provider = runtime.assistant._providers["FreeChain"]
                self.assertEqual(provider.base_url, "http://127.0.0.1:4853/v1")
                self.assertEqual(provider.credential_env, "FREECHAIN_ACCESS_KEY")
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
