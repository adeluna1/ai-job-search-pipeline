"""Windows-safe adapter tests for the pinned MIT only-cli runtime."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from job_pipeline.integrations.only_cli import (
    OnlyCliAdapter,
    OnlyCliCommandError,
    OnlyCliOutputError,
    OnlyCliTimeoutError,
    OnlyCliUnavailableError,
)
from job_pipeline.tool_broker import ToolPolicy


class RecordingRunner:
    """Capture the exact process boundary while returning a controlled result."""

    def __init__(self, *, code=0, stdout="ok", stderr=""):
        self.code = code
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, args, **options):
        self.calls.append((list(args), dict(options)))
        return subprocess.CompletedProcess(args, self.code, self.stdout, self.stderr)


class OnlyCliAdapterTests(unittest.TestCase):
    """Prove command allowlisting, process safety, classification, and broker contracts."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.entry = self.root / "only-cli" / "src" / "cli.js"
        self.entry.parent.mkdir(parents=True)
        self.entry.write_text("// test entry\n", encoding="utf-8")
        self.session_dir = self.root / "sessions"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def adapter(self, runner=None, *, max_output_bytes=4096, url_validator=None):
        return OnlyCliAdapter(
            project_root=self.root,
            cli_entry=self.entry,
            node_binary="C:\\Program Files\\nodejs\\node.exe",
            session_dir=self.session_dir,
            runner=runner or RecordingRunner(),
            max_output_bytes=max_output_bytes,
            url_validator=url_validator or (lambda _url: None),
        )

    def test_supported_commands_use_fixed_node_entry_and_owned_session_home(self) -> None:
        runner = RecordingRunner(stdout="page")
        adapter = self.adapter(runner)
        cases = {
            "open": ["https://example.test/page"],
            "do": ["3"],
            "find": ["qualifications"],
            "read": ["7"],
            "next": [],
            "raw": ["https://example.test/page"],
            "sites": [],
            "site": ["hn", "top"],
            "logout": [],
        }
        for command, arguments in cases.items():
            with self.subTest(command=command):
                result = adapter.run(command, arguments, timeout_seconds=2)
                self.assertEqual(result.command, command)
                self.assertNotIn("C:\\C:\\", " ".join(result.process_args))
                self.assertEqual(result.status, "ok")

        process_args, options = runner.calls[0]
        self.assertEqual(process_args[:2], [str(adapter.node_binary), str(self.entry)])
        self.assertFalse(options["shell"])
        self.assertEqual(options["env"]["OC_HOME"], str(self.session_dir))

    def test_planned_and_arbitrary_commands_are_rejected(self) -> None:
        adapter = self.adapter()
        for command in ("fill", "submit", "back", "shell", "session"):
            with self.subTest(command=command), self.assertRaises(OnlyCliCommandError):
                adapter.run(command, [])

    def test_page_urls_pass_the_dns_aware_public_url_policy(self) -> None:
        checked = []
        adapter = self.adapter(url_validator=checked.append)
        adapter.run("open", ["https://example.test/page"])
        self.assertEqual(checked, ["https://example.test/page"])

        def reject_internal(_url):
            raise ValueError("internal target")

        with self.assertRaisesRegex(OnlyCliCommandError, "public"):
            self.adapter(url_validator=reject_internal).run(
                "raw", ["https://internal.example.test/page"]
            )

    def test_login_reads_cookie_from_stdin_and_never_process_arguments(self) -> None:
        runner = RecordingRunner()
        adapter = self.adapter(runner)
        result = adapter.run(
            "login",
            ["--domain", "example.test"],
            stdin_text="session-cookie-value",
        )
        process_args, options = runner.calls[0]
        self.assertIn("--cookie", process_args)
        self.assertIn("-", process_args)
        self.assertNotIn("session-cookie-value", " ".join(process_args))
        self.assertEqual(options["input"], "session-cookie-value")
        self.assertEqual(result.status, "ok")

    def test_missing_entry_timeout_and_output_cap_are_explicit(self) -> None:
        missing = OnlyCliAdapter(project_root=self.root, cli_entry=self.root / "missing.js")
        self.assertFalse(missing.available())
        with self.assertRaises(OnlyCliUnavailableError):
            missing.run("sites", [])

        def timeout_runner(args, **_options):
            raise subprocess.TimeoutExpired(args, 0.01)

        with self.assertRaises(OnlyCliTimeoutError):
            self.adapter(timeout_runner).run("sites", [], timeout_seconds=0.01)

        with self.assertRaises(OnlyCliOutputError):
            self.adapter(RecordingRunner(stdout="x" * 256), max_output_bytes=64).run(
                "sites", []
            )

    def test_challenge_login_and_secret_redaction_are_structured(self) -> None:
        challenge = self.adapter(
            RecordingRunner(
                code=2,
                stderr="no readable content, JavaScript-only, gated, or challenged",
            )
        ).run("open", ["https://example.test"])
        self.assertEqual(challenge.status, "challenge")
        self.assertTrue(challenge.browser_handoff_required)

        login = self.adapter(
            RecordingRunner(code=2, stderr="session expired, login required")
        ).run("open", ["https://example.test"])
        self.assertEqual(login.status, "login_required")

        redacted = self.adapter(
            RecordingRunner(code=1, stderr="api_key=private-token-value")
        ).run("sites", [])
        self.assertNotIn("private-token-value", redacted.stderr)

    def test_tool_specs_expose_supported_surface_with_safe_policies(self) -> None:
        specs = {spec.name: spec for spec in self.adapter().tool_specs()}
        self.assertIn("web.only_cli.open", specs)
        self.assertIn("web.only_cli.site", specs)
        self.assertIn("web.only_cli.login", specs)
        self.assertEqual(specs["web.only_cli.open"].policy, ToolPolicy.READ)
        self.assertEqual(specs["web.only_cli.login"].policy, ToolPolicy.LOCAL_WRITE)
        self.assertNotIn("web.only_cli.submit", specs)


if __name__ == "__main__":
    unittest.main()
