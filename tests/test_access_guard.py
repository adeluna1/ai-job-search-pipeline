"""Regression tests for fail-closed job-board access handling."""

from __future__ import annotations

import logging
import unittest

from job_pipeline.integrations.jobspy_source import JobSpySource


class AccessGuardTests(unittest.TestCase):
    """Keep access challenges visible and route them to a user session."""

    def test_human_check_opens_board_circuit_and_requests_user_session(self) -> None:
        """A challenge page must stop board automation even with no HTTP exception."""

        def challenged_scraper(**_options):
            logging.getLogger("JobSpy:Indeed").warning(
                "HTTP 429 security check: verify you are human"
            )
            return []

        source = JobSpySource(challenged_scraper)
        source.search(
            search_term="Recruiting Coordinator",
            location="San Jose, California",
            hours_old=24,
            results_wanted=5,
            sites=["indeed"],
        )

        diagnostics = source.last_diagnostics
        self.assertEqual(diagnostics["status_by_site"]["indeed"], "blocked_human_check")
        self.assertEqual(diagnostics["blocked_sites"], ["indeed"])
        self.assertEqual(
            diagnostics["circuit_breakers"]["indeed"]["action"],
            "route_to_session_browser",
        )
        self.assertFalse(
            diagnostics["circuit_breakers"]["indeed"]["retry_in_current_run"]
        )

    def test_configured_unauthorized_status_is_not_retried(self) -> None:
        """The default HTTP 401 guard must remain broader than upstream 400/403 checks."""

        def unauthorized_scraper(**_options):
            logging.getLogger("JobSpy:LinkedIn").warning("HTTP response 401")
            return []

        source = JobSpySource(unauthorized_scraper)
        source.search(
            search_term="Recruiting Coordinator",
            location="Remote",
            hours_old=24,
            results_wanted=5,
            sites=["linkedin"],
        )

        diagnostics = source.last_diagnostics
        self.assertEqual(diagnostics["status_by_site"]["linkedin"], "blocked_401")
        self.assertIn(401, diagnostics["access_guard"]["detect_status"])


if __name__ == "__main__":
    unittest.main()
