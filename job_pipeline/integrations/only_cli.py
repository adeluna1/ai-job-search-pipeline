"""Bounded subprocess adapter for the MIT only-cli web browsing runtime.

only-cli remains a pinned Node.js dependency. This module exposes its shipped
read, navigation, site-shortcut, and session commands to the Python tool
broker without accepting arbitrary command strings or placing cookie values
on a process command line.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

from ..tool_broker import ToolContext, ToolPolicy, ToolResult, ToolSpec
from ..util import redact_secrets
from ..web_intelligence import SafeUrlPolicy, UnsafeUrlError


SUPPORTED_COMMANDS = frozenset(
    {"open", "do", "find", "read", "next", "raw", "sites", "site", "login", "logout"}
)

SUPPORTED_SITE_NAMES = frozenset(
    {
        "aws", "bing", "cloud.google.com", "cpp", "ddg", "developer.mozilla.org",
        "doc.rust-lang.org", "docs.aws.amazon.com", "docs.oracle.com", "docs.python.org",
        "docs.ruby-lang.org", "duckduckgo", "en.cppreference.com", "finance",
        "finance.yahoo.com", "gcp", "gh", "github", "github.com", "hn", "java",
        "learn", "learn.microsoft.com", "linkedin", "linkedin.com", "mdn", "news",
        "news.ycombinator.com", "node", "nodejs.org", "oracle", "php", "php.net",
        "pkg.go.dev", "py", "python", "reddit", "reddit.com", "ruby", "rust", "so",
        "stackoverflow", "stackoverflow.com", "ts", "twitter", "typescriptlang.org",
        "wiki", "wikipedia", "wikipedia.org", "x", "x.com", "youtube", "youtube.com",
        "yt",
    }
)

_LOGIN_MARKERS = (
    "login required",
    "session expired",
    "sign in required",
    "redirected to a login page",
)
_CHALLENGE_MARKERS = (
    "challenged",
    "bot challenge",
    "verify you are human",
    "security check",
    "javascript-only",
    "consent wall",
    "gated",
)


class OnlyCliError(RuntimeError):
    """Base class for only-cli adapter failures."""


class OnlyCliUnavailableError(OnlyCliError):
    """Raised when the pinned Node entry cannot be resolved."""


class OnlyCliCommandError(OnlyCliError):
    """Raised before execution for unsupported or malformed commands."""


class OnlyCliTimeoutError(OnlyCliError):
    """Raised when a command exceeds its caller-provided deadline."""


class OnlyCliOutputError(OnlyCliError):
    """Raised when combined stdout and stderr exceed the adapter cap."""


@dataclass(frozen=True)
class OnlyCliResult:
    """Structured only-cli process result suitable for an agent tool response."""

    command: str
    process_args: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    status: str
    browser_handoff_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the bounded fields that may be shown to an assistant."""
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "status": self.status,
            "browser_handoff_required": self.browser_handoff_required,
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]
UrlValidator = Callable[[str], object]


def _default_session_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "Expedient Employment" / "only-cli"
    return Path.home() / ".expedient-employment" / "only-cli"


