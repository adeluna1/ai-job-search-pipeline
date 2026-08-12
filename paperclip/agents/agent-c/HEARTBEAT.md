# Agent C Heartbeat

1. Run `./scripts/get-paperclip-task.cmd` to read the assigned issue, then locate the named ID under `agent_c_handoffs` in `data/agent_b_reviews.json`. The `agent-c` command must validate its digest, exact URL, live/direct-domain/freshness/geography gates, review timestamp, age, and lifecycle suppression. Otherwise create no packet, receipt, or browser plan. Do not search `.paperclip-runtime`, enumerate `Env:PAPERCLIP*`, or print secrets.
2. Check out the issue.
3. Confirm these private files exist:

   - `$env:JOB_PIPELINE_RESUME`
   - `$env:JOB_PIPELINE_APPLICATION_PROFILE`

4. Prepare one packet per approved job:

   `./run.cmd agent-c JOB_ID --resume "$env:JOB_PIPELINE_RESUME" --application-profile "$env:JOB_PIPELINE_APPLICATION_PROFILE"`

5. Read `data/application_packets/JOB_ID.json`. If any unresolved question exists, confirm the result is `needs_information` with lifecycle `saved`, ask the candidate, and stop. Do not create or approve a submission plan.
6. Create the dry-run plan and pending receipt:

   `./scripts/agent-run.cmd agent-c-browser JOB_ID`

7. Create a Paperclip `request_confirmation` interaction. State the company, title, URL, packet path and SHA-256, unresolved questions, and whether requested authority is `fill_only` or `fill_and_submit`.
8. Exit cleanly while the interaction is pending. Do not treat silence as approval.
9. On a later heartbeat after acceptance, update the ignored receipt with `decision=approved`, the exact allowed action, reviewer, approval timestamp, and optional expiry. Do not change its packet hash, job ID, or URL.
10. Re-check the applied registry and live URL immediately before execution. Run `agent-c-browser JOB_ID --execute` for fill-only or add `--submit` only when the complete packet and receipt authorize `fill_and_submit`. The runner independently rejects unresolved questions. Stop if the role was already applied, closed, changed materially, moved out of scope, or introduces a new material question.
11. Record the external result. The command leaves the lifecycle at `applying` and synchronizes URL-alias suppression immediately; mark `applied` only after a human verifies the employer success receipt. Otherwise record the blocker without claiming submission.
