"""Behavior tests for restart-safe, policy-bounded scheduled workflows."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_pipeline.scheduler import Recurrence, ScheduleService, ScheduleValidationError
from job_pipeline.tool_broker import ToolBroker, ToolContext, ToolPolicy, ToolResult, ToolSpec
from job_pipeline.web_workflows import WorkflowDefinition, WorkflowRunner, WorkflowStep


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls: list[str] = []

        def local_handler(arguments, _context):
            self.calls.append(arguments["value"])
            return ToolResult(data={"draft_id": arguments["value"]}, summary="draft prepared")

        def send_handler(arguments, _context):
            self.calls.append("sent:" + arguments["value"])
            return ToolResult(data={"sent": True})

        self.broker = ToolBroker([
            ToolSpec(
                name="jobs.prepare_draft",
                description="Prepare a local application draft.",
                policy=ToolPolicy.EXTERNAL_DRAFT,
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                handler=local_handler,
            ),
            ToolSpec(
                name="jobs.submit",
                description="Submit an external application.",
                policy=ToolPolicy.EXTERNAL_ACTION,
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                handler=send_handler,
            ),
        ])
        self.runner = WorkflowRunner(
            self.broker,
            self.root / "workflow.sqlite3",
            retry_delay_seconds=0,
        )
        self.database = self.root / "schedules.sqlite3"
        self.service = ScheduleService(self.database, self.runner, self.broker)
        self.workflow = WorkflowDefinition(
            "draft",
            (WorkflowStep("draft", "jobs.prepare_draft", {"value": "candidate-42"}),),
        )

    def tearDown(self) -> None:
        self.service.close()
        self.runner.close()
        self.temp.cleanup()

    def test_interval_schedule_persists_across_restart_and_coalesces_missed_runs(self) -> None:
        now = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
        created = self.service.create(
            "Every hour",
            self.workflow,
            Recurrence.interval(60),
            now=now,
        )
        self.service.close()
        self.service = ScheduleService(self.database, self.runner, self.broker)

        runs = self.service.run_due(now=now + timedelta(hours=4, minutes=5))
        refreshed = self.service.get(created.id)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["status"], "succeeded")
        self.assertEqual(self.calls, ["candidate-42"])
        self.assertGreater(refreshed.next_run_at, now + timedelta(hours=4, minutes=5))

    def test_daily_recurrence_uses_named_local_timezone(self) -> None:
        now = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
        created = self.service.create(
            "Morning hunt",
            self.workflow,
            Recurrence.daily("09:30", "America/Los_Angeles"),
            now=now,
        )
        self.assertEqual(created.next_run_at, datetime(2026, 8, 25, 16, 30, tzinfo=timezone.utc))

    def test_external_actions_are_rejected_at_schedule_creation(self) -> None:
        unsafe = WorkflowDefinition(
            "unsafe",
            (WorkflowStep("send", "jobs.submit", {"value": "candidate-42"}),),
        )
        with self.assertRaises(ScheduleValidationError):
            self.service.create("Unsafe", unsafe, Recurrence.interval(60))

    def test_disabled_and_future_locked_schedules_do_not_run(self) -> None:
        now = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
        disabled = self.service.create(
            "Disabled", self.workflow, Recurrence.interval(30), now=now, enabled=False
        )
        locked = self.service.create("Locked", self.workflow, Recurrence.interval(30), now=now)
        self.assertTrue(self.service.claim(locked.id, now=now, lease_seconds=300))

        self.assertEqual(self.service.run_due(now=now), [])
        self.assertFalse(self.service.get(disabled.id).enabled)
        self.assertEqual(self.calls, [])

    def test_schedule_can_be_enabled_updated_and_run_history_is_durable(self) -> None:
        now = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
        created = self.service.create(
            "Draft", self.workflow, Recurrence.interval(15), now=now, enabled=False
        )
        enabled = self.service.set_enabled(created.id, True, now=now)
        self.assertTrue(enabled.enabled)
        self.assertEqual(self.service.run_due(now=now)[0]["status"], "succeeded")
        self.assertEqual(self.service.history(created.id)[0]["schedule_id"], created.id)


if __name__ == "__main__":
    unittest.main()
