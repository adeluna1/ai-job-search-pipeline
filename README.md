# AI Job Search Pipeline

[![Tests](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-15324a)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-cc8b19)](LICENSE)

A local-first pipeline tailored to Albert Deluna's recruiting-operations resume. [Paperclip](https://github.com/paperclipai/paperclip) coordinates three specialized agents: [JobSpy](https://github.com/speedyapply/JobSpy) supplies multi-board discovery, [WebClaw](https://github.com/0xMassi/webclaw) supplies direct-page extraction and fallback discovery, [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) can add ATS evidence, and [browser-use](https://github.com/browser-use/browser-use) powers an approval-gated application helper.

The default profile intentionally excludes phone numbers and email addresses. Job data, scores, and reports stay in this folder.

## Why this project exists

Job searches often scatter discovery, resume comparison, notes, and application tracking across unrelated tools. This project makes that workflow reproducible: public pages are extracted into consistent records, every ranking exposes its evidence and gaps, and all personal data remains local unless optional AI scoring is enabled deliberately.

## What it does

1. Searches LinkedIn, Indeed, Glassdoor, and ZipRecruiter concurrently through JobSpy, with provider-level diagnostics and a replaceable discovery boundary.
2. Uses WebClaw's Serper-backed search and direct-page extraction as a fallback or verification path.
3. Deduplicates jobs in a local SQLite database.
4. Scores title alignment, demonstrated skills, experience, location, and responsibility overlap.
5. Optionally adds a Resume-Matcher tailoring-preview ATS score, keyword gaps, and recommendations without replacing the original explainable score.
6. Produces an interactive HTML report and a CSV shortlist with match evidence and gaps.
7. Coordinates a recruiter agent, an independent verifier, and a browser-use application assistant in Paperclip; every browser action is bound to the exact packet hash, job URL, and approved action.

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

Install optional agent integrations in separate environments. They are intentionally isolated because JobSpy and browser-use require incompatible `markdownify` versions:

```powershell
# Stage 1: Agent A discovery
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-integrations.ps1 -JobSpy

# Stage 3: Agent C browser runtime (Python 3.11+)
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-integrations.ps1 -BrowserUse
```

Resume-Matcher stays a separate service. The upstream pinned Docker image can be started locally, then configured through its UI at port 3000:

```powershell
docker run --name ai-job-resume-matcher -p 3000:3000 `
  -v ai-job-resume-data:/app/backend/data `
  ghcr.io/srbhr/resume-matcher:1.2.0
```

Use `http://127.0.0.1:3000/api/v1` for Agent B. Do not point `--resume-matcher-url` at an untrusted host; the opt-in command uploads the corrected resume there.

Run the real pipeline with your resume:

```powershell
.\run.ps1 run --resume "C:\path\to\Albert Deluna ResumeV1.docx" --max-jobs 30
```

Open `reports\job_matches.html` after the run. The pipeline never copies the resume; it extracts and redacts contact details in memory.

## Paperclip agent team

Requirements: Node.js 20+, pnpm, and a signed-in Codex CLI. The repository pins both Paperclip and Codex in `package.json`.

```powershell
pnpm install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-paperclip.ps1 -ProbeCodex
```

