# Pipeline review remediation

## Decision

Keep the optimized Agent A/B/C graph and the selective Career-Ops posting
intelligence layer. Strengthen lifecycle tracking, recency, the Agent B-to-C
handoff, direct-domain verification, and truthful tailoring. Archive dated
manual production alternatives.

## What changed

| Review area | Previous behavior | Maintained behavior |
|---|---|---|
| Lifecycle | One mutable status row | Current state plus append-only `application_events`, validated transitions, actors, notes, and metadata |
| Search suppression | Applied-role list only | Every suppression-eligible lifecycle transition is synchronized into the alias-aware JSON registry before commit, so `applying` roles cannot be rediscovered through another board URL |
| Recency | `hours_old` rounded up to calendar days | Exact hour window; timestamp evidence is exact and boundary-crossing date-only evidence remains unknown |
| Agent B to C | Agent C recalculated Agent B locally | Agent B writes a SHA-256-bound apply handoff; Agent C requires the same job, URL, gates, review time, and an unexpired handoff |
| Live verification | Valid non-board pages could be treated as direct | Exact ATS suffix or application path plus employer-host identity is required; lookalike and aggregator hosts fail |
| Tailoring | Three general text notes | Structured evidence bullets, supported keywords, truthful gap checks, quarantined unsupported keywords, and mandatory human review |
| Agent C readiness | Incomplete packets could be marked ready | `needs_information` remains `saved`; only complete packets become `ready_to_apply`, and the browser runner independently blocks incomplete submission |
| Legacy paths | Dated hard-coded report scripts remained beside production tools | Historical builders and raw helpers moved to `scripts/archive/manual_reports/` |

## Supported production path

```text
agent-a-find
  -> current-run employer verification
  -> exact geography + strict recency + top-10 gates
agent-b --live
  -> direct-domain verification
  -> resume fit + separate posting intelligence
  -> integrity-bound apply handoff
agent-c
  -> validates unexpired Agent B handoff
  -> prepares private, evidence-bound packet
  -> saved/needs_information when incomplete; ready_to_apply only when complete
agent-c-browser
  -> independently rejects unresolved fill_and_submit packets
  -> exact packet/action approval
  -> applying lifecycle state + immediate alias suppression
human verifies employer receipt
  -> status applied
```

## Lifecycle states

The normal graph is:

```text
new -> saved -> ready_to_apply -> applying -> applied
applied -> interviewing -> offer -> accepted
applied/interviewing -> rejected or withdrawn
offer -> declined or withdrawn
new/saved/ready_to_apply/applying -> closed or withdrawn
```

Use `status JOB_ID STATE --force` only to correct reviewed historical data. It
does not grant browser or submission authority.

## Recency policy

- Timestamp evidence is compared directly with the requested number of hours.
- Date-only evidence represents a 24-hour interval.
- If that interval crosses the freshness boundary, the result is `unknown`, not
  fresh. Unknown records do not enter an Agent C handoff.
- The evidence source and precision are persisted in Agent A and Agent B output.

## Agent B-to-C contract

Agent B creates `agent_c_handoffs` only when all hard gates pass:

- recommendation is `apply`;
- Agent B performed live verification;
- the URL passed direct ATS/employer-domain verification;
- freshness is unambiguously true;
- geography is eligible.

Agent C verifies the handoff digest, exact URL, review timestamp, gates, and age.
The default maximum handoff age is 24 hours. There is no review-bypass flag.

## Tailoring boundary

Tailoring remains decision support. It never edits the corrected source resume
automatically. Resume-Matcher suggestions are divided into keywords supported by
existing resume evidence and keywords that must not be added without evidence.
Every packet requires human review.

## Validation

Run:

```powershell
python -m compileall -q job_pipeline
python -m unittest tests.test_pipeline
```

The remediation adds regression tests for strict recency, direct-domain
lookalikes, lifecycle audit events, handoff integrity, supported versus
unsupported tailoring keywords, applying-state alias suppression, incomplete
packet lifecycle handling, and independent browser submission blocking. The
maintained suite contains 50 passing tests.
