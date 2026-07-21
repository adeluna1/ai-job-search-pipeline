# Application actions and function reference

This document explains every user action, the complete Python application function surface, the Paperclip launcher surface, the data each action reads or changes, and how the WebClaw and Paperclip references were applied.

## WebClaw documentation reviewed

Implementation was based on these upstream sources from `0xMassi/webclaw`:

- `README.md`: install paths; CLI, REST, MCP, and SDK surfaces; local-first extraction; search and output formats.
- `CLAUDE.md`: crate boundaries, provider chain, CLI examples, hard rules, and build/test expectations.
- `crates/webclaw-cli/src/main.rs`: exact `search`, `--format json`, `--only-main-content`, `--stdin`, `--extract-json`, provider, model, and timeout flags.
- `crates/webclaw-core/src/types.rs`: `ExtractionResult`, `Metadata`, `Content`, links, images, and `structured_data` JSON output.
- `crates/webclaw-fetch/src/search.rs`: Serper result fields and the optional result-page extraction behavior.
- `crates/webclaw-llm/src/extract.rs`: JSON Schema prompt construction, JSON-only output, thinking-tag cleanup, and parsing behavior.
- Reference commit: `81e4ac2e93d9b160d9e36e28d65b7f92fad3a331` (2026-07-19).

The pipeline preserves WebClaw as a separate executable. The setup script resolves GitHub's current `latest` release, downloads the Windows x86_64 archive, verifies its SHA-256 checksum, and installs it under `tools/webclaw/`.

## Paperclip documentation reviewed

The control-plane implementation follows Paperclip's repository and agent-organization guidance:

- `README.md`: local installation, company structure, budgets, governance, and run coordination.
- Agent guide: roles, reporting lines, adapter configuration, instruction bundles, heartbeat behavior, and paused status.
- Server API schemas/routes from the pinned package: companies, goals, projects, agents, issues, instruction bundles, adapter diagnostics, and pause operations.
- Codex adapter package from the pinned Paperclip release: explicit `command`, `cwd`, `env`, `extraArgs`, timeout, and approval/sandbox bypass behavior.

Paperclip is installed as a pinned Node development dependency and runs with an isolated ignored data directory. Provisioning uses its localhost REST API because that preserves structured JSON reliably on Windows PowerShell.

## Specialist integration documentation reviewed

- `speedyapply/JobSpy` README, `jobspy.__init__.scrape_jobs`, provider models, and board implementations: simultaneous `site_name` calls; `hours_old`; result limits; normalized dataframe columns; LinkedIn description fetch; and board-specific rate/location behavior. Version `1.1.82`, reference commit `fda080a373e8226f3fd60635323f5da9af9892b1`.
- `srbhr/Resume-Matcher` README, FastAPI routers, request/response schemas, and ATS service: `GET /api/v1/health`, resume multipart upload, batch job upload, non-persisting improve preview, and the ATS score projection. Version `1.2.0`, reference commit `dd9b5c3b7a341a62c3a86f7a84e8e30786e6153d`.
- `browser-use/browser-use` README, Agent constructor, BrowserProfile domain controls, sensitive-data examples, form-filling examples, and application example. Version `0.13.6`, reference commit `2be09b6c5eb702a9287684b42b27e7042a1aba29`.
- Several auto-apply repositories were reviewed only to identify common form control families. Their code was not copied. The implementation intentionally excludes guessed answers, anti-detection behavior, credential automation, and reusable blanket submission authority.

The current Resume-Matcher backend requires Python 3.13 and runs as a separate user-controlled service. JobSpy and browser-use run in separate ignored environments because their pinned `markdownify` requirements conflict.

## End-to-end action map

```text
Configured searches
      |
      v
JobSpy multi-board call ----> provider diagnostics + normalized jobs
      |
      +---- degraded coverage ----> WebClaw search fallback
      |
      v
WebClaw scrape --format json --only-main-content
      |
      +----> JSON-LD JobPosting facts (preferred)
      +----> metadata/content fallbacks
      +----> optional WebClaw LLM field extraction
      |
      v
Normalized Job ----> SQLite deduplication and application state
      |
      v
Deterministic 5-part score ----> optional bounded LLM score blend
      |
      v
Interactive HTML shortlist + CSV export
      |
      v
Agent A freshness/source triage
      |
      v
Agent B independent live verification
      |
      +---- optional explicit resume upload ----> Resume-Matcher ATS preview
      |
      +----> review / skip
      |
      v
Agent C private packet ----> hash-bound pending receipt
      |
      v
Paperclip per-role confirmation ----> browser-use exact-domain action or handoff
```

