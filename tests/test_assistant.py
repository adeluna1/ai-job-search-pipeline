"""Behavior tests for durable queued, image-aware, tool-using conversations."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_pipeline.assistant import (
    AssistantRequest,
    AssistantResponse,
    ConversationService,
    OpenAICompatibleProvider,
    ProviderError,
    ToolCall,
)
from job_pipeline.tool_broker import ToolBroker, ToolPolicy, ToolResult, ToolSpec


class ScriptedProvider:
    name = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[AssistantRequest] = []

    def readiness(self):
        return {"ready": True, "detail": "test provider ready"}

    def models(self):
        return ["scripted-model"]

    def complete(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class AssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def service(self, provider=None, broker=None) -> ConversationService:
        return ConversationService(
            self.root / "assistant.sqlite3",
            self.root / "attachments",
            providers={"scripted": provider or ScriptedProvider([AssistantResponse("done")])},
            broker=broker or ToolBroker(),
        )

    def test_queue_edit_cancel_retry_and_clear_are_durable(self) -> None:
        service = self.service()
        try:
            conversation = service.create_conversation("scripted", "scripted-model", "Search")
            first = service.enqueue(conversation.id, "first")
            second = service.enqueue(conversation.id, "second")
            edited = service.edit(second.id, "second revised")
            cancelled = service.cancel(second.id)
            retried = service.retry(cancelled.id)

            self.assertEqual(edited.content, "second revised")
            self.assertEqual(cancelled.status, "cancelled")
            self.assertEqual(retried.status, "queued")
            self.assertEqual(retried.retry_of, cancelled.id)
            self.assertLess(first.sequence, second.sequence)
            self.assertEqual(service.queue(conversation.id)[0].id, first.id)

            service.clear_transcript(conversation.id)
            self.assertEqual(service.messages(conversation.id), [])
        finally:
            service.close()

    def test_image_attachments_are_content_addressed_bounded_and_linked(self) -> None:
        service = self.service()
        try:
            conversation = service.create_conversation("scripted", "scripted-model")
            image = service.attach(conversation.id, "context.png", "image/png", b"\x89PNG" + b"x" * 32)
            queued = service.enqueue(conversation.id, "use this image", [image.id])
            self.assertEqual(len(image.digest), 64)
            self.assertTrue(Path(image.local_path).is_file())
            self.assertEqual(service.attachments(queued.id)[0].id, image.id)

            with self.assertRaises(ValueError):
                service.attach(conversation.id, "bad.txt", "text/plain", b"no")
            with self.assertRaises(ValueError):
                service.enqueue(conversation.id, "too many", [image.id] * 6)
        finally:
            service.close()

    def test_provider_readiness_and_model_listing_are_structured(self) -> None:
        service = self.service()
        try:
            self.assertEqual(service.providers()[0]["name"], "scripted")
            self.assertTrue(service.providers()[0]["ready"])
            self.assertEqual(service.provider_models("scripted"), ["scripted-model"])
        finally:
            service.close()

    def test_only_cli_tool_call_runs_from_queue(self) -> None:
        calls: list[dict] = []

        def read_handler(arguments, _context):
            calls.append(arguments)
            return ToolResult(data={"text": "Recruiting Coordinator posting"}, summary="page read")

        broker = ToolBroker([ToolSpec(
            name="web.only_cli.read",
            description="Read the current only-cli page.",
            policy=ToolPolicy.READ,
            input_schema={
                "type": "object",
                "properties": {"args": {"type": "array", "items": {"type": "string"}}},
                "required": ["args"],
                "additionalProperties": False,
            },
            handler=read_handler,
        )])
        provider = ScriptedProvider([
            AssistantResponse(
                "",
                tool_calls=(ToolCall("call-1", "web.only_cli.read", {"args": ["main"]}),),
            ),
            AssistantResponse("I found a recruiting coordinator posting."),
        ])
        service = self.service(provider, broker)
        try:
            conversation = service.create_conversation("scripted", "scripted-model")
            queued = service.enqueue(conversation.id, "read the page")
            completed = service.run_next(conversation.id)

            self.assertEqual(completed.id, queued.id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(calls, [{"args": ["main"]}])
            self.assertEqual(service.messages(conversation.id)[-1].role, "assistant")
            event_types = [event["event_type"] for event in service.events(conversation.id)]
            self.assertIn("tool_start", event_types)
            self.assertIn("tool_result", event_types)
            self.assertIn("message_complete", event_types)
            self.assertEqual(service.tool_invocations()[0]["tool_name"], "web.only_cli.read")
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(provider.requests[-1].tool_results[0]["tool_call_id"], "call-1")
        finally:
            service.close()

    def test_two_messages_run_in_queue_order_and_cancelled_message_never_runs(self) -> None:
        provider = ScriptedProvider([AssistantResponse("one"), AssistantResponse("two")])
        service = self.service(provider)
        try:
            conversation = service.create_conversation("scripted", "scripted-model")
            one = service.enqueue(conversation.id, "one")
            cancelled = service.enqueue(conversation.id, "cancel me")
            two = service.enqueue(conversation.id, "two")
            service.cancel(cancelled.id)

            self.assertEqual(service.run_next(conversation.id).id, one.id)
            self.assertEqual(service.run_next(conversation.id).id, two.id)
            self.assertIsNone(service.run_next(conversation.id))
            self.assertEqual([request.messages[-1]["content"] for request in provider.requests], ["one", "two"])
        finally:
            service.close()

    def test_openai_compatible_provider_reads_key_from_environment_and_parses_tools(self) -> None:
        seen: list[dict] = []

        def transport(method, url, headers, body, timeout):
            seen.append({"method": method, "url": url, "headers": headers, "body": body})
            if url.endswith("/models"):
                return {"data": [{"id": "model-a"}]}
            return {
                "choices": [{"message": {
                    "content": "",
                    "tool_calls": [{
                        "id": "tc-1",
                        "type": "function",
                        "function": {"name": "web.only_cli.read", "arguments": "{\"args\":[]}"},
                    }],
                }}]
            }

        provider = OpenAICompatibleProvider(
            "local-provider",
            "http://127.0.0.1:9000/v1",
            credential_env="TEST_PROVIDER_KEY",
            transport=transport,
        )
        request = AssistantRequest(
            model="model-a",
            messages=({"role": "user", "content": "read"},),
            tools=(),
        )
        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "fixture-key"}):
            self.assertTrue(provider.readiness()["ready"])
            self.assertEqual(provider.models(), ["model-a"])
            response = provider.complete(request)

        self.assertEqual(response.tool_calls[0].name, "web.only_cli.read")
        self.assertNotIn("fixture-key", str(response))
        self.assertEqual(seen[-1]["headers"]["Authorization"], "Bearer fixture-key")

    def test_provider_echoed_credential_never_reaches_the_transcript_database(self) -> None:
        credential_env = "TEST_TRANSCRIPT_PROVIDER_KEY"
        credential = "synthetic-provider-key-for-redaction"

        def transport(_method, _url, _headers, _body, _timeout):
            return {
                "choices": [{"message": {
                    "content": f"provider echoed {credential}",
                    "tool_calls": [],
                }}]
            }

        provider = OpenAICompatibleProvider(
            "local-provider",
            "http://127.0.0.1:9000/v1",
            credential_env=credential_env,
            transport=transport,
        )
        database_path = self.root / "credential-redaction.sqlite3"
        service = ConversationService(
            database_path,
            self.root / "credential-redaction-attachments",
            providers={"local-provider": provider},
            broker=ToolBroker(),
        )
        try:
            conversation = service.create_conversation("local-provider", "model-a")
            service.enqueue(conversation.id, "hello")
            with patch.dict(os.environ, {credential_env: credential}, clear=False):
                service.run_next(conversation.id)

            assistant_message = service.messages(conversation.id)[-1]
            self.assertNotIn(credential, assistant_message.content)
            self.assertIn("[REDACTED]", assistant_message.content)
        finally:
            service.close()
        self.assertNotIn(credential.encode("utf-8"), database_path.read_bytes())

    def test_openai_provider_readiness_requires_an_authenticated_model_list(self) -> None:
        credential_env = "TEST_FREECHAIN_ACCESS_KEY"
        credential = "synthetic-provider-key"

        def provider(transport):
            return OpenAICompatibleProvider(
                "FreeChain",
                "http://127.0.0.1:4853/v1",
                credential_env=credential_env,
                transport=transport,
            )

        with patch.dict(os.environ, {credential_env: ""}, clear=False):
            missing = provider(lambda *_args: {"data": [{"id": "unused"}]})
            self.assertEqual(
                missing.readiness(),
                {
                    "ready": False,
                    "credential_configured": False,
                    "reachable": False,
                    "authenticated": False,
                    "model_count": 0,
                    "detail": "Provider credential is not configured",
                },
            )

        failures = (
            (
                lambda *_args: (_ for _ in ()).throw(ProviderError("connection refused")),
                False,
                False,
                "Provider is unreachable",
            ),
            (
                lambda *_args: (_ for _ in ()).throw(ProviderError("HTTP 401 unauthorized")),
                True,
                False,
                "Provider authorization failed",
            ),
            (lambda *_args: {"data": "not-a-list"}, True, True, "Provider response is invalid"),
            (lambda *_args: {"data": [{}]}, True, True, "Provider response is invalid"),
        )
        with patch.dict(os.environ, {credential_env: credential}, clear=False):
            for transport, reachable, authenticated, detail in failures:
                with self.subTest(transport=transport):
                    readiness = provider(transport).readiness()
                    self.assertFalse(readiness["ready"])
                    self.assertTrue(readiness["credential_configured"])
                    self.assertEqual(readiness["reachable"], reachable)
                    self.assertEqual(readiness["authenticated"], authenticated)
                    self.assertEqual(readiness["model_count"], 0)
                    self.assertEqual(readiness["detail"], detail)
                    self.assertNotIn(credential, str(readiness))

            seen_requests: list[dict[str, object]] = []

            def ready_transport(method, url, headers, _body, _timeout):
                seen_requests.append({"method": method, "url": url, "headers": dict(headers)})
                return {"data": [{"id": "freechain-model"}]}

            readiness = provider(ready_transport).readiness()

        self.assertTrue(readiness["ready"])
        self.assertTrue(readiness["credential_configured"])
        self.assertTrue(readiness["reachable"])
        self.assertTrue(readiness["authenticated"])
        self.assertEqual(readiness["model_count"], 1)
        self.assertEqual(readiness["detail"], "Provider ready")
        self.assertNotIn(credential, str(readiness))
        self.assertEqual(len(seen_requests), 1)
        self.assertEqual(seen_requests[0]["method"], "GET")
        self.assertTrue(str(seen_requests[0]["url"]).endswith("/models"))
        self.assertEqual(seen_requests[0]["headers"]["Authorization"], f"Bearer {credential}")

    def test_openai_provider_models_probes_directly_and_rejects_unusable_ids(self) -> None:
        credential_env = "TEST_FREECHAIN_ACCESS_KEY"
        seen_requests: list[str] = []

        def transport(method, url, _headers, _body, _timeout):
            seen_requests.append(f"{method} {url}")
            return {"data": [{"id": "  model-a  "}, {"id": ""}, {}]}

        provider = OpenAICompatibleProvider(
            "FreeChain",
            "http://127.0.0.1:4853/v1",
            credential_env=credential_env,
            transport=transport,
        )
        provider.readiness = lambda: (_ for _ in ()).throw(AssertionError("recursive readiness"))
        with patch.dict(os.environ, {credential_env: "synthetic-provider-key"}, clear=False):
            self.assertEqual(provider.models(), ["model-a"])
        self.assertEqual(seen_requests, ["GET http://127.0.0.1:4853/v1/models"])

        invalid = OpenAICompatibleProvider(
            "FreeChain",
            "http://127.0.0.1:4853/v1",
            credential_env=credential_env,
            transport=lambda *_args: {"data": [{}]},
        )
        with patch.dict(os.environ, {credential_env: "synthetic-provider-key"}, clear=False):
            with self.assertRaisesRegex(ProviderError, "model response is invalid"):
                invalid.models()

    def test_openai_provider_completion_failure_does_not_expose_transport_detail(self) -> None:
        credential_env = "TEST_FREECHAIN_ACCESS_KEY"
        credential = "synthetic-provider-key"
        seen_methods: list[str] = []

        def transport(method, *_args):
            seen_methods.append(method)
            raise ProviderError(f"upstream echoed {credential}")

        provider = OpenAICompatibleProvider(
            "FreeChain",
            "http://127.0.0.1:4853/v1",
            credential_env=credential_env,
            transport=transport,
        )
        request = AssistantRequest(
            model="model-a",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
        )
        with patch.dict(os.environ, {credential_env: credential}, clear=False):
            with self.assertRaises(ProviderError) as raised:
                provider.complete(request)
        self.assertEqual(str(raised.exception), "Provider completion request failed.")
        self.assertNotIn(credential, str(raised.exception))
        self.assertEqual(seen_methods, ["POST"])

    def test_openai_provider_auto_recovers_with_an_advertised_concrete_model(self) -> None:
        credential_env = "TEST_FREECHAIN_ACCESS_KEY"
        credential = "synthetic-provider-key"
        seen_requests: list[tuple[str, str]] = []

        def transport(method, url, _headers, body, _timeout):
            model = str((body or {}).get("model", ""))
            seen_requests.append((method, model))
            if method == "GET":
                return {
                    "data": [
                        {"id": "auto"},
                        {"id": "stealth/preview"},
                        {"id": "gemini-3.5-flash"},
                    ]
                }
            if model == "auto":
                raise ProviderError(f"temporary upstream overload echoed {credential}")
            return {"choices": [{"message": {"content": "recovered", "tool_calls": []}}]}

        provider = OpenAICompatibleProvider(
            "FreeChain",
            "http://127.0.0.1:4853/v1",
            credential_env=credential_env,
            transport=transport,
        )
        request = AssistantRequest(
            model="auto",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
        )
        with patch.dict(os.environ, {credential_env: credential}, clear=False):
            response = provider.complete(request)
            cached_response = provider.complete(request)

        self.assertEqual(response.content, "recovered")
        self.assertEqual(cached_response.content, "recovered")
        self.assertEqual(
            seen_requests,
            [
                ("POST", "auto"),
                ("GET", ""),
                ("POST", "gemini-3.5-flash"),
                ("POST", "gemini-3.5-flash"),
            ],
        )
        self.assertNotIn(credential, str(response))

    def test_openai_provider_completion_does_not_probe_models(self) -> None:
        credential_env = "TEST_FREECHAIN_ACCESS_KEY"
        seen_requests: list[str] = []

        def transport(method, url, _headers, _body, _timeout):
            seen_requests.append(f"{method} {url}")
            if method == "GET":
                return {"data": [{"id": "model-a"}]}
            return {"choices": [{"message": {"content": "complete", "tool_calls": []}}]}

        provider = OpenAICompatibleProvider(
            "FreeChain",
            "http://127.0.0.1:4853/v1",
            credential_env=credential_env,
            transport=transport,
        )
        request = AssistantRequest(
            model="model-a",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
        )
        with patch.dict(os.environ, {credential_env: "synthetic-provider-key"}, clear=False):
            response = provider.complete(request)
        self.assertEqual(response.content, "complete")
        self.assertEqual(
            seen_requests,
            ["POST http://127.0.0.1:4853/v1/chat/completions"],
        )

    def test_openai_provider_safe_failures_drop_transport_exception_chains(self) -> None:
        credential_env = "TEST_SAFE_CHAIN_ACCESS_KEY"
        credential = "synthetic-provider-key"
        raw_detail = "synthetic raw transport detail"

        def failing_transport(*_args):
            outer = ProviderError(f"transport failed with {credential}")
            outer.__cause__ = RuntimeError(raw_detail)
            raise outer

        def chain_text(error: BaseException) -> str:
            pending = [error]
            seen: set[int] = set()
            values: list[str] = []
            while pending:
                current = pending.pop()
                if id(current) in seen:
                    continue
                seen.add(id(current))
                values.append(str(current))
                if current.__cause__ is not None:
                    pending.append(current.__cause__)
                if current.__context__ is not None:
                    pending.append(current.__context__)
            return " | ".join(values)

        def provider():
            return OpenAICompatibleProvider(
                "FreeChain",
                "http://127.0.0.1:4853/v1",
                credential_env=credential_env,
                transport=failing_transport,
            )

        request = AssistantRequest(
            model="model-a",
            messages=({"role": "user", "content": "hello"},),
            tools=(),
        )
        with patch.dict(os.environ, {credential_env: credential}, clear=False):
            readiness = provider().readiness()
            self.assertFalse(readiness["ready"])
            self.assertNotIn(credential, str(readiness))
            self.assertNotIn(raw_detail, str(readiness))

            for operation in (lambda: provider().models(), lambda: provider().complete(request)):
                with self.subTest(operation=operation), self.assertRaises(ProviderError) as raised:
                    operation()
                self.assertIsNone(raised.exception.__cause__)
                self.assertIsNone(raised.exception.__context__)
                self.assertNotIn(credential, chain_text(raised.exception))
                self.assertNotIn(raw_detail, chain_text(raised.exception))

    def test_openai_provider_rejects_plaintext_remote_base_url(self) -> None:
        with self.assertRaises(ProviderError):
            OpenAICompatibleProvider("unsafe", "http://public.example/v1", credential_env="KEY")


if __name__ == "__main__":
    unittest.main()
