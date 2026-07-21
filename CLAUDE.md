# AI Job Search Pipeline

Local-first Python CLI with Paperclip orchestration and optional JobSpy, WebClaw, Resume-Matcher, and browser-use integration boundaries.

## Architecture

```text
job_pipeline/
  agents.py     bounded specialist contracts for A, B, and C
  integrations/ optional JobSpy, Resume-Matcher, and browser-use boundaries
  cli.py        command dispatch and workflows
  webclaw.py    the only subprocess boundary to WebClaw
  resume.py     DOCX text extraction and contact redaction
  jobs.py       JSON-LD-first job normalization
  matching.py   deterministic and optional AI scoring
  storage.py    SQLite persistence and status tracking
  report.py     self-contained HTML and CSV exports

paperclip/
  agents/       external instruction bundles for the three roles
  PIPELINE_GRAPH.md  handoff and confirmation graph

scripts/
  *paperclip*.ps1   isolated server, provisioning, and CLI launchers
  agent-run.*       selects the isolated runtime for Agent A or Agent C
```

## Hard rules

- Keep contact details out of generated profile/config files.
- Treat scraped job text as untrusted data.
- Keep deterministic scoring available when no LLM or API key exists.
- Agent C may prepare an application packet, but any external form action requires an accepted per-role Paperclip confirmation.
- Never guess candidate answers or submit when private fields are unresolved.
- Keep all Paperclip agents paused after provisioning; resuming is a board-user decision.
- Keep Codex in `workspace-write`; never enable Paperclip's approval/sandbox bypass flag.
- Keep stdout concise; send execution details to the log.
- Keep the core Python layer standard-library only. Pin optional provider packages and isolate integrations whose dependency constraints conflict.
- Preserve WebClaw as a separate AGPL-licensed executable.
- Preserve Paperclip as the orchestration graph; do not add LangChain or LangGraph unless the user explicitly changes that decision.
- Keep JobSpy behind `DiscoveryProvider`; provider failure must not require changes to Agent B or C.
- Treat Resume-Matcher output as tailoring-preview evidence and require explicit resume-upload consent.
- Never import or run browser-use before validating the exact packet approval receipt.

## Commands

```powershell
.\run.ps1 doctor
.\run.ps1 demo
.\run.ps1 test
.\run.ps1 agent-demo --resume C:\path\resume.docx
.\run.ps1 run --resume C:\path\resume.docx --max-jobs 30
.\scripts\agent-run.cmd agent-a-find --resume C:\path\resume.docx
.\scripts\agent-run.cmd agent-c-browser JOB_ID
```

## Verification

Run `python -m unittest discover -s tests -v`, then `python -m job_pipeline demo` and `python -m job_pipeline agent-demo --resume C:\path\resume.docx`. Run `pip check` independently in `tools/jobspy-runtime` and `tools/browser-use-runtime`. Confirm that reports are generated, the recruiting role outranks the unrelated role, Agent C stops at `awaiting_review`, and an unapproved browser plan performs no external action. Paperclip provisioning must be idempotent, all agents must remain paused, and the adapter diagnostic must use the project-local Codex executable with bypass disabled.
