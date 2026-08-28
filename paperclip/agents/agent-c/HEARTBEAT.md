# Agent C Heartbeat

1. Read the assigned issue and confirm Agent B recorded `recommendation=apply` for each job ID.
2. Check out the issue.
3. Confirm these private files exist:

   - `$env:JOB_PIPELINE_RESUME`
   - `$env:JOB_PIPELINE_APPLICATION_PROFILE`

4. Prepare one packet per approved job:

   `./run.cmd agent-c JOB_ID --resume "$env:JOB_PIPELINE_RESUME" --application-profile "$env:JOB_PIPELINE_APPLICATION_PROFILE"`

5. Read `data/application_packets/JOB_ID.json`. If any unresolved question exists, ask the candidate and stop.
6. Create the dry-run plan and pending receipt:

   `./scripts/agent-run.cmd agent-c-browser JOB_ID`

7. Create a Paperclip `request_confirmation` interaction. State the company, title, URL, packet path and SHA-256, unresolved questions, and whether requested authority is `fill_only` or `fill_and_submit`.
8. Exit cleanly while the interaction is pending. Do not treat silence as approval.
9. On a later heartbeat after acceptance, update the ignored receipt with `decision=approved`, the exact allowed action, reviewer, approval timestamp, and optional expiry. Do not change its packet hash, job ID, or URL.
10. Re-check the live URL. Run `agent-c-browser JOB_ID --execute` for fill-only or add `--submit` only when the receipt authorizes `fill_and_submit`. Stop if the form introduces a new material question.
11. Record the external result. Mark `applied` only after the employer page displays a success receipt; otherwise keep `saved` and explain the handoff.
