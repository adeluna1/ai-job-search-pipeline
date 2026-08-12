# Agent A Heartbeat

1. Run `./scripts/get-paperclip-task.cmd` to read the assigned issue's ID, title, description, and status. Do not search `.paperclip-runtime`, enumerate `Env:PAPERCLIP*`, or print any environment variable whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, or `AUTH`.
2. Check out the assigned issue before mutating it.
3. Confirm `$env:JOB_PIPELINE_RESUME` exists. If it does not, block the issue and name the missing path.
4. Translate the issue's geography literally. Pass each named city/metro as a separate `--location`; never substitute a broader state or country. Use `--hours-old 24 --fresh-days 1` for a 24-hour request or `--hours-old 168 --fresh-days 7` for a 7-day request. Run one bounded search operation with isolated board requests. If the assigned issue supplies an exact `agent-a-find` command, run that command verbatim and give its shell process at least 180 seconds before treating it as timed out. Otherwise use the default:

   `./scripts/agent-run.cmd agent-a-find --location "San Francisco Bay Area" --location "San Jose, California" --hours-old 168 --fresh-days 7 --results-wanted 10 --max-results 10 --resume "$env:JOB_PIPELINE_RESUME"`

5. Read only the required summary fields from `data/agent_a_discovery.json`: each board's attempt count/status, open circuit breakers, WebClaw fallback status, Agent Web Browser availability/use, employer-URL resolutions, verification-error count, `verified_active_count`, `previously_applied_count`, `geography_gate`, and `shortlist_gate`. Confirm the shortlist has no more than 10 current-run IDs and every retained role passed the exact geography gate. Do not dump full JSON or job descriptions. Do not run a second board search.

6. If discovery was separate from triage, pass only the current run's `shortlist_gate.selected_job_ids` (maximum 10), plus the exact locations:

   `./run.cmd agent-a --job-id JOB_ID --location "San Francisco Bay Area" --location "San Jose, California" --fresh-days 7 --min-score 72`

7. Read only compact fields from `data/agent_a_findings.json`: `job_id`, `title`, `company`, `url`, `score`, `eligible_for_agent_b`, and the short finding reasons. Keep only records with `eligible_for_agent_b=true`. Unknown posting dates are ineligible; never pad the list with stale, out-of-area, unverified, previously applied, previously sent, or closed roles.
8. Comment on the Paperclip issue with a compact table: job ID, title, company, score, posting age, source quality, source board, and URL. Include the provider coverage summary.
9. Update or create the Agent B issue with the exact qualified IDs, exact requested locations, and exact freshness window. The handoff may contain fewer than 10 IDs but never more. Do not assign application work directly to Agent C.
10. Mark the issue done when the handoff exists; otherwise mark blocked with a concrete unblock action.
