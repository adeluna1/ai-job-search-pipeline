"""Optional third-party adapters used by the three specialist agents.

Imports stay lightweight so the core deterministic pipeline works without any
third-party package or locally running service.
"""

from .browser_use_runner import BrowserUseError, BrowserUseRunner
from .jobspy_source import DiscoveryError, JobSpySource
from .resume_matcher import ATSAssessment, ResumeMatcherClient, ResumeMatcherError

__all__ = [
    "ATSAssessment",
    "BrowserUseError",
    "BrowserUseRunner",
    "DiscoveryError",
    "JobSpySource",
    "ResumeMatcherClient",
    "ResumeMatcherError",
]