def _resolve_entry(project_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    candidates = [
        Path(os.environ["ONLY_CLI_ENTRY"]) if os.environ.get("ONLY_CLI_ENTRY") else None,
        project_root / "gui" / "node_modules" / "@only-cli" / "oc" / "src" / "cli.js",
        project_root / "gui" / "only-cli-runtime" / "node_modules" / "@only-cli" / "oc" / "src" / "cli.js",
        project_root / "node_modules" / "@only-cli" / "oc" / "src" / "cli.js",
        project_root / "only-cli-runtime" / "node_modules" / "@only-cli" / "oc" / "src" / "cli.js",
        project_root / "only-cli" / "src" / "cli.js",
        project_root / "resources" / "only-cli" / "src" / "cli.js",
    ]
    return next(
        (Path(item) for item in candidates if item and Path(item).exists()),
        project_root / "gui" / "only-cli-runtime" / "node_modules" / "@only-cli" / "oc" / "src" / "cli.js",
    )


def _resolve_node(explicit: str | Path | None) -> Path:
    value = explicit or os.environ.get("ONLY_CLI_NODE") or shutil.which("node") or "node"
    return Path(str(value))


def _safe_environment(session_dir: Path) -> dict[str, str]:
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
        "HOME", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy",
        "no_proxy", "NODE_EXTRA_CA_CERTS", "ELECTRON_RUN_AS_NODE",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update({"OC_HOME": str(session_dir), "NO_COLOR": "1", "FORCE_COLOR": "0"})
    return environment


def _validate_argument(value: str) -> str:
    text = str(value)
    if len(text) > 4096:
        raise OnlyCliCommandError("only-cli argument is too long.")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
        raise OnlyCliCommandError("only-cli argument contains a control character.")
    return text


def _validate_public_url(raw_url: str, validator: UrlValidator) -> None:
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OnlyCliCommandError("only-cli accepts HTTP or HTTPS page URLs only.")
    if parsed.username or parsed.password:
        raise OnlyCliCommandError("URL user information is not allowed.")
    try:
        validator(raw_url)
    except (UnsafeUrlError, ValueError, OSError) as exc:
        raise OnlyCliCommandError("only-cli page URLs must resolve to public addresses.") from exc


class OnlyCliAdapter:
    """Invoke a fixed only-cli Node entry through an allowlisted command surface."""

    def __init__(
        self,
        project_root: Path,
        *,
        cli_entry: Path | None = None,
        node_binary: str | Path | None = None,
        session_dir: Path | None = None,
        session_name: str = "expedient",
        runner: Runner | None = None,
        max_output_bytes: int = 524_288,
        url_validator: UrlValidator | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.cli_entry = _resolve_entry(self.project_root, cli_entry)
        self.node_binary = _resolve_node(node_binary)
        self.session_dir = Path(session_dir or _default_session_dir()).resolve()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_name):
            raise OnlyCliCommandError("only-cli session name is invalid.")
        self.session_name = session_name
        self.runner = runner or subprocess.run
        self.max_output_bytes = max(1, int(max_output_bytes))
        self.url_validator = url_validator or SafeUrlPolicy().resolve

    def available(self) -> bool:
        """Return whether the pinned JavaScript entry is available to execute."""
        return self.cli_entry.is_file() and bool(str(self.node_binary))

    def _process_arguments(self, command: str, arguments: list[str]) -> list[str]:
        actual_command = command
        actual_arguments = list(arguments)
        if command == "site":
            if len(actual_arguments) < 2:
                raise OnlyCliCommandError("Site commands require a site name and verb.")
            site_name = actual_arguments.pop(0).casefold()
            if site_name not in SUPPORTED_SITE_NAMES:
                raise OnlyCliCommandError("Unsupported only-cli site shortcut.")
            actual_command = site_name
        if command in {"open", "raw"} and actual_arguments:
            candidate = actual_arguments[0]
            if candidate.startswith(("http://", "https://")):
                _validate_public_url(candidate, self.url_validator)
        return [
            str(self.node_binary),
            str(self.cli_entry),
            actual_command,
            *actual_arguments,
            "--session",
            self.session_name,
        ]

    def run(
        self,
        command: str,
        arguments: Sequence[str],
        *,
        timeout_seconds: float = 30.0,
        stdin_text: str | None = None,
    ) -> OnlyCliResult:
        """Run one supported only-cli command with bounded arguments and output."""
        normalized_command = str(command).strip().casefold()
        if normalized_command not in SUPPORTED_COMMANDS:
            raise OnlyCliCommandError("Unsupported only-cli command.")
        normalized_arguments = [_validate_argument(value) for value in arguments]
        if len(normalized_arguments) > 50:
            raise OnlyCliCommandError("only-cli command has too many arguments.")
        if any(value == "--cookie" or value.startswith("--cookie=") for value in normalized_arguments):
            raise OnlyCliCommandError("Cookie values must use the adapter's protected stdin path.")
        if normalized_command == "login":
            if stdin_text is None or not stdin_text:
                raise OnlyCliCommandError("Login requires an explicit cookie value on protected stdin.")
            if "--domain" not in normalized_arguments:
                raise OnlyCliCommandError("Login requires an explicit cookie domain.")
            normalized_arguments.extend(["--cookie", "-"])
        elif stdin_text is not None:
            raise OnlyCliCommandError("Protected stdin is available only for login.")
        if not self.available():
            raise OnlyCliUnavailableError(
                "only-cli is not installed at the pinned application entry."
            )

        self.session_dir.mkdir(parents=True, exist_ok=True)
        process_args = self._process_arguments(normalized_command, normalized_arguments)
        try:
            completed = self.runner(
                process_args,
                cwd=str(self.project_root),
                env=_safe_environment(self.session_dir),
                input=stdin_text,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(0.01, min(float(timeout_seconds), 120.0)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OnlyCliTimeoutError("only-cli exceeded its execution deadline.") from exc
        except OSError as exc:
            raise OnlyCliUnavailableError(f"only-cli could not start: {exc}") from exc

        stdout = redact_secrets(str(completed.stdout or ""))
        stderr = redact_secrets(str(completed.stderr or ""))
        if len(stdout.encode("utf-8")) + len(stderr.encode("utf-8")) > self.max_output_bytes:
            raise OnlyCliOutputError("only-cli output exceeded the application cap.")
        diagnostic = f"{stdout}\n{stderr}".casefold()
        if any(marker in diagnostic for marker in _LOGIN_MARKERS):
            status = "login_required"
        elif completed.returncode == 2 or any(marker in diagnostic for marker in _CHALLENGE_MARKERS):
            status = "challenge"
        else:
            status = "ok" if completed.returncode == 0 else "failed"
        return OnlyCliResult(
            command=normalized_command,
            process_args=tuple(process_args),
            exit_code=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            status=status,
            browser_handoff_required=status in {"challenge", "login_required"},
        )

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        """Return first-class broker specs for every supported runtime command."""
        specs: list[ToolSpec] = []

        def command_handler(command: str):
            def handler(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
                result = self.run(command, arguments.get("args", []))
                return ToolResult(
                    data=result.to_dict(),
                    summary=f"only-cli {command}: {result.status}",
                )

            return handler

        argument_schema = {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 4096},
                    "maxItems": 50,
                }
            },
            "additionalProperties": False,
        }
        for command in ("open", "do", "find", "read", "next", "raw", "sites", "site"):
            specs.append(
                ToolSpec(
                    name=f"web.only_cli.{command}",
                    description=f"Run only-cli {command} in the application-owned web session.",
                    policy=ToolPolicy.READ,
                    input_schema=argument_schema,
                    handler=command_handler(command),
                    timeout_seconds=45,
                    max_output_bytes=self.max_output_bytes,
                )
            )

        def login_handler(arguments: dict[str, Any], _context: ToolContext) -> ToolResult:
            variable = arguments["credential_env"]
            if not re.fullmatch(r"ONLY_CLI_COOKIE_[A-Z0-9_]{1,48}", variable):
                raise OnlyCliCommandError("Credential environment name is not allowed.")
            cookie = os.environ.get(variable, "")
            if not cookie:
                raise OnlyCliCommandError("The requested only-cli credential is not configured.")
            result = self.run(
                "login",
                ["--domain", arguments["domain"]],
                stdin_text=cookie,
            )
            return ToolResult(data=result.to_dict(), summary="only-cli login session updated")

        specs.append(
            ToolSpec(
                name="web.only_cli.login",
                description="Seed an app-owned only-cli session from an explicitly configured credential.",
                policy=ToolPolicy.LOCAL_WRITE,
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "minLength": 1, "maxLength": 253},
                        "credential_env": {"type": "string", "minLength": 1, "maxLength": 72},
                    },
                    "required": ["domain", "credential_env"],
                    "additionalProperties": False,
                },
                handler=login_handler,
                timeout_seconds=15,
                max_output_bytes=32_768,
            )
        )
        specs.append(
            ToolSpec(
                name="web.only_cli.logout",
                description="Clear the app-owned only-cli cookies and saved page state.",
                policy=ToolPolicy.LOCAL_WRITE,
                input_schema={"type": "object", "additionalProperties": False},
                handler=command_handler("logout"),
                timeout_seconds=15,
                max_output_bytes=32_768,
            )
        )
        return tuple(specs)
