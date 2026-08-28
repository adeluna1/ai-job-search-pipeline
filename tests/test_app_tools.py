"""Tests for brokered job-pipeline and draft tools."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from job_pipeline.app_tools import JobPipelineToolAdapter
from job_pipeline.tool_broker import ToolBroker, ToolContext


class AppToolTests(unittest.TestCase):
    def test_pipeline_and_draft_commands_are_fixed_bounded_and_non_submitting(self) -> None:
        calls = []

        def runner(arguments, **options):
            calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, "completed", "")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "candidate.docx"
            resume.touch()
            profile = root / "application_profile.json"
            profile.write_text("{}", encoding="utf-8")
            adapter = JobPipelineToolAdapter(root, python_binary="python-test", runner=runner)
            broker = ToolBroker(list(adapter.tool_specs()))
            context = ToolContext(actor="assistant", request_id="app-tool-test")

            pipeline = broker.invoke(
                "jobs.pipeline.run",
                {"max_jobs": 250, "concurrency": 4, "min_score": 72},
                context,
            )
            draft = broker.invoke(
                "jobs.application.prepare_draft",
                {
                    "job_id": "abc123def456",
                    "resume_path": str(resume),
                    "application_profile_path": str(profile),
                },
                context,
            )

        self.assertEqual(pipeline.data["status"], "ok")
        self.assertEqual(draft.data["status"], "ok")
        flattened = " ".join(value for call, _ in calls for value in call)
        self.assertIn("--max-jobs 250", flattened)
        self.assertIn("agent-c abc123def456", flattened)
        self.assertNotIn("agent-c-browser", flattened)
        self.assertNotIn("--submit", flattened)
        policies = {item["name"]: item["policy"] for item in broker.list_tools()}
        self.assertEqual(policies["jobs.application.prepare_draft"], "external_draft")
        self.assertNotIn("external_action", policies.values())

    def test_invalid_paths_ids_and_ranges_fail_before_subprocess(self) -> None:
        adapter = JobPipelineToolAdapter(Path.cwd(), runner=lambda *_args, **_kwargs: None)
        broker = ToolBroker(list(adapter.tool_specs()))
        context = ToolContext(actor="assistant", request_id="invalid")
        with self.assertRaises(Exception):
            broker.invoke("jobs.pipeline.run", {"max_jobs": 501, "concurrency": 4, "min_score": 0}, context)
        with self.assertRaises(Exception):
            broker.invoke(
                "jobs.application.prepare_draft",
                {"job_id": "../bad", "resume_path": "bad.txt", "application_profile_path": "bad"},
                context,
            )

    def test_pipeline_subprocess_does_not_inherit_the_provider_credential(self) -> None:
        calls = []

        def runner(arguments, **options):
            calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 0, "completed", "")

        adapter = JobPipelineToolAdapter(Path.cwd(), runner=runner)
        with patch.dict(
            "os.environ",
            {
                "EXPEDIENT_PROVIDER_KEY_ENV": "FREECHAIN_ACCESS_KEY",
                "FREECHAIN_ACCESS_KEY": "synthetic-provider-key",
            },
            clear=False,
        ):
            adapter._run(["run", "--max-jobs", "1"], timeout_seconds=1)

        child_environment = calls[0][1]["env"]
        self.assertNotIn("EXPEDIENT_PROVIDER_KEY_ENV", child_environment)
        self.assertNotIn("FREECHAIN_ACCESS_KEY", child_environment)


if __name__ == "__main__":
    unittest.main()
