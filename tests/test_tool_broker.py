"""Behavior tests for the typed, approval-aware agent tool broker."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from job_pipeline.storage import JobStore
from job_pipeline.tool_broker import (
    ApprovalRequiredError,
    InvalidToolArgumentsError,
    ToolBroker,
    ToolCancelledError,
    ToolContext,
    ToolOutputTooLargeError,
    ToolPolicy,
    ToolResult,
    ToolSpec,
    ToolTimeoutError,
    UnknownToolError,
)


def echo_spec(*, policy: ToolPolicy = ToolPolicy.READ, max_output_bytes: int = 1024):
    """Return a real broker tool whose result reflects one validated string."""

    def handler(arguments, _context):
        return ToolResult(data={"value": arguments["value"]}, summary="echo complete")

    return ToolSpec(
        name="test.echo",
        description="Echo one bounded string.",
        policy=policy,
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string", "maxLength": 128}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=handler,
        max_output_bytes=max_output_bytes,
    )


class ToolBrokerTests(unittest.TestCase):
    """Exercise registration, validation, approval, limits, and audit behavior."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.context = ToolContext(actor="assistant", request_id="request-1", store=self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_unknown_tool_is_rejected(self) -> None:
        with self.assertRaises(UnknownToolError):
            ToolBroker().invoke("shell", {}, self.context)

    def test_arguments_are_checked_before_handler_execution(self) -> None:
        broker = ToolBroker([echo_spec()])
        with self.assertRaises(InvalidToolArgumentsError):
            broker.invoke("test.echo", {"value": "ok", "command": "extra"}, self.context)
        self.assertEqual(self.store.tool_invocations()[0]["status"], "invalid_arguments")

    def test_external_action_requires_an_exact_approval_digest(self) -> None:
        broker = ToolBroker([echo_spec(policy=ToolPolicy.EXTERNAL_ACTION)])
        arguments = {"value": "application-42"}
        with self.assertRaises(ApprovalRequiredError):
            broker.invoke("test.echo", arguments, self.context)

        approved = ToolContext(
            actor="assistant",
            request_id="request-2",
            store=self.store,
            approval_digest=broker.approval_digest("test.echo", arguments),
        )
        result = broker.invoke("test.echo", arguments, approved)
        self.assertEqual(result.data, {"value": "application-42"})

    def test_result_size_is_capped_before_it_reaches_the_caller(self) -> None:
        broker = ToolBroker([echo_spec(max_output_bytes=32)])
        with self.assertRaises(ToolOutputTooLargeError):
            broker.invoke("test.echo", {"value": "x" * 64}, self.context)
        self.assertEqual(self.store.tool_invocations()[-1]["status"], "output_too_large")

    def test_timeout_and_pre_cancel_are_distinct_audit_statuses(self) -> None:
        def slow_handler(_arguments, _context):
            time.sleep(0.2)
            return ToolResult(data={"done": True}, summary="slow complete")

        broker = ToolBroker([
            ToolSpec(
                name="test.slow",
                description="Wait beyond the broker deadline.",
                policy=ToolPolicy.READ,
                input_schema={"type": "object", "additionalProperties": False},
                handler=slow_handler,
                timeout_seconds=0.02,
            )
        ])
        with self.assertRaises(ToolTimeoutError):
            broker.invoke("test.slow", {}, self.context)

        cancelled = threading.Event()
        cancelled.set()
        cancelled_context = ToolContext(
            actor="assistant",
            request_id="request-3",
            store=self.store,
            cancel_event=cancelled,
        )
        with self.assertRaises(ToolCancelledError):
            broker.invoke("test.slow", {}, cancelled_context)
        self.assertEqual(
            [row["status"] for row in self.store.tool_invocations()[-2:]],
            ["timed_out", "cancelled"],
        )

    def test_audit_records_digests_and_bounded_summary_without_arguments(self) -> None:
        broker = ToolBroker([echo_spec()])
        secret_value = "private-token-value"
        broker.invoke("test.echo", {"value": secret_value}, self.context)
        row = self.store.tool_invocations()[-1]
        self.assertEqual(row["tool_name"], "test.echo")
        self.assertEqual(row["status"], "succeeded")
        self.assertEqual(len(row["arguments_digest"]), 64)
        self.assertEqual(len(row["result_digest"]), 64)
        self.assertNotIn(secret_value, str(row))


if __name__ == "__main__":
    unittest.main()
