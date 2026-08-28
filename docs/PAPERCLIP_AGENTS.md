# Paperclip three-agent operating guide

## What Paperclip controls

Paperclip is the durable coordination layer. It owns the company, goal, project, issues, assignees, agent state, run history, and confirmation checkpoint. The Python layer exposes replaceable specialist adapters: JobSpy/WebClaw plus optional read-only Agent Web Browser for discovery, Resume-Matcher for optional ATS evidence, and browser-use for an exactly approved application action.

The setup creates this dependency graph:

```text
AIJ-1 Agent A discovery
        |
        v
AIJ-2 Agent B independent verification
        |
        +-- skip/review --> candidate decision
        |
        v
AIJ-3 Agent C private packet
        |
        v
per-role confirmation --> reviewed browser action or manual handoff
```

Paperclip remains the graph; LangGraph/LangChain are intentionally not dependencies. Repository libraries implement individual nodes, while Paperclip owns durable routing and human decisions.

The three agents are intentionally not interchangeable:

| Role | Primary judgment | May use contact data? | May act externally? |
|---|---|---:|---:|
| Agent A - Recruiter | Is this a fresh, plausible resume match? | No | No |
| Agent B - Verifier | Is the live posting genuinely worth applying to? | No | No |
| Agent C - Application Assistant | Are the packet and answers complete and truthful? | Only from the private profile | Only after a specific accepted confirmation |

## Install and provision

From the repository root:

```powershell
pnpm install
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-integrations.ps1 -JobSpy
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-agent-integrations.ps1 -BrowserUse
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-paperclip.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-paperclip.ps1 -ProbeCodex
```

