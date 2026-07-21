# Paperclip Agent Graph

Paperclip owns organization, assignments, durable issue state, budgets, run transcripts, routing, and human confirmation. The Python project owns provider adapters, normalization, scoring, evidence, and private application packets.

```mermaid
flowchart LR
    U["Board user sets search objective"] --> J["JobSpy multi-board discovery"]
    J --> A["Agent A: Recruiter"]
    J -->|"degraded / unavailable"| W["WebClaw fallback"]
    W --> A
    A -->|"qualified job IDs + evidence"| B["Agent B: Verifier"]
    B -->|"optional authorized ATS evidence"| M["Resume-Matcher preview"]
    M --> B
    B -->|"apply"| C["Agent C: Application Assistant"]
    B -->|"review"| U
    B -->|"skip"| X["Archive"]
    C --> P["Private application packet"]
    P --> G{"Paperclip confirmation accepted?"}
    G -->|"No / pending"| S["Stop safely"]
    G -->|"Yes, exact packet + action"| BU["browser-use exact-domain session"]
    BU --> F["Fill reviewed fields"]
    F --> R{"Employer success receipt?"}
    R -->|"Yes"| D["Mark applied"]
    R -->|"No"| H["Save handoff + blocker"]
```

## Agent contracts

| Agent | Input | Local command | Output | External authority |
|---|---|---|---|---|
| A | Search objective and corrected resume | `agent-a-find`, then `agent-a` | Fresh, scored shortlist plus provider diagnostics | Public discovery only |
| B | Agent A job IDs | `agent-b --live`; optional Resume-Matcher | `apply`, `review`, or `skip` with deterministic and optional ATS evidence | Public verification; resume upload only after explicit service consent |
| C | Agent B `apply` IDs and reviewed candidate profile | `agent-c`, then `agent-c-browser` | Private packet, hash-bound receipt, plan, and verified outcome | Only after accepted confirmation for exact packet/action |

The agents are provisioned paused. This prevents assignments from starting model runs or external actions until the board user reviews the configuration and explicitly resumes the relevant agent.
