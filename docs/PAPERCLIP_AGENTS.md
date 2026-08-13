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
2. Agent A runs `scripts/agent-run.cmd agent-a-find` with literal locations and a 24-hour, 3-day, or 7-day window. It excludes applied/sent roles, resolves employer URLs, verifies active pages, requires exact geography and a known in-window date, resume-ranks only the current run, and writes no more than 10 roles plus the complete audit.
3. Resume Agent B after that shortlist exists and run it with `--live`. Agent B independently rechecks geography, lifecycle suppression, the exact hour window, the active page, and direct ATS/employer-domain evidence. Only an unambiguously fresh `apply` decision creates a SHA-256-bound record under `agent_c_handoffs`; posting intelligence never changes the resume-fit score.
4. Resume Agent C only when that current handoff exists. Agent C validates the handoff, consumes the persisted Agent B analysis without recomputing it, and writes an ignored evidence-bound packet under `data/application_packets/`. An incomplete profile produces `needs_information` and leaves the lifecycle `saved`; only a complete packet becomes `ready_to_apply`.
5. If the packet is complete, Agent C runs `agent-c-browser` without `--execute` to create a dry-run plan and a pending receipt under `data/application_approvals/`. The browser boundary independently blocks `fill_and_submit` while any unresolved question exists.
6. Agent C requests a per-role confirmation naming the company, title, URL, packet SHA-256, unresolved questions, and whether authority is `fill_only` or `fill_and_submit`.
7. Pending, rejected, expired, mismatched, or ambiguous confirmation means stop. After acceptance, Agent C records the reviewer and timestamp in the ignored receipt; authority applies only to that packet hash and action.
8. The approved execution uses browser-use with an exact-domain allowlist and moves the job to `applying`. That transition immediately updates alias-aware discovery suppression. Mark it `applied` only after a human verifies the employer success receipt; otherwise retain the result and blocker without claiming submission.

For a safe offline contract test that never opens a site or submits anything:

```powershell
.\run.ps1 agent-demo --resume "C:\Users\acdde\Downloads\Albert Deluna ResumeV1.docx"
```

Expected final state: Agent A identifies the aligned fixture, Agent B recommends it, and Agent C returns `awaiting_review` with `approval=pending`.

## Command and artifact contracts

| Command | Reads | Writes | Network/external effect |
|---|---|---|---|
| `agent-a-find` | exact locations/window, corrected resume, exclusions | current-run top 10 or fewer, report, discovery audit, findings | Board discovery; WebClaw/AWB fallback; active-page verification |
| `agent-a` | at most 10 current-run IDs, locations, matches | `data/agent_a_findings.json` | None |
| `agent-b --live --job-id JOB_ID` | at most 10 jobs, exact scope, Agent A finding | reviews plus integrity-bound Agent C handoffs | Live employer read; Resume-Matcher additionally requires explicit upload consent |
| `agent-c JOB_ID` | exact unexpired Agent B handoff, private profile, corrected resume path | evidence-bound packet; `ready_to_apply` only when complete, otherwise `needs_information` and `saved` | Never submits |
| `agent-c-browser JOB_ID` | complete private packet | pending receipt and dry-run plan | None unless `--execute`; `--submit` independently rejects unresolved questions and requires exact `fill_and_submit` approval |
| `agent-demo` | fixture jobs, corrected resume | demo database, private fixture packet, `reports/agent_demo.json` | None |

## Failure and safety behavior

- Missing date or date-only evidence crossing the requested hour boundary: exclude it before an Agent B-to-C handoff.
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
| `scripts/agent-run.ps1` / `.cmd` | Repairs quoted `OR` queries split by legacy Windows forwarding, selects the JobSpy or browser-use runtime, and handles locked-down PowerShell policy |
| `scripts/paperclip.ps1` | Pass-through CLI wrapper for the isolated Paperclip instance |
| `scripts/_paperclip-common.ps1` | Shared paths, environment, health check, and CLI invocation |

## Reset and sharing notes

The source code, role bundles, setup scripts, and lockfile are safe to commit. Do not commit `.env`, `data/`, `reports/`, `logs/`, `.paperclip-runtime/`, or `node_modules/`. A colleague can clone the repository, install dependencies, and provision a fresh local Paperclip instance without receiving candidate contact data or your local run history.