Open [http://127.0.0.1:3100](http://127.0.0.1:3100). The setup command is safe to rerun: it finds entities by name, updates the safe Codex adapter settings and instruction bundles, creates missing starter issues, and refreshes existing starter issue descriptions.

Resume-Matcher is not started by Paperclip. Run its pinned `ghcr.io/srbhr/resume-matcher:1.2.0` image separately on port 3000, configure its LLM through the upstream UI, and authorize its URL/resume upload in the Agent B issue before use.

The control plane uses:

- a project-local, pinned Codex executable;
- `workspace-write` sandbox mode;
- `dangerouslyBypassApprovalsAndSandbox = false`;
- no configured Paperclip spend cap (`0` is displayed as unlimited), so set a company budget before resuming agents;
- paused agents after every provisioning run.

The isolated Paperclip database and logs live under `.paperclip-runtime/`, which is ignored by Git.

## Prepare private candidate answers

Create the ignored template:

```powershell
.\run.ps1 agent-profile-init
```

Review and fill `data/application_profile.json`. It is separate from `config/profile.json` because it can contain contact and eligibility information. Agent C refuses to load it until `consents.use_contact_for_applications` is explicitly set to `true`.

Do not put demographic, disability, veteran, or other voluntary self-identification defaults in the profile. Those questions should remain unresolved for a per-application decision.

## Run the workflow

1. In Paperclip, inspect AIJ-1 and resume Agent A only when the search objective is ready.
2. Agent A runs `scripts/agent-run.cmd agent-a-find`. The command attempts each JobSpy board once, opens a run-scoped circuit breaker for HTTP 400/403, routes missing coverage through WebClaw, optionally uses the authenticated read-only Agent Web Browser bridge when a discovered Glassdoor/ZipRecruiter page rejects direct reading, resolves employer application URLs, and writes the complete audit to `agent_a_discovery.json`.
3. Only WebClaw-verified active employer postings cross the scoring gate. Resume Agent B after that shortlist exists; Agent B records `apply`, `review`, or `skip` and may add Resume-Matcher only when the issue explicitly authorizes the target service URL and resume upload.
4. Resume Agent C only for an `apply` decision and only after the private profile is complete. Agent C runs `agent-c` to write an ignored packet under `data/application_packets/`.
5. Agent C runs `agent-c-browser` without `--execute` to create a dry-run plan and a pending receipt under `data/application_approvals/`.
6. Agent C requests a per-role confirmation naming the company, title, URL, packet SHA-256, unresolved questions, and whether authority is `fill_only` or `fill_and_submit`.
7. Pending, rejected, expired, mismatched, or ambiguous confirmation means stop. After acceptance, Agent C records the reviewer and timestamp in the ignored receipt; authority applies only to that packet hash and action.
8. The approved execution uses browser-use with an exact-domain allowlist. Mark a job `applied` only after the employer page shows a success receipt; otherwise preserve a handoff and keep it `saved`.

For a safe offline contract test that never opens a site or submits anything:

```powershell
.\run.ps1 agent-demo --resume "C:\path\to\resume.docx"
```

Expected final state: Agent A identifies the aligned fixture, Agent B recommends it, and Agent C returns `awaiting_review` with `approval=pending`.

## Command and artifact contracts

| Command | Reads | Writes | Network/external effect |
|---|---|---|---|
| `agent-a-find` | corrected resume, search objective | verified jobs, scores, report, `agent_a_discovery.json`, `agent_a_findings.json` | One JobSpy attempt per board; WebClaw search, optional AWB visible-text recovery, employer resolution, and active-page verification |
| `agent-a` | stored jobs, matches | `data/agent_a_findings.json` | None |
| `agent-b --job-id JOB_ID` | stored job, match, Agent A finding | `data/agent_b_reviews.json` | None unless `--live`; Resume-Matcher additionally requires explicit upload consent |
| `agent-c JOB_ID` | Agent B review, private profile, corrected resume path | `data/application_packets/JOB_ID.json` | Never submits |
| `agent-c-browser JOB_ID` | private packet | pending receipt and dry-run plan | None unless `--execute`; `--submit` also requires exact `fill_and_submit` approval |
| `agent-demo` | fixture jobs, corrected resume | demo database, private fixture packet, `reports/agent_demo.json` | None |

## Failure and safety behavior

- Missing or unparseable posting date: Agent A flags it; Agent B returns `review` unless freshness can be verified.
- Invalid or expired live page: Agent B returns `skip`.
- Stored and live title/company differ: Agent B records a discrepancy.
- Match score below threshold: Agent B returns `skip` even if Agent A surfaced it.
- Missing private answer, consent, or resume: Agent C stops with `needs_information` or an error.
- New material form question after confirmation: Agent C requests a new confirmation.
- Browser capability unavailable: Agent C produces a direct link and a field-by-field manual handoff.
- JobSpy HTTP 400/403: open that board's circuit breaker and do not retry it during the run.
- JobSpy returns empty/error coverage: keep successful records and automatically use WebClaw for the missing boards.
- WebClaw cannot resolve an employer application page or confirm an active role: record the error and exclude the posting before scoring.
- Agent Web Browser is stopped or not authenticated: retain the WebClaw path and record AWB as unavailable.
- Any AWB arbitrary-navigation, JavaScript, extension-mutation, or write flag is enabled: refuse the AWB integration.
- Resume-Matcher unavailable: keep the deterministic Agent B result and record that external ATS evidence was not produced.
- Resume-Matcher ATS preview below 60: route an otherwise eligible job to `review`, not an automatic rejection.
- Approval packet hash, URL, job ID, action, reviewer, timestamp, or expiry fails validation: browser-use does not import or run.
- `fill_only` approval: browser-use has no click, keyboard-submit, dropdown-selection, or JavaScript action; choice controls return to the human.
- No employer success receipt: never mark the role applied.

## Repository components

| Path | Responsibility |
|---|---|
| `paperclip/agents/agent-a/` | Recruiter role, heartbeat, posture, and tool contract |
| `paperclip/agents/agent-b/` | Independent verifier contract |
| `paperclip/agents/agent-c/` | Approval-gated application contract |
| `paperclip/PIPELINE_GRAPH.md` | Handoff graph and authority table |
| `scripts/start-paperclip.ps1` | Starts one hidden, isolated localhost server if it is not healthy |
| `scripts/paperclip-server.ps1` | Foreground server entry point with project-local runtime paths |
| `scripts/setup-paperclip.ps1` | Idempotent REST provisioning and safe adapter updates |
| `scripts/test-paperclip.ps1` | Verifies all roles are present, paused, sandboxed, and assigned; `-ProbeCodex` adds a minimal authenticated adapter probe |
| `scripts/install-agent-integrations.ps1` | Creates independent pinned JobSpy and browser-use runtimes to avoid dependency conflicts |
| `scripts/install-agent-web-browser.ps1` | Clones the reviewed AWB commit, applies the narrow first-party job-board patch, and optionally tests/builds it |
| `scripts/agent-run.ps1` / `.cmd` | Selects the JobSpy or browser-use runtime from the specialist command; the CMD wrapper handles locked-down PowerShell policy |
| `scripts/paperclip.ps1` | Pass-through CLI wrapper for the isolated Paperclip instance |
| `scripts/_paperclip-common.ps1` | Shared paths, environment, health check, and CLI invocation |

## Reset and sharing notes

The source code, role bundles, setup scripts, and lockfile are safe to commit. Do not commit `.env`, `data/`, `reports/`, `logs/`, `.paperclip-runtime/`, or `node_modules/`. A colleague can clone the repository, install dependencies, and provision a fresh local Paperclip instance without receiving candidate contact data or your local run history.
