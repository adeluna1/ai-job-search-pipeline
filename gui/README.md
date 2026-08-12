# AI Job Search Pipeline Desktop

This React, TypeScript, and Electron interface is selectively adapted from
BarnsL/expedient-employment v1.4.0. It controls the maintained Agent A/B/C
pipeline in the parent directory; it does not replace the Python search,
verification, lifecycle, scoring, or approval logic.

## Development

From this directory:

    npm.cmd install
    npm.cmd test
    npm.cmd run lint
    npm.cmd run build
    npm.cmd run electron

Use npm.cmd run dev for the Vite renderer alone. For an Electron development
window backed by Vite, start Vite on port 7100 and run npm.cmd run electron:dev.

## Search behavior

The Search page invokes agent-a-find with:

- the reviewed junior recruiting and recruiting-coordination title family;
- San Francisco Bay Area, San Francisco, San Jose, Oakland, and Sacramento;
- exact 24-hour, 3-day, or 7-day freshness;
- a hard top-10 output cap;
- the selected corrected DOCX resume.

The Python pipeline remains responsible for applied-role exclusions, duplicate
removal, live employer-page verification, posting intelligence, Agent B scoring,
and the approval-bound Agent B to Agent C handoff.

## Security boundaries

- Renderer Node integration is disabled; context isolation and sandboxing are on.
- IPC exposes a narrow allowlist rather than arbitrary command execution.
- Search input, resume type, result count, freshness, and concurrency are bounded.
- Embedded sessions allow reviewed job-board and identity-provider hosts only.
- Browser permissions are denied by default.
- External links must use HTTPS.
- Application submission is not exposed as an automatic desktop action.

See ../docs/DESKTOP_APP.md for the operating and packaging reference.

## Applications dashboard

The Applications navigation item reads `reports/applications_dashboard.json`. Its Refresh button runs the offline `applications-report` CLI command, and Interactive report opens the self-contained HTML view. Applied-role data remains under the ignored `data/` and `reports/` directories.

### Flagging outcomes

Use the Outcome dropdown on an application row to select Interview, Denied, or Didn't get job. Confirm the change in the prompt; after it saves, the success banner offers Undo. Status changes and reversals update SQLite plus the durable registry as one rollback-safe operation. Distinct outcome flags are retained even when two choices share the rejected lifecycle state.
