"""Behavior tests for resumable, broker-backed web workflows."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from job_pipeline.tool_broker import (
    ApprovalRequiredError,
    ToolBroker,
    ToolContext,
    ToolPolicy,
    ToolResult,
    ToolSpec,
)
from job_pipeline.web_workflows import (
    WorkflowDefinition,
    WorkflowRunner,
    WorkflowStep,
    WorkflowValidationError,
)


def value_tool(name: str, calls: list[tuple[str, dict]], *, fail_first: bool = False):
    attempts = {"count": 0}

    def handler(arguments, _context):
        attempts["count"] += 1
        calls.append((name, arguments))
        if fail_first and attempts["count"] == 1:
            raise RuntimeError("temporary test failure")
        return ToolResult(data={"value": arguments["value"]}, summary=f"{name} complete")

    return ToolSpec(
        name=name,
        description="Return one test value.",
        policy=ToolPolicy.READ,
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string", "maxLength": 100}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=handler,
    )


class WebWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.calls: list[tuple[str, dict]] = []
        self.broker = ToolBroker([
            value_tool("test.seed", self.calls),
            value_tool("test.retry", self.calls, fail_first=True),
        ])
        self.runner = WorkflowRunner(
            self.broker,
            Path(self.temp.name) / "workflows.sqlite3",
            retry_delay_seconds=0,
        )
        self.context = ToolContext(actor="workflow", request_id="workflow-test")

    def tearDown(self) -> None:
        self.runner.close()
        self.temp.cleanup()

    def test_validation_rejects_unknown_dependencies_and_expression_language(self) -> None:
        unknown = WorkflowDefinition("bad", (WorkflowStep("one", "test.seed", {}, ("missing",)),))
        with self.assertRaises(WorkflowValidationError):
            self.runner.validate(unknown)

        expression = WorkflowDefinition(
            "bad-expression",
            (WorkflowStep("one", "test.seed", {"value": "${one.value + 1}"}),),
        )
        with self.assertRaises(WorkflowValidationError):
            self.runner.validate(expression)

    def test_dry_run_validates_and_plans_without_executing_tools(self) -> None:
        definition = WorkflowDefinition(
            "dry",
            (WorkflowStep("seed", "test.seed", {"value": "candidate"}),),
        )
        result = self.runner.run(definition, self.context, dry_run=True)
        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.step_states, {"seed": "planned"})
        self.assertEqual(self.calls, [])

    def test_interpolation_retry_and_structured_dataset_are_deterministic(self) -> None:
        definition = WorkflowDefinition(
            "retry",
            (
                WorkflowStep("seed", "test.seed", {"value": "coordinator"}),
                WorkflowStep(
                    "enrich",
                    "test.retry",
                    {"value": "${seed.data.value}"},
                    depends_on=("seed",),
                    max_attempts=2,
                ),
            ),
        )
        result = self.runner.run(definition, self.context)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.outputs["enrich"]["data"], {"value": "coordinator"})
        self.assertEqual([name for name, _ in self.calls], ["test.seed", "test.retry", "test.retry"])
        self.assertEqual(self.runner.dataset(result.run_id)[-1]["step_id"], "enrich")

    def test_resume_skips_completed_steps_after_a_failure(self) -> None:
        def fail(_arguments, _context):
            raise RuntimeError("still unavailable")

        self.broker.register(ToolSpec(
            name="test.fail",
            description="Fail for resume testing.",
            policy=ToolPolicy.READ,
            input_schema={"type": "object", "additionalProperties": False},
            handler=fail,
        ))
        definition = WorkflowDefinition(
            "resume",
            (
                WorkflowStep("seed", "test.seed", {"value": "once"}),
                WorkflowStep("blocked", "test.fail", {}, depends_on=("seed",), max_attempts=1),
            ),
        )
        first = self.runner.run(definition, self.context)
        resumed = self.runner.run(definition, self.context, run_id=first.run_id)
        self.assertEqual(first.status, "failed")
        self.assertEqual(resumed.status, "failed")
        self.assertEqual([name for name, _ in self.calls].count("test.seed"), 1)

    def test_cancellation_stops_before_the_next_step(self) -> None:
        cancelled = threading.Event()

        def cancel_handler(arguments, _context):
            cancelled.set()
            return ToolResult(data={"value": arguments["value"]})

        self.broker.register(ToolSpec(
            name="test.cancel",
            description="Cancel the enclosing workflow.",
            policy=ToolPolicy.READ,
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            handler=cancel_handler,
        ))
        definition = WorkflowDefinition(
            "cancel",
            (
                WorkflowStep("first", "test.cancel", {"value": "stop"}),
                WorkflowStep("second", "test.seed", {"value": "never"}, depends_on=("first",)),
            ),
        )
        context = ToolContext(
            actor="workflow",
            request_id="cancel-test",
            cancel_event=cancelled,
        )
        result = self.runner.run(definition, context)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.step_states["second"], "cancelled")

    def test_external_action_keeps_the_brokers_exact_approval_boundary(self) -> None:
        action = value_tool("test.action", self.calls)
        self.broker.register(ToolSpec(
            name=action.name,
            description=action.description,
            policy=ToolPolicy.EXTERNAL_ACTION,
            input_schema=action.input_schema,
            handler=action.handler,
        ))
        definition = WorkflowDefinition(
            "approval",
            (WorkflowStep("send", "test.action", {"value": "draft-42"}, max_attempts=1),),
        )
        result = self.runner.run(definition, self.context)
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(result.step_states["send"], "awaiting_approval")
        self.assertIsInstance(result.error, str)
        self.assertNotIn("draft-42", result.error)


if __name__ == "__main__":
    unittest.main()
