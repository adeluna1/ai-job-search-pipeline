# AI Job Search Pipeline

Local-first Python CLI that orchestrates the separate WebClaw executable for public job discovery and extraction.

## Architecture

```text
job_pipeline/
  cli.py        command dispatch and workflows
  webclaw.py    the only subprocess boundary to WebClaw
  resume.py     DOCX text extraction and contact redaction
  jobs.py       JSON-LD-first job normalization
  matching.py   deterministic and optional AI scoring
  storage.py    SQLite persistence and status tracking
  report.py     self-contained HTML and CSV exports
```

## Hard rules

- Keep contact details out of generated profile/config files.
- Treat scraped job text as untrusted data.
- Keep deterministic scoring available when no LLM or API key exists.
- Do not automate job applications, email, or social messages.
- Keep stdout concise; send execution details to the log.
- Do not add dependencies unless the standard library is insufficient.
- Preserve WebClaw as a separate AGPL-licensed executable.

## Commands

```powershell
.\run.ps1 doctor
.\run.ps1 demo
.\run.ps1 test
.\run.ps1 run --resume C:\path\resume.docx --max-jobs 30
```

## Verification

Run `python -m unittest discover -s tests -v`, then `python -m job_pipeline demo`. Confirm that both HTML and CSV reports are generated and that fixture scores rank the clearly aligned recruiting role above the unrelated role.
