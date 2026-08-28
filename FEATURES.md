# Expedient Employment Feature List

A complete inventory of what the application does. For install instructions see [README.md](README.md); for known limitations see [ISSUES.md](ISSUES.md).

## Pipeline stages

1. **Discovery**
   - Multi-board search of LinkedIn, Indeed, Glassdoor, and ZipRecruiter through [JobSpy](https://github.com/speedyapply/JobSpy), with board-isolated calls so each board receives only the parameters it supports.
   - Run-scoped circuit breaker: a board that returns HTTP 400/403 is not retried during that run.
   - Automatic fallback: empty, errored, or circuit-broken board coverage is routed through [WebClaw](https://github.com/0xMassi/webclaw) search.
   - Session-aware reading of job boards you have logged into yourself via the optional local [Agent Web Browser](https://github.com/BarnsL/agent-web-browser) bridge (read-only, sanitized visible text, exact first-party board hosts only).
   - Key-free ingestion: paste job URLs directly (`ingest`) or supply a URLs file — no search API key required.

2. **Verification**
   - Every discovered result is resolved to the employer's own application page (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, employer career sites).
   - WebClaw active-page verification gate: closed, generic, mismatched, or unverifiable postings are excluded **before** scoring.
   - JSON-LD `JobPosting` facts are preferred; page metadata and main content are fallbacks; optional WebClaw LLM field extraction can fill gaps.

3. **Deterministic scoring**
   - Five-part explainable rubric: title alignment 35%, demonstrated skills 30%, experience fit 15%, location/work-mode 10%, responsibility overlap 10%.
   - Every score ships with component breakdowns, matched evidence, and explicit gaps — decision support, never a black box.
   - Excluded-seniority terms and named requirement gaps reduce the score.
   - Optional AI re-ranking through WebClaw blends at most 30% AI / 70% deterministic, so unexplained swings are bounded.
   - The deterministic score works with zero API keys and no network.

4. **Optional ATS evidence (self-hosted Resume-Matcher)**
   - A user-controlled [Resume-Matcher](https://github.com/srbhr/Resume-Matcher) service (pinned Docker image, port 3000) can add a tailoring-preview ATS score, keyword gaps, and recommendations.
   - Requires explicit per-use authorization (`--allow-resume-upload`); the deterministic score is always retained alongside it.
   - An external ATS preview below 60 routes an otherwise eligible role to `review`, never to automatic rejection.

5. **Approval-gated application helper**
   - Agent C prepares a private application packet from your explicitly consented private profile and corrected resume.
   - A dry-run browser plan and a pending approval receipt (bound to the exact packet SHA-256, job URL, and action) are created before anything external happens.
   - Only after you accept a per-role Paperclip confirmation can [browser-use](https://github.com/browser-use/browser-use) fill reviewed fields — restricted to the exact HTTPS host of the job posting.
   - `fill_only` sessions remove click, keyboard-submit, dropdown-selection, and JavaScript tools; those steps remain a manual handoff.
   - Unknown, sensitive, demographic, disability, veteran, or work-authorization questions always return to you.
   - A job is only marked `applied` after an employer success receipt; otherwise a field-by-field manual handoff is preserved.

## Paperclip agent team

Coordinated by [Paperclip](https://github.com/paperclipai/paperclip) (localhost, port 3100, isolated `.paperclip-runtime/` data directory). All agents are provisioned **paused**; resuming one is always your decision.

| Agent | Role | What it does | External authority |
|---|---|---|---|
| **Agent A — Recruiter** | Discovery lead | One bounded JobSpy call per board, records exact status/coverage, routes missing coverage to WebClaw, resolves employer URLs, hands verified job IDs to Agent B | Public discovery and verification only |
| **Agent B — Verifier** | Independent match analyst | Re-verifies freshness, employer source, requirements, evidence, and gaps; returns `apply`, `review`, or `skip`; optionally adds explicitly authorized Resume-Matcher ATS evidence | Resume upload only after explicit consent |
| **Agent C — Application Assistant** | Approval-gated helper | Builds the private packet, creates the hash-bound pending receipt, requests per-role confirmation, and only then performs the approved browser action | Only within an accepted confirmation for the exact packet/action |

- Instruction bundles live in `paperclip/agents/agent-{a,b,c}/` (`AGENTS.md`, `HEARTBEAT.md`, `SOUL.md`, `TOOLS.md`).
- The handoff graph and authority table are in `paperclip/PIPELINE_GRAPH.md`; the operating procedure is in `docs/PAPERCLIP_AGENTS.md`.
- Provisioning is idempotent: company, goal, project, three paused agents, and three starter issues (AIJ-1/2/3).
- Safe adapter defaults: project-local pinned Codex executable, `workspace-write` sandbox, approval/sandbox bypass disabled.

## Desktop GUI (Electron + React)

| Page | Features |
|---|---|
| **Dashboard** | Pipeline doctor diagnostics, service health cards (Agent Web Browser, Paperclip, Resume-Matcher), quick actions |
| **Search** | Query/location/freshness controls, live streaming run log, runs Agent A discovery end-to-end |
| **Jobs** | Reads the generated CSV shortlist into a sortable table; opens the interactive HTML report |
| **Agents** | Lists Paperclip agents, roles, and paused/running status from the control plane |
| **Browser** | Per-site login tabs (LinkedIn, Glassdoor, ZipRecruiter, Indeed) with persistent sessions, plus standalone Agent Web Browser launch |
| **Settings** | JSON editors for `profile.json`, `searches.json`, `access_policy.json`, and `agent_web_browser.json` with validate-before-save and automatic `.bak` backups |
| **Paperclip** | Embedded control-plane page with **Engine Start** button |
| **Resume-Matcher** | Embedded Resume-Matcher page with **Engine Start** button |
| **Assistant** | Durable provider-aware chat, message queue, edit/cancel/retry controls, local images, model discovery, and typed tool events |
| **Automations** | Interval and daily schedules, enable/disable controls, due-run execution, history, and Windows background wake installation |
| **Web Workbench** | Typed tool catalog, JSON workflow editor, dry-run validation, bounded execution, and structured results |
| **Applications** | Application lifecycle dashboard, user outcome flags, undo, local draft packets, and report export |

- Services auto-launch with the app on a best-effort basis (Paperclip via Node, Resume-Matcher via Docker) without blocking window creation.
- Single-instance window; child processes spawned by the app are cleaned up on quit.
- Chromium sandboxing and context isolation are enabled. Webview destinations, permissions, popups, and navigation are restricted centrally.

## Assistant, tools, and scheduling

- Durable SQLite-backed conversations, messages, queue state, retries, attachments, and tool events.
- OpenAI-compatible provider adapter for HTTPS or fixed loopback services, with environment-owned credentials and bounded responses.
- Content-addressed image storage with explicit per-message provider upload consent.
- Typed tool broker with JSON Schema, read/local-write/external-draft/external-action policies, timeouts, cancellation, output caps, and content-free audit records.
- Pinned MIT only-cli runtime exposing its implemented read and navigation surface to the assistant and workflow engine.
- Validated workflow DAGs with exact result interpolation, dry run, retry, resume, cancellation, and circuit controls.
- Persistent interval or timezone-aware daily schedules, leases, coalescing, enable/disable state, and run history.
- Headless Windows wake task with limited privilege and overlap prevention.
- Scheduled job-hunting and local draft preparation, with employer-facing actions excluded from scheduler authority.

## Web intelligence

- Public URL policy requiring HTTP(S), global DNS answers, and no URL credentials.
- DNS peer pin verification and redirect revalidation to reduce SSRF and rebinding exposure.
- Bounded response sizes, MIME types, crawl depth, link counts, cache state, and workflow results.
- Explicit challenge and login-handoff signals with cooldown and circuit behavior.
- No CAPTCHA bypass, fingerprint spoofing, credential replay, stealth timing, or concealed submission.

## Session persistence

- Job-board logins you perform in the built-in browser tabs or in Agent Web Browser persist locally (`data/site_sessions.json` records login state per site).
- The pipeline reads Agent Web Browser's local token only from `%LOCALAPPDATA%\agent-web-browser\api-token` and refuses the integration entirely if any unsafe upstream flag is enabled.

## Configuration files

| File | Purpose |
|---|---|
| `config/profile.json` | Candidate targets, locations, skills, evidence, scoring weights (generic template; copy to gitignored `config/profile.local.json` for your real data) |
| `config/searches.json` | Search queries, result counts, preferred direct-ATS domains |
| `config/job_schema.json` | Optional WebClaw/LLM extraction schema |
| `config/access_policy.json` | Session-site login URLs and blocked-response routing policy |
| `config/agent_web_browser.json` | Reviewed AWB repository/commit, loopback URL, read-only mode, refused unsafe flags |
| `config/application_profile.example.json` | Blank private-answer template for Agent C (consent starts disabled) |
| `.env` (gitignored) | API keys: `SERPER_API_KEY`, `WEBCLAW_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, service URLs |

## Diagnostics and testing

- `run.ps1 doctor` — checks Python, config validity, WebClaw resolution, keys, optional runtimes, and service URLs without making web requests.
- `run.ps1 demo` — ranks three fictional fixture jobs with no network or keys.
- `run.ps1 agent-demo` — offline three-agent contract test; asserts Agent C stops at `awaiting_review`.
- `scripts/test-paperclip.ps1` — verifies health, three paused agents, sandbox settings, starter issues, and an optional authenticated Codex probe.
- `python -m unittest discover -s tests` runs the complete standard-library test suite.
- `python -m job_pipeline.recruiting_acceptance --output reports/recruiting_acceptance.json` runs the deterministic multi-trial recruiting scale and privacy gate.
- `npm --prefix gui test`, `npm --prefix gui run lint`, and `npm --prefix gui run build` verify the renderer.
- `node --test gui/electron/*.test.cjs` verifies the Electron and control-service boundaries.

## Cross-platform support

- **Windows**: full support — PowerShell scripts, `run.cmd` fallback for locked-down policies, Inno Setup installer and portable zip builds.
- **macOS / Linux**: Python pipeline and GUI run with `pwsh` on PATH; electron-builder `dmg`/`AppImage` targets are defined (see `packaging/README.md`).
- The core Python layer is standard-library only; optional integrations (JobSpy, browser-use) are pinned in isolated environments so their dependencies never conflict.