## User actions

### `doctor`

Reads config and environment state, resolves WebClaw, calls `webclaw --version`, and reports which discovery/AI credential paths are available. It does not perform web requests or change job data.

### `profile --resume FILE.docx`

Reads the DOCX locally, extracts text in document order, redacts phone/email/LinkedIn patterns, and prints only character count, redaction state, and recognized professional terms. It never writes a resume copy or extracted resume body.

### `search --max-jobs N`

Runs every query in `config/searches.json` through `webclaw search ... --format json`, removes obvious non-job URLs, canonicalizes and deduplicates results, prioritizes configured direct ATS domains, and writes `data/discovered_urls.txt`. It does not scrape or score the URLs.

### `ingest [URL ...] [--urls-file FILE]`

Scrapes supplied public job pages concurrently through WebClaw, normalizes them, stores them in SQLite, re-scores every stored job, and regenerates reports. Per-URL failures are isolated and recorded in the local log. `--ai-extract` optionally uses WebClaw's schema extraction after the normal scrape.

### `score [--resume FILE.docx] [--ai]`

Re-runs matching for all stored jobs. With `--resume`, redacted resume evidence is used in memory. With `--ai`, the app asks WebClaw's provider chain for a constrained second score and blends it 30% AI / 70% deterministic by default.

### `report --min-score N`

Reads existing SQLite data and rewrites `reports/job_matches.html` and `reports/job_matches.csv`. It performs no network or AI calls.

### `status JOB_ID STATE --notes TEXT`

Updates only the manual application tracker. Supported states are `new`, `saved`, `applied`, `interviewing`, `offer`, `rejected`, and `withdrawn`.

### `run`

Executes the complete search -> scrape -> normalize -> store -> score -> report flow. `--max-jobs` bounds scraping; `--concurrency` bounds parallel WebClaw processes. No application is submitted.

### `demo`

Loads three fictional fixture jobs, ranks them without WebClaw or any key, stores them in `data/demo.sqlite3`, and writes `reports/demo_matches.html` plus `.csv`. It is the fastest operational smoke test.

### `test`

The PowerShell wrapper maps this action to Python `unittest`. Tests cover privacy redaction, canonical URLs, JSON-LD normalization, relevant-vs-unrelated ranking, corrected Ashby evidence, SQLite, both report formats, and the three-agent stop-at-review contract.

### `agent-profile-init`

Copies the blank private answer template to ignored `data/application_profile.json`. It refuses to overwrite an existing profile unless `--force` is supplied. The template starts with contact-use consent disabled.

### `agent-a [JOB_ID ...] [--fresh-days N]`

Reads selected or all stored jobs and scores, validates each normalized posting, classifies the source, and calculates age only from parseable ISO dates. It uses `config.scoring.strong_fit_threshold` unless `--min-score` explicitly overrides it. It writes `data/agent_a_findings.json`; an unavailable date remains unknown rather than being guessed.

### `agent-a-find [--query TEXT] [--site BOARD] [--hours-old N]`

Runs Agent A's replaceable discovery boundary. The JobSpy implementation sends all selected boards in one bounded call, normalizes dataframe records, stores and scores them, regenerates the report, writes `data/agent_a_discovery.json`, and reuses `agent-a` triage for the returned IDs. A board without results is recorded as degraded/unknown coverage; successful boards are retained. The validated default boards are LinkedIn, Indeed, Glassdoor, and ZipRecruiter.

### `agent-b --job-id JOB_ID ... [--fresh-days N] [--live]`

Independently evaluates Agent A's leads. With `--live`, it re-scrapes the public posting through WebClaw and records invalid pages, title/company discrepancies, freshness, evidence, gaps, blockers, and one recommendation: `apply`, `review`, or `skip`. `--resume-matcher` requires `--resume` and `--allow-resume-upload`; it calls a reviewed service URL and adds tailoring-preview ATS evidence. An otherwise eligible role with external ATS score below 60 becomes `review`, not `skip`. Results go to `data/agent_b_reviews.json`.

