# Application actions and function reference

This document explains every user action, the complete application function surface, the data it reads or changes, and how the WebClaw reference was applied.

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

## End-to-end action map

```text
Configured searches
      |
      v
WebClaw search (Serper) ----> reviewable discovered_urls.txt
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

The PowerShell wrapper maps this action to Python `unittest`. Tests cover privacy redaction, canonical URLs, JSON-LD normalization, relevant-vs-unrelated ranking, SQLite, and both report formats.

## Data and side effects

| Path | Purpose | Contains resume contact data? |
|---|---|---:|
| `config/profile.json` | Curated candidate evidence, targets, preferences, and weights | No |
| `config/searches.json` | Discovery queries and direct-ATS priority list | No |
| `data/jobs.sqlite3` | Extracted public job text, scores, runs, and manual states | No |
| `data/discovered_urls.txt` | Search results selected for possible ingestion | No |
| `reports/job_matches.html` | Interactive local shortlist | No |
| `reports/job_matches.csv` | Spreadsheet-ready shortlist | No |
| `logs/pipeline.log` | Operational diagnostics with known key patterns redacted | No by design |

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
| `command_doctor(args, root)` | Implements the prerequisite/configuration diagnostic action. |
| `command_profile(args, root)` | Implements safe resume extraction validation. |
| `command_search(args, root)` | Implements discovery-only output. |
| `command_ingest(args, root)` | Implements explicit URL ingestion, scoring, and export. |
| `command_score(args, root)` | Implements offline re-scoring plus optional AI calls. |
| `command_report(args, root)` | Implements network-free report regeneration. |
| `command_status(args, root)` | Implements manual application state updates. |
| `command_run(args, root)` | Implements the full production pipeline. |
| `command_demo(args, root)` | Implements the deterministic fixture smoke test. |
| `_add_resume_option(parser)` | Adds the shared DOCX flag to applicable commands. |
| `_add_ai_options(parser, include_extract)` | Adds provider, model, AI score, and optional AI extraction flags. |
| `build_parser()` | Defines the complete argparse command tree and help text. |
| `main(argv)` | Loads `.env`, configures logging, dispatches, and maps expected errors to exit code 2. |

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

## Scope boundaries

The app researches, ranks, exports, and tracks. It intentionally does not log in to job boards, bypass access controls, submit applications, write cover letters as fact, send email, or message recruiters.
