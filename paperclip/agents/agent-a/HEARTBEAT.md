# Agent A Heartbeat

1. Read `PAPERCLIP_TASK_ID`, the task description, its goal, and all recent comments.
2. Check out the assigned issue before mutating it.
3. Confirm `$env:JOB_PIPELINE_RESUME` exists. If it does not, block the issue and name the missing path.
4. Run one bounded search operation with isolated board requests:

   `./scripts/agent-run.cmd agent-a-find --query "Recruiting Coordinator" --location "United States" --hours-old 168 --results-wanted 10 --resume "$env:JOB_PIPELINE_RESUME"`

5. Read `data/agent_a_discovery.json`. Record each board's attempt count/status, open circuit breakers, WebClaw fallback status, Agent Web Browser availability/use, employer-URL resolutions, verification errors, and `verified_active_count`. Do not run a second board search: `agent-a-find` already performs the authorized fallback and active-page gate.

6. If discovery was separate from triage, run:

   `./run.cmd agent-a --fresh-days 7 --min-score 72`

7. Read `data/agent_a_findings.json`. Keep only records with `eligible_for_agent_b=true`.
8. Comment on the Paperclip issue with a compact table: job ID, title, company, score, posting age, source quality, source board, and URL. Include the provider coverage summary.
9. Update or create the Agent B issue with the exact qualified IDs. Do not assign application work directly to Agent C.
10. Mark the issue done when the handoff exists; otherwise mark blocked with a concrete unblock action.
