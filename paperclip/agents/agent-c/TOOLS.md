# Agent C Tools

- `./run.cmd agent-profile-init` - create the private application-answer template.
- `./run.cmd agent-c JOB_ID --resume "$env:JOB_PIPELINE_RESUME" --application-profile "$env:JOB_PIPELINE_APPLICATION_PROFILE"` - prepare a review-required packet.
- `data/application_profile.json` - private candidate answers; ignored by Git.
- `data/application_packets/` - private per-job packets; ignored by Git.
- `./scripts/agent-run.cmd agent-c-browser JOB_ID` - create a no-network plan and pending hash-bound receipt.
- `data/application_approvals/JOB_ID.json` - private approval receipt; pending by default and never reusable after the packet changes.
- `./scripts/agent-run.cmd agent-c-browser JOB_ID --execute` - fill-only browser-use run after exact approval.
- `./scripts/agent-run.cmd agent-c-browser JOB_ID --execute --submit` - final submission only with exact `fill_and_submit` approval.
- `data/application_results/JOB_ID.json` - browser result requiring independent employer-success verification.
- `./run.cmd status JOB_ID applied --notes "Employer confirmation received"` - record a verified success only.

The packet-preparation command never submits. The browser command does not import browser-use until the exact approval receipt validates, and its navigation is restricted to the job URL's HTTPS host.
