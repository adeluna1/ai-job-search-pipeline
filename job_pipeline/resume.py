"""Read DOCX resumes locally and remove contact details before model use."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .util import normalize_space, unique_preserving_order


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class ResumeError(RuntimeError):
    """Raised when the corrected DOCX resume cannot be read safely."""


def extract_docx_text(path: Path) -> str:
    """Extract paragraphs and table-cell text from DOCX in document order."""
    if not path.exists():
        raise ResumeError(f"Resume not found: {path}")
    if path.suffix.casefold() != ".docx":
        raise ResumeError("The resume must be a .docx file.")

    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ResumeError(f"Could not read DOCX: {exc}") from exc

    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ResumeError("Word document XML declarations are not allowed.")

    try:
        # DTD and entity declarations are rejected before the parser sees the bytes.
        root = ElementTree.fromstring(xml)  # nosec B314
    except ElementTree.ParseError as exc:
        raise ResumeError(f"Invalid Word document XML: {exc}") from exc

    lines: list[str] = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        fragments: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NS}t" and node.text:
                fragments.append(node.text)
            elif node.tag == f"{WORD_NS}tab":
                fragments.append("\t")
        line = normalize_space("".join(fragments))
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines)


def redact_contact_details(text: str) -> str:
    """Replace email, North American phone, and LinkedIn URL patterns with labels."""
    text = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[EMAIL REDACTED]", text)
    text = re.sub(
        r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)",
        "[PHONE REDACTED]",
        text,
    )
    text = re.sub(r"(?i)https?://(?:www\.)?linkedin\.com/\S+", "[LINKEDIN REDACTED]", text)
    return text


def resume_context(path: Path | None) -> str:
    """Return redacted resume text for in-memory scoring, or an empty string if omitted."""
    if not path:
        return ""
    return redact_contact_details(extract_docx_text(path))


def resume_terms(text: str) -> list[str]:
    """Extract conservative, job-relevant terms; never return contact data."""
    catalog = [
        "Greenhouse ATS",
        "Ashby ATS",
        "G Suite",
        "Microsoft Excel",
        "ChatGPT",
        "Gemini",
        "Claude",
        "recruiting coordination",
        "candidate experience",
        "interview scheduling",
        "onboarding",
        "project management",
        "sales operations",
        "technical recruiting",
        "data analysis",
        "database management",
        "cross-functional collaboration",
        "knowledge management",
        "LLM",
    ]
    aliases = {
        "Ashby ATS": ("ashby ats", "ashby"),
    }
    normalized = text.casefold()
    found = [
        term
        for term in catalog
        if any(alias in normalized for alias in aliases.get(term, (term.casefold(),)))
    ]
    return unique_preserving_order(found)
