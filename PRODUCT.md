# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Expedient Employment is a single-user Windows desktop control center for a job seeker who wants one place to discover roles, evaluate fit, prepare truthful application materials, operate approved agent tools, and review every consequential action.

## Product Purpose

The product automates repetitive job-search research and preparation without automating away the user's judgment or identity. Success means the application can discover and verify suitable roles, score and triage them deterministically, prepare reviewable drafts, explain every agent action, and preserve a complete local audit trail.

## Positioning

Expedient Employment combines a deterministic job pipeline, an approval-bound application workflow, a tool-using assistant, and a local automation workbench. Unlike a generic chatbot or one-off scraper, every tool call is typed, policy-classified, attributable to a run, and constrained by the same user approval contract.

## Operating Context

The user operates the Electron application on Windows. Scheduled runs may perform discovery, verification, extraction, scoring, deduplication, lifecycle updates, and draft preparation while the user is away. Employer-facing messages, submissions, and other representational actions remain queued for exact per-item approval.

The application works with local candidate data, resumes, screenshots or image attachments, job-board pages, direct employer pages, ATS pages, locally installed agent runtimes, Paperclip agents, and bounded browser sessions.

## Capabilities and Constraints

- Preserve the existing Expedient Employment workflow and incorporate every nonconflicting feature from the MIT-licensed Adeluna pipeline.
- Expose only-cli as a first-class assistant tool, including its read, open, inspect, navigation, and supported site-command surfaces.
- Recreate the appropriate Wigolo and Maxun capabilities as original MIT code. Do not copy or adapt AGPL source, tests, assets, prompts, schemas, or implementation structure.
- Keep the Python core compatible with the standard library except for existing optional provider integrations.
- Use SQLite for durable runs, jobs, applications, messages, attachments, schedules, approvals, and audit events.
- Treat scraped pages, attached images, model output, and tool output as untrusted data.
- Never guess candidate facts or silently fill unresolved application fields.
- Never implement CAPTCHA bypass, fingerprint spoofing, stealth drivers, credential replay, concealment-oriented timing, or unauthorized scraping.
- Detect challenges, throttle requests, honor cooldowns and access policy, and fail closed to user handoff.
- Bind consequential approvals to the exact reviewed payload so later mutations invalidate the approval.
- Keep credentials outside logs and source control, and bind local service APIs to loopback with authenticated requests.

## Brand Commitments

The product name is Expedient Employment. The existing dark desktop control-center identity remains the visual authority. The supplied Connection Assistant screenshot is a binding interaction reference for the assistant surface: provider and model controls, readiness status, transcript, image attachment, message composer, queue-aware sending, new conversation, and transcript clearing.

## Evidence on Hand

- Existing Electron and React application shell under `gui/`.
- Existing Python pipeline, SQLite store, agent contracts, provider adapters, approval receipts, and tests under `job_pipeline/` and `tests/`.
- Existing Paperclip role contracts under `paperclip/`.
- Current and Adeluna repository histories plus their MIT license files.
- only-cli repository and MIT license.
- User-supplied assistant screenshot used only as visual and interaction reference.
- Generated Understand Anything graph under `.ua/` for architecture inspection.

No customer testimonials, placement-rate claims, employer partnerships, or performance benchmarks have been supplied. Future interface copy must not invent them.

## Product Principles

- Automate preparation, preserve human representation.
- Explain every action and make every external side effect attributable.
- Prefer deterministic scoring and typed data over opaque model judgment.
- Keep the default experience local, reversible, and privacy-preserving.
- Earn trust through visible state, explicit boundaries, and reproducible evidence.

## Accessibility & Inclusion

All primary workflows must be keyboard operable, expose accessible names and status announcements, maintain visible focus, respect reduced-motion preferences, and meet WCAG 2.2 AA contrast targets.
