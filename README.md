# AI Job Search Pipeline

[![Tests](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml/badge.svg)](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/tests.yml)
[![Code Review Graph](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/code-review-graph.yml/badge.svg)](https://github.com/adeluna1/ai-job-search-pipeline/actions/workflows/code-review-graph.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-15324a)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-cc8b19)](LICENSE)

A local-first pipeline tailored to the candidate's recruiting-operations resume. [Paperclip](https://github.com/paperclipai/paperclip) coordinates three specialized agents: [JobSpy](https://github.com/speedyapply/JobSpy) supplies multi-board discovery, [WebClaw](https://github.com/0xMassi/webclaw) supplies direct-page extraction and fallback discovery, [Agent Web Browser](https://github.com/BarnsL/agent-web-browser) supplies optional session-aware Glassdoor/ZipRecruiter reads, [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) can add ATS evidence, and [browser-use](https://github.com/browser-use/browser-use) powers an approval-gated application helper.

Sharing this project with another AI assistant? Start with [`README_FOR_AI.md`](README_FOR_AI.md), which contains the architecture, safety boundaries, setup commands, and a copy-paste handoff prompt without private candidate data.

The latest pipeline-review decision and completed remediation are documented in [`docs/PIPELINE_REVIEW_REMEDIATION.md`](docs/PIPELINE_REVIEW_REMEDIATION.md).

The default profile intentionally excludes phone numbers and email addresses. Job data, scores, and reports stay in this folder.

## Why this project exists

Job searches often scatter discovery, resume comparison, notes, and application tracking across unrelated tools. This project makes that workflow reproducible: public pages are extracted into consistent records, every ranking exposes its evidence and gaps, and all personal data remains local unless optional AI scoring is enabled deliberately.

## What it does

1. Searches LinkedIn and Indeed through JobSpy and attempts Glassdoor and ZipRecruiter once per run. Indeed/Glassdoor receive `country_indeed` plus a full city/state location; ZipRecruiter receives only its supported location input.
2. Opens a per-run circuit breaker when a board returns HTTP 400/403, then routes missing coverage through WebClaw search instead of retrying the blocked JobSpy request.
3. Automatically starts Agent Web Browser in safe read-only mode when available, navigates its signed-in Glassdoor/ZipRecruiter tabs to constructed search pages, extracts only first-party job-detail links, and opens a board-wide circuit for the rest of the run if a challenge blocks access.
4. Runs bounded searches by requested title family and ATS family on every run: Greenhouse, Ashby, Lever, Workday, SmartRecruiters, iCIMS, Workable, Dayforce, Paycom, HRMDirect, and Workwolf.
5. Resolves board results and safe redirects to the final employer application page and recognizes joined employer domains such as spectrocloud.com. Closed, stale, suspicious, generic, mismatched, and out-of-scope pages are rejected; relevant blocked or incomplete leads enter a manual-verification queue that cannot reach Agent B or C.
6. Adds a local Career Ops-inspired posting-confidence layer: URL/provenance trust, 90-day repost detection, and near-duplicate description fingerprints. These advisory signals never change resume-fit scores.
7. Scores title alignment, demonstrated skills, experience, location, and responsibility overlap only after the active-page verification gate passes.
8. Optionally adds a Resume-Matcher tailoring-preview ATS score, keyword gaps, and recommendations without replacing the original explainable score.
9. Produces a complete current-run HTML/CSV/JSON audit plus a separate verified-only shortlist. Every unique candidate is categorized as `verified`, `manual_verification_required`, or `excluded`; historical benchmarks never count toward current-run totals.
10. Coordinates a recruiter agent, an independent verifier, and a browser-use application assistant in Paperclip; every browser action is bound to the exact packet hash, job URL, and approved action.

## Visual overview

![Pipeline architecture](docs/images/pipeline-architecture.svg)

![Sample interactive dashboard](docs/images/dashboard-preview.svg)

The dashboard image uses synthetic sample data and contains no personal information.
## Quick start on Windows

Requirements: PowerShell, Python 3.10+, and internet access.

```powershell
cd path\to\ai-job-search-pipeline
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install-webclaw.ps1
Copy-Item .env.example .env
```

Edit `.env` and set `TAVILY_API_KEY` for automated search. A Tavily free key is used for discovery and page extraction; you can always ingest job URLs directly without it.

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

Agent Web Browser is an optional Agent A recovery service, not Agent C's form filler. The installer clones the reviewed commit and applies a narrow patch that permits only the two documented first-party job-board hosts:

```powershell
# Clone/pin/patch source; no compiler required
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-web-browser.ps1

# Requires Rust stable, Microsoft C++ Build Tools, and WebView2
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-web-browser.ps1 -RunTests -Build
.\tools\upstream\agent-web-browser\src-tauri\target\release\smab.exe
```

Log in, consent, and handle CAPTCHA only in its visible window. The pipeline reads its local token from `%LOCALAPPDATA%\agent-web-browser\api-token`. Its reviewed `/page/job-links` route only enumerates HTTPS job-detail anchors on the active first-party Glassdoor or ZipRecruiter page; ZipRecruiter searches use its server-rendered `/Jobs` route so those anchors exist. The route does not click Apply, fill forms, or modify the account. Never enable AWB's arbitrary-navigation, JavaScript, extension-mutation, or write flags for this pipeline.

Resume-Matcher stays a separate service. The upstream pinned Docker image can be started locally, then configured through its UI at port 3000:

```powershell
docker run --name ai-job-resume-matcher -p 3000:3000 `
  -v ai-job-resume-data:/app/backend/data `
  ghcr.io/srbhr/resume-matcher:1.2.0
```

Use `http://127.0.0.1:3000/api/v1` for Agent B. Do not point `--resume-matcher-url` at an untrusted host; the opt-in command uploads the corrected resume there.

Run the real pipeline with your resume:

```powershell
.\run.ps1 run --resume "C:\path\to\resume.docx" --max-jobs 30
```

Open `reports\job_matches.html` for every current-run candidate or `reports\job_matches_verified.html` for the Agent B-eligible shortlist. The pipeline never copies the resume; it extracts and redacts contact details in memory.

## Paperclip agent team

Requirements: Node.js 20+, pnpm, and a signed-in Codex CLI. The repository pins both Paperclip and Codex in `package.json`.

```powershell
pnpm install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-paperclip.ps1 -ProbeCodex
```

Open [http://127.0.0.1:3100](http://127.0.0.1:3100). Setup is idempotent and creates one company, one goal, one project, three paused agents, and three backlog issues:

- Agent A - Recruiter: runs one bounded call per board, records exact status/coverage, and automatically hands missing coverage to WebClaw.
- Agent B - Verifier: scores only WebClaw-verified employer postings, then returns `apply`, `review`, or `skip`; an explicitly authorized Resume-Matcher service can add ATS evidence.
- Agent C - Application Assistant: prepares a private packet, creates a pending approval receipt, and can invoke browser-use only after an exact accepted confirmation.

Agents are paused by default. Review the board and private application profile before resuming one. See [`docs/PAPERCLIP_AGENTS.md`](docs/PAPERCLIP_AGENTS.md) for the operating procedure and [`paperclip/PIPELINE_GRAPH.md`](paperclip/PIPELINE_GRAPH.md) for the graph contract.

## Maintained production workflow

The supported production route is `agent-a-find` -> `agent-b --live` ->
`agent-c` -> `agent-c-browser`. Generic `run`, `ingest`, and `score` commands are
retained as manual maintenance utilities, not alternative production graphs.

```powershell
# Check setup, keys, config, and WebClaw
.\run.ps1 doctor

# Legacy/manual all-in-one utility; does not create an Agent B-to-C handoff
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

# Historical date-specific builders are reference-only under
# scripts\archive\manual_reports\ and must not be used for new searches.

# Track an application state
.\run.ps1 status JOB_ID applied --notes "Applied through company site"

# Test all three specialist contracts without network access or submission
.\run.ps1 agent-demo --resume "C:\path\to\resume.docx"

# Create the ignored, private answer template for Agent C
.\run.ps1 agent-profile-init

# Run individual specialist commands against only the current shortlist
.\run.ps1 agent-a --job-id JOB_ID --location "San Francisco Bay Area" --fresh-days 7
.\scripts\agent-run.cmd agent-a-find --query "Recruiting Coordinator" `
  --location "San Francisco Bay Area" --location "San Jose, California" `
  --hours-old 168 --fresh-days 7 --results-wanted 10 --max-results 10 --concurrency 4 `
  --resume "C:\path\to\resume.docx"
.\run.ps1 agent-b --job-id JOB_ID --location "San Francisco Bay Area" --fresh-days 7 --live
.\run.ps1 agent-c JOB_ID --resume "C:\path\to\resume.docx" `
  --application-profile .\data\application_profile.json

# Create a dry-run browser plan and pending approval receipt; no browser opens
.\scripts\agent-run.cmd agent-c-browser JOB_ID

# Optional Resume-Matcher evidence. This explicitly transmits the resume to that URL.
.\run.ps1 agent-b --job-id JOB_ID --live --resume-matcher `
  --resume-matcher-url http://127.0.0.1:3000/api/v1 `
  --resume "C:\path\to\resume.docx" --allow-resume-upload
```

## Recommended search scope

The desktop app defaults to a seven-day daily search. Its optional 14-day window is intended for a wider weekly pass. The default title family includes entry-level recruiting coordination, scheduling, sourcing, candidate experience, recruiting operations, junior recruiter, Recruiter I, and university recruiting coordination while excluding senior and technical-recruiter roles. The default geography includes Northern California cities plus Remote US, Remote California, and California.
## Keys and optional AI

Set values in `.env`; never commit the real file.

- `TAVILY_API_KEY`: enables Tavily discovery and employer-page extraction.
- `TAVILY_API_KEY`: enables employer-page extraction and summarization.
- `AGENT_WEB_BROWSER_URL`: optional read-only local bridge; fixed to `http://127.0.0.1:7896`.
- `WEBCLAW_API_KEY`: optional fallback for protected or JavaScript-rendered pages.`r`n- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: optional AI scoring through WebClaw.
- Ollama requires no API key; start it locally and pass `--ai --llm-provider ollama`.
- `WEBCLAW_BIN`: optional explicit path to the `webclaw` executable.
- `RESUME_MATCHER_URL`: optional user-controlled Resume-Matcher API; default is `http://127.0.0.1:3000/api/v1`.
- `WEBCLAW_API_KEY`: optional fallback for protected or JavaScript-rendered pages.`r`n- `OPENAI_API_KEY`: also used by the browser-use runner when an approved browser session is executed.

Posting intelligence is local and deterministic. Configure it in `config/profile.json` under `posting_intelligence`; profiles that omit the block or set `enabled` to `false` retain the prior verified-page and resume-ranking behavior without changing search configuration.

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

- `data/jobs.sqlite3`: jobs, scores, runs, current lifecycle state, and append-only application events.
- `data/applied_jobs.json`: ignored lifecycle-suppression registry that survives fresh databases and board URL aliases.
- `data/application_exclusions.local.json`: optional ignored company/role exclusions for maintained searches.
- `data/agent_a_findings.json`: Agent A's freshness and source triage.
- `data/agent_a_discovery.json`: JobSpy board counts, missing-board coverage, and fallback recommendation.
- `data/agent_b_reviews.json`: Agent B's independent decisions, evidence, and integrity-bound Agent C handoffs.
- `data/application_packets/`: ignored private Agent C review packets.
- `data/application_approvals/`: ignored, per-packet approval receipts.
- `data/browser_plans/`: ignored browser-use dry-run plans without candidate field values.
- `data/application_results/`: ignored browser outcomes requiring employer-receipt verification.
- `reports/job_matches.html`, `.csv`, `.json`: complete current-run candidate audit with category, lifecycle, duplicate, and URL-evidence labels.
- `reports/job_matches_verified.html`, `.csv`: verified-only shortlist eligible for Agent B.
- `reports/job_matches_manual_verification.html`, `.csv`, `.json`: visible leads that require a human check and cannot reach Agent B or C.
- `reports/job_matches_excluded.html`, `.csv`, `.json`: every rejected current-run candidate with its exact reason, including already-applied roles.
- Historical comparison data is separately labeled and is never included in current-run counts.
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
- Application packets stay private and require a current, integrity-bound Agent B apply handoff plus per-role confirmation. Never treat silence, a prior approval, or a high match score as permission to submit.
- Agent C must stop for missing or sensitive answers and may act externally only within the exact accepted Paperclip confirmation.
- The browser is restricted to the job URL's exact HTTPS host. It may not bypass CAPTCHA, bot detection, access controls, or site terms.
- Agent Web Browser is used only for first-party Glassdoor/ZipRecruiter search navigation, sanitized visible-text reads, and bounded first-party job-link enumeration. It never clicks Apply or changes the account, and the pipeline refuses it when any upstream diagnostic or write flag is enabled.
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

Code Review Graph provides a separate local-first code-quality layer. It maps call relationships, impact radius, flows, and test gaps without joining the job-search agent graph or reading private generated artifacts:

```powershell
.\scripts\code-review-graph.cmd status
.\scripts\code-review-graph.cmd detect-changes --brief
.\scripts\code-review-graph.cmd visualize
```

Its GitHub workflow comments on pull requests but is initially advisory and cannot block a merge. See [`docs/CODE_REVIEW_GRAPH.md`](docs/CODE_REVIEW_GRAPH.md) for installation, privacy exclusions, MCP scope, and operating commands.

For the complete action map and every application function, see [`docs/APP_REFERENCE.md`](docs/APP_REFERENCE.md).

## Desktop control center

The optional Electron desktop interface is selectively adapted from
[BarnsL/expedient-employment v1.4.0](https://github.com/BarnsL/expedient-employment/releases/tag/v1.4.0).
It adds a shareable control center and release packaging without replacing the
maintained Agent A/B/C Python workflow.

From the gui directory:

    npm.cmd install
    npm.cmd test
    npm.cmd run lint
    npm.cmd run build
    npm.cmd run electron

The desktop search screen uses the expanded coordinator and junior-recruiter
title family, exact Bay Area/San Francisco/San Jose/Oakland/Sacramento
locations, 24-hour/3-day/7-day freshness, the corrected DOCX resume, and a hard
top-10 cap. Applied-role exclusion, duplicate removal, live direct-page
verification, fit scoring, and Agent C approval remain enforced by the Python
pipeline.

A packaged desktop release still requires Python 3.10+ on PATH. Paperclip,
Docker/Resume-Matcher, JobSpy, WebClaw, Agent Web Browser, and browser-use remain
optional separately installed runtimes. See [the desktop integration reference](docs/DESKTOP_APP.md)
and [packaging guide](packaging/README.md).

## Applications dashboard

Generate a local dashboard from the durable applied-role registry and SQLite lifecycle history:

```powershell
python -m job_pipeline applications-report
```

The command writes:

- `reports/applications_dashboard.html`: interactive search and status filters.
- `reports/applications_dashboard.csv`: spreadsheet-friendly export.
- `reports/applications_dashboard.json`: structured input for the Electron Applications page.

Older imported records without an explicit outcome are labeled **Applied - status not recorded**. The dashboard never guesses an interview, rejection, or offer. Update detailed pipeline jobs with `status JOB_ID STATE --notes TEXT`, then regenerate the dashboard.

### Dashboard outcome dropdown

On the desktop Applications page, use each row's **Outcome** dropdown:

- **Interview** moves the lifecycle to `interviewing`.
- **Denied** moves it to `rejected` and retains the explicit denied flag.
- **Didn't get job** moves it to `rejected` and retains a separate not-selected flag.

Every selection requires confirmation. The change is written atomically to `data/applied_jobs.json` and SQLite when a matching job ID exists, all three dashboard exports are regenerated, and the success banner offers **Undo** to restore the previous status in both stores.