### `agent-c JOB_ID --resume FILE --application-profile FILE`

Requires an Agent B `apply` recommendation, an explicitly consented private profile, and the corrected resume. It writes a review-required packet under ignored `data/application_packets/` and stops. The packet includes a common ATS form catalog, manual-only topics, and `external_submission_performed: false`. It always starts with `approval: pending`; this command has no browser or submission function.

### `agent-c-browser JOB_ID [--execute] [--submit]`

Without `--execute`, creates a public-safe dry-run plan and a pending private approval receipt. No browser package is imported and no data is transmitted. Execution validates the exact job ID, HTTPS URL, packet SHA-256, decision, action, reviewer, timestamp, and optional expiry before importing browser-use. `--submit` requires `allowed_action: fill_and_submit`; otherwise only `fill_only` can run. The browser profile allows only the job host, candidate values are passed as domain-scoped sensitive data, and unknown or sensitive questions require a human.

### `agent-demo --resume FILE`

Runs all three specialist contracts on fictional fixtures without WebClaw or a network call. Agent C uses a temporary fictional profile and must finish at `awaiting_review`, never submission. It writes `reports/agent_demo.json`.

### Paperclip launch and setup actions

| Script | Action |
|---|---|
| `scripts/start-paperclip.ps1` | Starts the isolated localhost service only when its health endpoint is not already ready. |
| `scripts/paperclip-server.ps1` | Runs Paperclip in the foreground with this repository's ignored runtime directory. |
| `scripts/setup-paperclip.ps1` | Idempotently creates/updates the company, goal, project, three agents, instruction bundles, and backlog issues; reapplies safe Codex settings and pauses every agent. |
| `scripts/test-paperclip.ps1` | Verifies health, the three paused agents, bypass-disabled workspace sandboxing, starter issues, run count, and optionally the authenticated Codex hello probe. |
| `scripts/paperclip.ps1` | Passes arguments to the pinned Paperclip CLI with the isolated data directory. |
| `scripts/_paperclip-common.ps1` | Resolves project-local binaries, sets runtime paths/telemetry preference, implements the CLI wrapper, and checks localhost health. |
| `scripts/install-agent-integrations.ps1` | Creates independent pinned JobSpy and browser-use virtual environments and validates imports. |
| `scripts/agent-run.ps1` / `.cmd` | Selects the JobSpy runtime for `agent-a-find` or browser-use runtime for `agent-c-browser`. |
| `run.cmd` | Runs `run.ps1` with a process-local execution-policy bypass for locked-down Windows systems. |

## Data and side effects

| Path | Purpose | Contains resume contact data? |
|---|---|---:|
| `config/profile.json` | Curated candidate evidence, targets, preferences, and weights | No |
| `config/searches.json` | Discovery queries and direct-ATS priority list | No |
| `data/jobs.sqlite3` | Extracted public job text, scores, runs, and manual states | No |
| `data/discovered_urls.txt` | Search results selected for possible ingestion | No |
| `data/agent_a_findings.json` | Agent A freshness/source decisions | No |
| `data/agent_a_discovery.json` | Requested boards, per-board counts, normalization errors, and fallback recommendation | No |
| `data/agent_b_reviews.json` | Agent B evidence, gaps, blockers, and recommendations | No |
| `data/application_profile.json` | Explicitly consented private application answers | Yes; ignored by Git |
| `data/application_packets/` | Per-job private packet with contact data and resume path | Yes; ignored by Git |
| `data/application_approvals/` | Hash-bound pending/accepted per-job receipts | Yes; ignored by Git |
| `data/browser_plans/` | Dry-run metadata without candidate field values | No; ignored by Git |
| `data/application_results/` | Browser-use final result requiring employer-receipt verification | May; ignored by Git |
| `reports/job_matches.html` | Interactive local shortlist | No |
| `reports/job_matches.csv` | Spreadsheet-ready shortlist | No |
| `reports/agent_demo.json` | Fictional offline specialist test result | No |
| `reports/paperclip_setup.json` | Paperclip IDs and safety state | No |
| `reports/paperclip_validation.json` | Reproducible agent, issue, sandbox, and adapter checks | No |
| `logs/pipeline.log` | Operational diagnostics with known key patterns redacted | No by design |
| `.paperclip-runtime/` | Ignored Paperclip database, configuration, and logs | May contain run text; ignored by Git |

