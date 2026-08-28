"""Release packaging contract tests using only the Python standard library."""

from __future__ import annotations

import json
import unittest
from fnmatch import fnmatchcase
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER_CONFIG = ROOT / "gui" / "electron-builder.yml"


def _scalar(value: str) -> str:
    value = value.strip()
    return json.loads(value) if value.startswith('"') else value


def _resources() -> dict[str, dict[str, object]]:
    """Parse the small extraResources subset used by electron-builder.yml."""

    resources: dict[str, dict[str, object]] = {}
    current: dict[str, object] | None = None
    in_filter = False

    for raw_line in BUILDER_CONFIG.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if raw_line.startswith("  - from: "):
            source = _scalar(stripped.removeprefix("- from: "))
            current = {"to": "", "filter": []}
            resources[source] = current
            in_filter = False
        elif current is not None and raw_line.startswith("    to: "):
            current["to"] = _scalar(stripped.removeprefix("to: "))
        elif current is not None and raw_line == "    filter:":
            in_filter = True
        elif current is not None and in_filter and raw_line.startswith("      - "):
            filters = current["filter"]
            assert isinstance(filters, list)
            filters.append(_scalar(stripped.removeprefix("- ")))

    return resources


def _included(path: str, patterns: list[str]) -> bool:
    included = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        matcher = pattern[1:] if negated else pattern
        if fnmatchcase(path, matcher):
            included = not negated
    return included


class ReleasePackagingTests(unittest.TestCase):
    def test_internal_docs_and_dependency_development_files_are_excluded(self) -> None:
        resources = _resources()
        docs_filters = resources["../docs"]["filter"]
        only_cli_filters = resources["only-cli-runtime/node_modules"]["filter"]
        self.assertIsInstance(docs_filters, list)
        self.assertIsInstance(only_cli_filters, list)

        self.assertIn("!superpowers/**", docs_filters)
        for required in (
            "!**/.github/**",
            "!**/test/**",
            "!**/tests/**",
            "!**/__tests__/**",
            "!**/*.map",
        ):
            self.assertIn(required, only_cli_filters)

        for excluded in (
            "@only-cli/oc/.github/workflows/release.yml",
            "@only-cli/oc/test/cli.test.js",
            "@only-cli/oc/tests/cli.test.js",
            "@only-cli/oc/__tests__/cli.test.js",
            "@only-cli/oc/dist/cli.js.map",
        ):
            self.assertFalse(_included(excluded, only_cli_filters), excluded)

    def test_legal_provenance_and_only_cli_runtime_resources_remain(self) -> None:
        resources = _resources()
        expected_mappings = {
            "../README.md": "pipeline/README.md",
            "../LICENSE": "pipeline/LICENSE",
            "../THIRD_PARTY_NOTICES.md": "pipeline/THIRD_PARTY_NOTICES.md",
            "../docs": "pipeline/docs",
            "only-cli-runtime/node_modules": "pipeline/only-cli-runtime/node_modules",
        }
        for source, destination in expected_mappings.items():
            self.assertEqual(resources[source]["to"], destination)

        for source in (
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / "THIRD_PARTY_NOTICES.md",
            ROOT / "docs" / "PROVENANCE.md",
            ROOT / "gui" / "only-cli-runtime" / "package.json",
            ROOT / "gui" / "only-cli-runtime" / "package-lock.json",
        ):
            self.assertTrue(source.is_file(), source.relative_to(ROOT))

        only_cli_filters = resources["only-cli-runtime/node_modules"]["filter"]
        self.assertIsInstance(only_cli_filters, list)
        for required in (
            "@only-cli/oc/package.json",
            "@only-cli/oc/LICENSE",
            "@only-cli/oc/README.md",
            "@only-cli/oc/src/cli.js",
            "@only-cli/oc/dist/cli.js",
        ):
            self.assertTrue(_included(required, only_cli_filters), required)

    def test_windows_timezone_runtime_resources_remain(self) -> None:
        resource = _resources()["../python-runtime"]
        self.assertEqual(resource["to"], "pipeline/python-runtime")
        filters = resource["filter"]
        self.assertIsInstance(filters, list)
        self.assertIn("tzdata/**", filters)
        self.assertIn("tzdata-*.dist-info/**", filters)
        self.assertTrue(_included("tzdata/zoneinfo/UTC", filters))
        self.assertTrue(_included("tzdata-2026.3.dist-info/METADATA", filters))


if __name__ == "__main__":
    unittest.main()
