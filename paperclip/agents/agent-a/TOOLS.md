# Agent A Tools

Working directory: `$env:JOB_PIPELINE_PROJECT_ROOT`

- `./scripts/agent-run.cmd agent-a-find --query "Recruiting Coordinator" --location "United States" --hours-old 168 --results-wanted 10 --resume "$env:JOB_PIPELINE_RESUME"` - primary JobSpy multi-board discovery, scoring, reporting, and triage.
- `data/agent_a_discovery.json` - board status/circuit breakers plus WebClaw and Agent Web Browser fallback diagnostics.
- `./run.cmd doctor` - validate WebClaw, keys, profile, and base runtime.
- `./run.cmd run --resume "$env:JOB_PIPELINE_RESUME" --max-jobs 30` - fallback WebClaw discovery, scrape, score, and report.
- `./run.cmd ingest --resume "$env:JOB_PIPELINE_RESUME" URL...` - ingest explicit employer/ATS URLs.
- `./run.cmd agent-a --fresh-days 7 --min-score 72` - write structured recruiter findings for stored jobs.
- `reports/job_matches.html` - interactive ranking report.
- `data/agent_a_findings.json` - machine-readable handoff to Agent B.

JobSpy is the primary board-discovery boundary. WebClaw remains the direct-page extraction and fallback-search boundary. Agent Web Browser is an optional read-only session bridge for Glassdoor/ZipRecruiter pages that reject direct reads. Do not add ad-hoc scraping code inside Agent A.