The optional resume body exists only in process memory. Optional LLM scoring sends the contact-redacted resume evidence to the provider configured through WebClaw; omit `--ai` to keep matching entirely local.

## Function reference

### `job_pipeline.cli`

| Function | Action |
|---|---|
| `project_root()` | Resolves the application root from the installed package location. |
| `load_profile(root)` | Reads the contact-free profile and rejects weights that do not sum to 1. |
| `_is_probable_job_url(url)` | Drops obvious articles, profiles, salary pages, and non-job results. |
| `discover_urls(client, config, max_jobs)` | Runs configured WebClaw searches, deduplicates, prioritizes ATS domains, and caps results. |
| `_ai_extract_job_fields(...)` | Sends already-extracted untrusted posting text through WebClaw JSON Schema extraction. |
| `_scrape_one(...)` | Worker boundary that scrapes and normalizes exactly one URL. |
| `ingest_urls(...)` | Runs bounded parallel scrape workers and persists successes on the main thread. |
| `score_jobs(...)` | Deterministically scores every job and optionally invokes the AI blend. |
| `_read_urls_file(path)` | Reads non-comment URL lines from a UTF-8 text file. |
| `_client(root, args)` | Builds the WebClaw subprocess adapter from shared CLI options. |
| `_resume_text(args)` | Reads and contact-redacts an optional DOCX resume in memory. |
| `_export(...)` | Joins ranked records and writes HTML plus CSV. |
| `command_doctor(args, root)` | Reports WebClaw/configuration state, optional JobSpy/browser runtimes, and configured Resume-Matcher URL without calling that service. |
| `command_profile(args, root)` | Implements safe resume extraction validation. |
| `command_search(args, root)` | Implements discovery-only output. |
| `command_ingest(args, root)` | Implements explicit URL ingestion, scoring, and export. |
| `command_score(args, root)` | Implements offline re-scoring plus optional AI calls. |
| `command_report(args, root)` | Implements network-free report regeneration. |
| `command_status(args, root)` | Implements manual application state updates. |
| `command_run(args, root)` | Implements the full production pipeline. |
| `command_demo(args, root)` | Implements the deterministic fixture smoke test. |
| `_agent_database(args, root)` | Resolves the production, demo, or explicitly selected database for specialist commands. |
| `_selected_jobs(store, job_ids)` | Returns all or selected stored jobs and rejects unknown IDs. |
| `command_agent_profile_init(args, root)` | Creates the ignored Agent C private-answer template without silent overwrite. |
| `command_agent_a(args, root)` | Runs recruiter triage and writes structured findings. |
| `command_agent_a_find(args, root)` | Runs the selected discovery provider, persists/scored jobs, writes provider diagnostics, and reuses Agent A triage. |
| `command_agent_b(args, root)` | Runs independent stored/live analysis and writes structured reviews. |
| `command_agent_c(args, root)` | Validates the apply handoff and prepares one pending private packet. |
| `command_agent_c_browser(args, root)` | Creates a pending approval/dry-run plan or invokes the exactly approved browser-use runner. |
| `command_agent_demo(args, root)` | Exercises A, B, and C offline and asserts that C stops at review. |
| `_add_resume_option(parser)` | Adds the shared DOCX flag to applicable commands. |
| `_add_ai_options(parser, include_extract)` | Adds provider, model, AI score, and optional AI extraction flags. |
| `build_parser()` | Defines the complete argparse command tree and help text. |
| `main(argv)` | Loads `.env`, configures logging, dispatches, and maps expected errors to exit code 2. |

### `job_pipeline.agents`

