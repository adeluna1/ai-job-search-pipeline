# Agent B Heartbeat

1. Run `./scripts/get-paperclip-task.cmd` to read the assigned issue, exact locations, freshness window, and supplied job IDs. Reject a handoff over 10 IDs. Treat Agent A's compact evidence as the candidate set, not as permission to relax any gate. Do not search `.paperclip-runtime`, enumerate `Env:PAPERCLIP*`, or print secrets.
2. Check out the issue.
3. Run live verification when network access is authorized, repeating each exact location from the issue:

   `./run.cmd agent-b --fresh-days 7 --min-score 72 --location "San Francisco Bay Area" --location "San Jose, California" --live`

   For a specific job, add `--job-id JOB_ID`. When the issue names one test job ID, run this command immediately for that ID; do not inspect unrelated jobs, historical reports, runtime logs, or Paperclip server source first.

4. If live verification is unavailable, rerun without `--live` only for diagnostic review. It cannot create an Agent C handoff.
5. Only when the issue explicitly allows sending the resume to a reviewed service URL, add:

   `--resume-matcher --resume-matcher-url URL --resume "$env:JOB_PIPELINE_RESUME" --allow-resume-upload`

6. Read `data/agent_b_reviews.json` and independently confirm: active exact ATS/employer domain, unambiguously in-window hour evidence, geography eligibility, no lifecycle-suppression match, and resume evidence. Only IDs present in `agent_c_handoffs` may move to Agent C. Label Resume-Matcher output as tailoring-preview evidence and never add an unsupported keyword.
7. Comment with deterministic score, optional ATS score, recommendation, live-verification status, matched evidence, gaps, blockers, and discrepancies.
8. Update Agent C's issue with only IDs and URLs present in `agent_c_handoffs`, including the handoff SHA-256 and expiry window. Route `review` items to the board user and close out `skip` items.
9. Mark done after the handoff is complete or blocked with a named unblock owner.
