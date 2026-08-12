# Agent A Tools

Working directory: `$env:JOB_PIPELINE_PROJECT_ROOT`

- `./scripts/agent-run.cmd agent-a-find --location "San Francisco Bay Area" --location "San Jose, California" --hours-old 168 --fresh-days 7 --results-wanted 10 --max-results 10 --resume "$env:JOB_PIPELINE_RESUME"` - primary multi-board search using the default expanded junior recruiting title family, exact-geography gate, and top-10 limit.
- `data/agent_a_discovery.json` - board status/circuit breakers, applied/excluded counts, WebClaw/AWB diagnostics, geography decisions, and current-run shortlist IDs.
- `./run.cmd doctor` - validate WebClaw, keys, profile, and base runtime.
- `./run.cmd run --resume "$env:JOB_PIPELINE_RESUME" --max-jobs 30` - fallback WebClaw discovery, scrape, score, and report.
- `./run.cmd ingest --resume "$env:JOB_PIPELINE_RESUME" URL...` - ingest explicit employer/ATS URLs.
- `./run.cmd agent-a --fresh-days 7 --min-score 72` - write structured recruiter findings for stored jobs.
- `reports/job_matches.html` - interactive ranking report containing only the current run's top 10 or fewer verified roles.
- `data/agent_a_findings.json` - machine-readable handoff to Agent B.

JobSpy is the primary board-discovery boundary. WebClaw remains the direct-page extraction and fallback-search boundary. Agent Web Browser is an optional read-only session bridge for Glassdoor/ZipRecruiter pages that reject direct reads. The applied registry, active-page check, geography gate, known-date freshness gate, and 10-result cap are mandatory. Do not add ad-hoc scraping code inside Agent A.
