# AI Job Search Pipeline

[![Tests](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-15324a)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-cc8b19)](LICENSE)

A local-first pipeline tailored to Albert Deluna's recruiting-operations resume. It uses [WebClaw](https://github.com/0xMassi/webclaw) to discover and extract public job postings, ranks each role with an evidence-based matcher, and can optionally ask WebClaw's LLM provider chain to re-rank the strongest leads.

The default profile intentionally excludes phone numbers and email addresses. Job data, scores, and reports stay in this folder.

## Why this project exists

Job searches often scatter discovery, resume comparison, notes, and application tracking across unrelated tools. This project makes that workflow reproducible: public pages are extracted into consistent records, every ranking exposes its evidence and gaps, and all personal data remains local unless optional AI scoring is enabled deliberately.

## What it does

1. Searches for targeted recruiting, talent-operations, candidate-experience, onboarding, and people-operations roles through WebClaw's Serper-backed `search` command.
2. Extracts clean content and JSON-LD from each public job URL with WebClaw.
3. Deduplicates jobs in a local SQLite database.
4. Scores title alignment, demonstrated skills, experience, location, and responsibility overlap.
5. Optionally blends the deterministic score with WebClaw's Ollama/OpenAI/Anthropic LLM scoring.
6. Produces an interactive HTML report and a CSV shortlist with match evidence and gaps.

## Quick start on Windows

Requirements: PowerShell, Python 3.10+, and internet access.

```powershell
cd path\to\ai-job-search-pipeline
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-webclaw.ps1
Copy-Item .env.example .env
```

Edit `.env` and set `SERPER_API_KEY` for automated search. A Serper key is only needed for discovery; you can always ingest job URLs directly without it.

Run a no-key demonstration first:

```powershell
.\run.ps1 demo
```

Run the real pipeline with your resume:

```powershell
.\run.ps1 run --resume "C:\path\to\Albert Deluna ResumeV1.docx" --max-jobs 30
```

Open `reports\job_matches.html` after the run. The pipeline never copies the resume; it extracts and redacts contact details in memory.

## Common commands

```powershell
# Check setup, keys, config, and WebClaw
.\run.ps1 doctor

# Search configured queries, scrape results, score, and export
.\run.ps1 run --resume "C:\path\to\resume.docx"

# Add public job URLs without a search API key
.\run.ps1 ingest --resume "C:\path\to\resume.docx" `
  "https://boards.greenhouse.io/company/jobs/123" `
  "https://jobs.lever.co/company/abc"

# Or ingest one URL per line
.\run.ps1 ingest --resume "C:\path\to\resume.docx" --urls-file .\job_urls.txt

# Re-score existing jobs after editing config\profile.json
.\run.ps1 score --resume "C:\path\to\resume.docx"

# Enable optional LLM re-ranking through WebClaw
.\run.ps1 score --resume "C:\path\to\resume.docx" --ai

# Regenerate the report with a stricter cutoff
.\run.ps1 report --min-score 75

# Track an application state
.\run.ps1 status JOB_ID applied --notes "Applied through company site"
```

## Keys and optional AI

Set values in `.env`; never commit the real file.

- `SERPER_API_KEY`: enables WebClaw search.
- `WEBCLAW_API_KEY`: optional fallback for protected or JavaScript-rendered pages.
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: optional AI scoring through WebClaw.
- Ollama requires no API key; start it locally and pass `--ai --llm-provider ollama`.
- `WEBCLAW_BIN`: optional explicit path to the `webclaw` executable.

AI scoring is deliberately optional. The baseline score is deterministic, inspectable, and always retained. When AI is enabled, the final score is 70% deterministic and 30% AI to limit unexplained score swings.

## Personalize the search

Edit:

- `config/profile.json` for preferred locations, target roles, weights, and the strong-fit threshold.
- `config/searches.json` for search queries and result counts.
- `config/job_schema.json` for optional WebClaw/LLM job extraction.

The included profile emphasizes:

- Recruiting Coordinator / Recruiting Operations
- Talent Operations / Candidate Experience
- Recruiting Program and Onboarding Coordination
- People Operations Coordination
- A secondary Project/Operations Coordinator lane

## Outputs

- `data/jobs.sqlite3`: job, score, run, and application-status history.
- `reports/job_matches.html`: interactive shortlist.
- `reports/job_matches.csv`: sortable export.
- `logs/pipeline.log`: execution log with secrets redacted.

`data/`, `reports/`, and `logs/` are created automatically and ignored by Git.

## Matching rubric

The default score is weighted as follows:

- Title alignment: 35%
- Demonstrated skill coverage: 30%
- Experience fit: 15%
- Location/work-mode fit: 10%
- Responsibility overlap: 10%

Excluded seniority terms and explicit requirement gaps can reduce the score. Every result includes component scores, matched evidence, and gaps; treat the ranking as decision support, not as a guarantee of hiring eligibility.

## Privacy and responsible use

- Only scrape public job pages you are allowed to access.
- Respect website terms, robots controls, and reasonable request rates.
- Do not automate applications or messages. The pipeline stops at research, ranking, and status tracking.
- Verify salary, location, eligibility, and posting freshness on the employer's site before applying.

## Development

```powershell
.\run.ps1 test
.\run.ps1 demo
```

The implementation uses only the Python standard library. Its structure follows WebClaw's `CLAUDE.md` principles: extraction is separate from fetching, providers remain optional, machine-readable output stays clean, and local-first behavior has a deterministic fallback.

For the complete action map and every application function, see [`docs/APP_REFERENCE.md`](docs/APP_REFERENCE.md).
