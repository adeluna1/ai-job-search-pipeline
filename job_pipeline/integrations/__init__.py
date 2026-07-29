"""Optional third-party adapters used by the three specialist agents.

Imports stay lightweight so the core deterministic pipeline works without any
third-party package or locally running service.
"""

from .browser_use_runner import BrowserUseError, BrowserUseRunner
from .agent_web_browser import (
    AgentWebBrowserClient,
    AgentWebBrowserError,
    AgentWebBrowserPage,
)
from .jobspy_source import DiscoveryError, JobSpySource
from .resume_matcher import ATSAssessment, ResumeMatcherClient, ResumeMatcherError

__all__ = [
    "ATSAssessment",
    "AgentWebBrowserClient",
    "AgentWebBrowserError",
    "AgentWebBrowserPage",
    "BrowserUseError",
    "BrowserUseRunner",
    "DiscoveryError",
    "JobSpySource",
    "ResumeMatcherClient",
    "ResumeMatcherError",
]