| Function/class/method | Action |
|---|---|
| `_parse_posted_datetime(value)` | Parses ISO timestamps conservatively and returns `None` for ambiguous/relative dates. |
| `_source_quality(url)` | Classifies direct ATS, major board, or employer/other sources. |
| `RecruiterFinding.to_dict()` | Serializes Agent A's active/fresh/age/source decision and reasons. |
| `RecruiterAgent.inspect(job, fresh_days, now)` | Validates a normalized job and measures stated age against the freshness window. |
| `MatchAnalysis.to_dict()` | Serializes Agent B's score, decision, evidence, insights, blockers, and discrepancies. |
| `MatchAnalystAgent.analyze(...)` | Optionally re-scrapes the role, independently verifies facts, and returns `apply`, `review`, or `skip`. |
| `ApplicationDraft.to_dict()` | Serializes Agent C's non-sensitive workflow result and packet location. |
| `load_application_profile(path)` | Loads private answers and requires explicit contact-use consent. |
| `ApplicationAgent.prepare(...)` | Writes a truthful, review-required private packet and lists every unresolved field; never submits. |

### `job_pipeline.integrations.jobspy_source`

| Function/class/method | Action |
|---|---|
| `DiscoveryProvider.search(...)` | Protocol that keeps Agent A independent of any one discovery repository. |
| `_clean(value)` | Normalizes scalar and pandas-style missing values without importing pandas. |
| `_date_text(value)` | Serializes Python/pandas date-like values conservatively. |
| `_json_safe(value)` | Converts dataframe/numpy values into JSON-safe primitives. |
| `_salary_text(row)` | Formats JobSpy salary columns for the canonical model. |
| `normalize_jobspy_row(row)` | Maps one JobSpy record to `Job`, preferring the direct employer URL. |
| `JobSpySource.__init__(scraper)` | Accepts an injectable scraper for deterministic tests. |
| `JobSpySource._load_scraper()` | Lazily imports JobSpy and explains the isolated installer when missing. |
| `JobSpySource.search(...)` | Executes one bounded multi-board call, normalizes usable records, and records per-board diagnostics. |

### `job_pipeline.integrations.resume_matcher`

| Function/class/method | Action |
|---|---|
| `ATSAssessment.to_dict()` | Projects the stable score, sub-scores, gaps, injectable terms, and recommendations. |
| `ResumeMatcherClient.__init__(...)` | Normalizes the API base URL and accepts an injectable transport. |
| `ResumeMatcherClient._default_transport(...)` | Performs bounded stdlib HTTP requests and maps network/JSON failures. |
| `ResumeMatcherClient._json(...)` | Encodes JSON request bodies and common headers. |
| `ResumeMatcherClient.health()` | Checks the upstream process-only health endpoint. |
| `ResumeMatcherClient.upload_resume(path)` | Builds multipart form data and returns a processed resume ID. |
| `ResumeMatcherClient.upload_jobs(descriptions, resume_id)` | Uploads a batch and preserves returned ID order. |
| `ResumeMatcherClient.preview(resume_id, job_id)` | Requests the non-persisting improvement preview and extracts ATS evidence. |

### `job_pipeline.integrations.browser_use_runner`

| Function/class/method | Action |
|---|---|
| `packet_sha256(path)` | Computes the exact packet digest used by the approval gate. |
| `build_form_answer_catalog(candidate)` | Maps common controls to reviewed values and routes sensitive/unknown fields to a human. |
| `BrowserApplicationPlan.to_dict()` | Serializes non-secret plan metadata. |
| `BrowserUseRunner.__init__(packet_path)` | Loads the packet and requires a valid exact-host HTTPS job URL. |
| `BrowserUseRunner.approval_template()` | Creates a pending receipt bound to job, URL, and packet digest. |
| `BrowserUseRunner.write_approval_template(path)` | Writes only when no receipt exists, preserving reviewer decisions. |
| `BrowserUseRunner._validate_approval(path, action)` | Enforces packet/job/URL/action/reviewer/time/expiry invariants. |
| `BrowserUseRunner.plan(action, approval_path)` | Reports pending, invalid, or approved state without exposing answers. |
| `BrowserUseRunner._task(action)` | Creates a no-guess, no-bypass, fill-only or explicitly submit-capable instruction. |
| `BrowserUseRunner.tool_exclusions(action)` | Hard-removes click, keyboard-submit, and JavaScript tools from fill-only sessions. |
| `BrowserUseRunner.execute(...)` | Lazily imports browser-use, locks the domain, scopes sensitive data, and runs within step bounds. |

### `job_pipeline.webclaw`

