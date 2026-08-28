# Agent B Heartbeat

1. Read the assigned issue, Agent A's evidence, provider diagnostics, and every supplied job ID.
2. Check out the issue.
3. Run live verification when network access is authorized:

   `./run.cmd agent-b --fresh-days 7 --min-score 72 --live`

   For a specific job, add `--job-id JOB_ID`.

4. If live verification is unavailable, rerun without `--live` and explicitly preserve that limitation.
5. Only when the issue explicitly allows sending the resume to a reviewed service URL, add:

   `--resume-matcher --resume-matcher-url URL --resume "$env:JOB_PIPELINE_RESUME" --allow-resume-upload`

6. Read `data/agent_b_reviews.json` and verify every recommendation is supported by evidence. Label Resume-Matcher output as a tailoring-preview ATS assessment.
7. Comment with deterministic score, optional ATS score, recommendation, live-verification status, matched evidence, gaps, blockers, and discrepancies.
8. Update Agent C's issue with only `apply` job IDs and their URLs. Route `review` items to the board user and close out `skip` items.
9. Mark done after the handoff is complete or blocked with a named unblock owner.