Open [http://127.0.0.1:3100](http://127.0.0.1:3100). Setup is idempotent and creates one company, one goal, one project, three paused agents, and three backlog issues:

- Agent A - Recruiter: runs one bounded JobSpy multi-board call, records board coverage, scores roles, and supplies evidence-backed job IDs. WebClaw remains the fallback when board coverage degrades.
- Agent B - Verifier: independently checks the role and returns `apply`, `review`, or `skip`; an explicitly authorized Resume-Matcher service can add ATS evidence.
- Agent C - Application Assistant: prepares a private packet, creates a pending approval receipt, and can invoke browser-use only after an exact accepted confirmation.

Agents are paused by default. Review the board and private application profile before resuming one. See [`docs/PAPERCLIP_AGENTS.md`](docs/PAPERCLIP_AGENTS.md) for the operating procedure and [`paperclip/PIPELINE_GRAPH.md`](paperclip/PIPELINE_GRAPH.md) for the graph contract.

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

# Build the dated, resume-weighted search snapshots (outputs stay Git-ignored)
$env:JOB_PIPELINE_RESUME = "C:\path\to\resume.docx"
python .\scripts\build_weighted_24h_report.py
python .\scripts\build_weighted_7d_report.py

# Track an application state
.\run.ps1 status JOB_ID applied --notes "Applied through company site"

# Test all three specialist contracts without network access or submission
.\run.ps1 agent-demo --resume "C:\path\to\Albert Deluna ResumeV1.docx"

# Create the ignored, private answer template for Agent C
.\run.ps1 agent-profile-init

# Run individual specialist commands against stored jobs
.\run.ps1 agent-a --fresh-days 7
.\scripts\agent-run.cmd agent-a-find --query "Recruiting Coordinator" `
  --location "United States" --hours-old 168 --results-wanted 10 `
  --resume "C:\path\to\resume.docx"
.\run.ps1 agent-b --job-id JOB_ID --fresh-days 7 --live
.\run.ps1 agent-c JOB_ID --resume "C:\path\to\resume.docx" `
  --application-profile .\data\application_profile.json

# Create a dry-run browser plan and pending approval receipt; no browser opens
.\scripts\agent-run.cmd agent-c-browser JOB_ID

# Optional Resume-Matcher evidence. This explicitly transmits the resume to that URL.
.\run.ps1 agent-b --job-id JOB_ID --resume-matcher `
  --resume-matcher-url http://127.0.0.1:3000/api/v1 `
  --resume "C:\path\to\resume.docx" --allow-resume-upload
```

## Keys and optional AI

Set values in `.env`; never commit the real file.

- `SERPER_API_KEY`: enables WebClaw search.
- `WEBCLAW_API_KEY`: optional fallback for protected or JavaScript-rendered pages.
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: optional AI scoring through WebClaw.
- Ollama requires no API key; start it locally and pass `--ai --llm-provider ollama`.
- `WEBCLAW_BIN`: optional explicit path to the `webclaw` executable.
- `RESUME_MATCHER_URL`: optional user-controlled Resume-Matcher API; default is `http://127.0.0.1:3000/api/v1`.
- `OPENAI_API_KEY`: also used by the browser-use runner when an approved browser session is executed.

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
- `data/applied_jobs.json`: ignored local registry used to suppress applied roles across fresh databases and board URL aliases.
- `data/application_exclusions.local.json`: optional ignored list such as `{ "companies": ["Example Corp"] }` used by dated report builders.
- `data/agent_a_findings.json`: Agent A's freshness and source triage.
- `data/agent_a_discovery.json`: JobSpy board counts, missing-board coverage, and fallback recommendation.
- `data/agent_b_reviews.json`: Agent B's independent decisions and evidence.
- `data/application_packets/`: ignored private Agent C review packets.
- `data/application_approvals/`: ignored, per-packet approval receipts.
- `data/browser_plans/`: ignored browser-use dry-run plans without candidate field values.
- `data/application_results/`: ignored browser outcomes requiring employer-receipt verification.
- `reports/job_matches.html`: interactive shortlist.
- `reports/job_matches.csv`: sortable export.
- `reports/agent_demo.json`: offline three-agent contract test.
- `reports/paperclip_setup.json`: non-sensitive Paperclip entity IDs and safety state.
- `reports/paperclip_validation.json`: reproducible paused/sandboxed control-plane check.
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
- Application packets stay private and require per-role confirmation. Never treat silence, a prior approval, or a high match score as permission to submit.
- Agent C must stop for missing or sensitive answers and may act externally only within the exact accepted Paperclip confirmation.
- The browser is restricted to the job URL's exact HTTPS host. It may not bypass CAPTCHA, bot detection, access controls, or site terms.
- Fill-only sessions remove click, keyboard-submit, dropdown-selection, and JavaScript tools at runtime; those controls remain a manual handoff.
- Voluntary demographic, disability, veteran, criminal-history, and unknown questions always return to the candidate.
- No agent sends recruiter messages, creates accounts, accepts unrelated terms, or invents candidate information.
- Verify salary, location, eligibility, and posting freshness on the employer's site before applying.

## Development

```powershell
.\run.ps1 test
.\run.ps1 demo
```

The core Python specialist layer uses only the standard library. JobSpy and browser-use are pinned in separate ignored virtual environments, while Resume-Matcher stays a separate service. Paperclip and the Codex CLI are pinned development dependencies for the control plane. This keeps providers optional, machine-readable output clean, and local-first behavior available when an integration is offline.

For the complete action map and every application function, see [`docs/APP_REFERENCE.md`](docs/APP_REFERENCE.md).