| Function/method | Action |
|---|---|
| `WebClawClient.__init__(...)` | Resolves WebClaw once and stores the default timeout. |
| `WebClawClient._resolve_binary(explicit)` | Searches CLI flag, `WEBCLAW_BIN`, local tools, and PATH in order. |
| `WebClawClient._run(args, stdin_text, timeout)` | Runs the process, keeps stdout machine-readable, logs redacted stderr, and raises concise failures. |
| `WebClawClient.version()` | Calls `webclaw --version`. |
| `WebClawClient.search(...)` | Calls the Serper-backed `search` subcommand and validates its result array. |
| `WebClawClient.scrape(url)` | Calls standard JSON extraction with main-content filtering. |
| `WebClawClient.extract_json_from_text(...)` | Calls `--stdin --extract-json @schema` with optional provider/model selection. |

### `job_pipeline.resume`

| Function | Action |
|---|---|
| `extract_docx_text(path)` | Reads `word/document.xml`, collecting paragraphs and table-cell text in order. |
| `redact_contact_details(text)` | Masks emails, North American phone patterns, and LinkedIn URLs. |
| `resume_context(path)` | Returns redacted in-memory resume text or an empty string. |
| `resume_terms(text)` | Finds only conservative job-relevant terms from an allowlisted catalog. |

### `job_pipeline.jobs`

| Function/method | Action |
|---|---|
| `Job.to_dict()` | Converts a normalized job into JSON-compatible data. |
| `Job.from_dict(data)` | Creates a job from recognized dataclass fields. |
| `_iter_json_objects(value)` | Recursively walks nested JSON-LD objects and arrays. |
| `_find_job_posting(structured_data)` | Selects the first `@type: JobPosting` object. |
| `_strip_html(value)` | Removes executable/style content, tags, and entity encoding. |
| `_organization_name(value)` | Normalizes organization object/string syntax. |
| `_location_text(value)` | Flattens Place/PostalAddress values and arrays. |
| `_salary_text(value)` | Flattens common MonetaryAmount/QuantitativeValue shapes. |
| `_split_page_title(value)` | Provides a conservative title/company fallback. |
| `_company_from_markdown(url, markdown)` | Recovers a direct-ATS company name from employer logo alt text or URL slug. |
| `infer_work_mode(location, description)` | Classifies remote, hybrid, onsite, or unknown from stated text. |
| `infer_required_years(description)` | Extracts the lowest explicit experience requirement. |
| `validate_job(job)` | Rejects empty shells, generic career indexes, and redirected/expired role pages. |
| `normalize_webclaw_job(url, payload, ai_fields)` | Merges fields in trust order: JSON-LD, WebClaw metadata/content, then optional AI gaps. |
| `job_from_fixture(data)` | Builds a normalized demo/test record. |

### `job_pipeline.matching`

| Function/method | Action |
|---|---|
| `MatchResult.to_dict()` | Converts the full explanation and scores to JSON-compatible data. |
| `_contains_phrase(text, phrase)` | Performs normalized phrase matching with boundaries for abbreviations. |
| `_skill_matches(profile_skills, job_text)` | Matches demonstrated skills through explicit alias lists. |
| `_title_score(title, targets)` | Uses containment, sequence similarity, and token overlap across target titles. |
| `_experience_score(candidate_years, required_years)` | Scores explicit minimum experience and emits a shortfall gap. |
| `_location_score(job, preferred, modes)` | Scores configured cities/work modes without assuming unstated flexibility. |
| `_responsibility_score(keywords, job_text)` | Measures responsibility phrase coverage. |
| `_fit_label(score, threshold)` | Maps a numeric score to a label and next action. |
| `_explicit_requirement_gaps(job_text, candidate_text)` | Flags named ATS/HRIS/compliance tools stated by the posting but absent from resume evidence. |
| `score_job(job, profile, resume_text)` | Computes all five components, penalties, evidence, gaps, and baseline result. |
| `_ai_schema()` | Defines the constrained fit-evaluation JSON Schema and prompt-injection warning. |
| `apply_ai_score(...)` | Calls WebClaw AI, catches provider failures, and performs the bounded blend. |

### `job_pipeline.storage`

