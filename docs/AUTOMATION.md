# Automation and Web Workflows

## Scheduling model

Automations can use either:

- an interval in seconds; or
- a daily wall-clock time with an IANA timezone.

Each schedule stores its workflow, next due time, enabled state, lease state, and run history. A missed interval is coalesced into one due run. The scheduler does not replay an unlimited backlog.

The service serializes scheduler database transactions so simultaneous loopback requests cannot share an SQLite connection unsafely.

On Windows, the hidden wake invokes Python with bytecode writes disabled. The scheduler CLI prepends the packaged timezone runtime before loading services, so named daily recurrences work even when the host Python installation has no IANA timezone package.

## Default scheduled job hunt

The Automations page can create a recurring recruiting workflow with a bounded pipeline request. The default asks for up to 250 recruiting results and stores its pipeline artifacts locally. It does not apply to jobs.

The scheduled tool policy permits:

- public reads;
- local writes;
- local external drafts.

It rejects external-action tools even if an approval digest is supplied. A human must initiate and approve employer-facing action in an interactive session.

## Windows background wake

The installer script creates a per-user scheduled task that:

- runs hidden;
- uses limited privilege;
- wakes every fifteen minutes;
- ignores a new wake if the prior wake is still active;
- starts only the scheduler command;
- stores no bearer token or provider credential in the task definition.

The wake process starts an authenticated local runtime, claims due work, records results, and exits.

## Workflow format

A workflow is a bounded list of nodes. Each node specifies:

- a unique identifier;
- a registered tool name;
- a JSON object of arguments;
- optional dependency identifiers;
- a retry count within the engine maximum.

An argument may reference the exact result of a completed dependency. The engine does not evaluate templates as code.

## Dry run

Dry run validates the complete graph, detects cycles and missing dependencies, resolves tool policies, and returns the planned execution order. It does not invoke a tool or mutate state.

Use dry run before saving a new workflow or changing an existing workflow's tool arguments.

## Runtime controls

- **Retry:** bounded per node and only for ordinary failures.
- **Resume:** completed node results can be supplied to a later execution.
- **Cancel:** a shared cancellation event stops unclaimed work.
- **Circuit control:** repeated failures stop the remaining graph.
- **Challenge handoff:** login walls and bot checks become structured stop states, not retry storms.
- **Output cap:** each tool and the assembled dataset have bounded serialized sizes.

## Data handling

Workflow state stores normalized arguments, result objects, status, timing, and error class. Credentials and browser session data stay in their integration-owned stores. Do not place secrets directly in workflow JSON.