| Function/method | Action |
|---|---|
| `JobStore.__init__(path)` | Opens SQLite, enables WAL/foreign keys, and creates the schema. |
| `JobStore.close()` | Commits and closes the connection. |
| `JobStore.__enter__()` / `__exit__(...)` | Provides context-managed database lifetime. |
| `JobStore.begin_run(action)` | Creates a run audit row. |
| `JobStore.finish_run(...)` | Records finish time and observable counts. |
| `JobStore.upsert_job(job)` | Inserts or refreshes a canonical URL and initializes application state. |
| `JobStore.upsert_match(match)` | Stores the latest score and explanation. |
| `JobStore.jobs()` | Rehydrates every normalized job. |
| `JobStore._job_from_row(row)` | Rehydrates one `Job` from a SQLite row. |
| `JobStore.job(job_id)` | Returns one stored job or `None`. |
| `JobStore.match(job_id)` | Returns one stored `MatchResult` or `None`. |
| `JobStore.ranked(min_score)` | Joins jobs, matches, and application state in score order. |
| `JobStore.set_status(job_id, status, notes)` | Updates manual tracking for an existing job. |
| `JobStore.count_jobs()` | Returns the number of unique job URLs. |
| `JobStore.upsert_jobs(jobs)` | Persists a sequence, used by the deterministic demo. |

### `job_pipeline.report`

| Function | Action |
|---|---|
| `_e(value)` | Escapes untrusted data for HTML. |
| `_chips(values, css_class)` | Renders short evidence tags. |
| `_list_items(values, empty)` | Renders explanation lists with an explicit empty state. |
| `_card(record)` | Renders one complete job scorecard. |
| `export_html(records, path, threshold)` | Writes the responsive offline dashboard and client-side filters. |
| `export_csv(records, path)` | Writes an Excel-friendly UTF-8 CSV. |
| `export_reports(...)` | Writes both formats and returns their paths. |

### `job_pipeline.util`

| Function | Action |
|---|---|
| `utc_now()` | Returns second-precision UTC ISO timestamps. |
| `read_json(path)` / `write_json(path, value)` | Performs UTF-8 JSON I/O. |
| `load_dotenv(path)` | Loads simple environment entries without overriding real environment variables. |
| `configure_logging(path, verbose)` | Configures file logging and optional stderr debug output. |
| `normalize_space(value)` | Collapses whitespace safely. |
| `normalize_term(value)` | Case-folds and strips matching punctuation. |
| `canonical_url(url)` | Removes tracking/fragments and normalizes scheme, host, and path. |
| `stable_id(*parts)` | Creates a deterministic 16-character SHA-256-based ID. |
| `unique_preserving_order(values)` | Case-insensitively deduplicates strings. |
| `redact_secrets(value)` | Masks common API-key shapes in error/log text. |

## Failure behavior

- Search without `SERPER_API_KEY`: WebClaw error is surfaced without printing a key.
- One job page fails: the other jobs continue; the failed URL is logged.
- Job lacks JSON-LD: metadata and extracted main content are used.
- Optional LLM unavailable: deterministic result remains final and the AI reason records the failure.
- Resume cannot be read: the command exits with code 2 and no partial resume artifact.
- Unknown job ID on `status`: no database row is created; exit code is 2.
- Missing Agent A date: freshness remains unknown and Agent B must review.
- JobSpy partial board failure: successful results remain usable and missing boards are reported for fallback judgment.
- JobSpy total failure: `DiscoveryError` exits cleanly; another provider can implement the unchanged `DiscoveryProvider` protocol.
- Live Agent B validation fails: recommendation becomes `skip` with a blocker.
- Resume-Matcher is not authorized: no resume upload occurs and Agent B stays deterministic.
- Resume-Matcher is unavailable after authorization: its error is recorded or surfaced without corrupting the deterministic match.
- Agent C profile consent is false: no packet is produced.
- Agent C fields are missing: packet is `needs_information` and external action is forbidden.
- Agent C approval is pending, expired, mismatched, or approved for another action: browser-use is not imported or executed.
- Paperclip setup reruns: existing named entities are reused, safe adapter settings are reapplied, and every agent is paused.

## Scope boundaries

Agents A and B research, rank, verify, export, and track only. Agent C's packet command never acts externally. Its separate browser command can fill or submit only after an accepted, role-specific receipt matches the exact packet, URL, and action. It never bypasses access controls, guesses candidate facts, treats a prior approval as reusable, sends email, messages recruiters, or marks `applied` without an employer success receipt.
