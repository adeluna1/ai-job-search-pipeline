# Desktop integration reference

## Decision

The maintained production implementation is still the local Python Agent A/B/C
graph. Expedient Employment v1.4.0 contributes only its Electron presentation
and packaging patterns. No upstream Python search, scoring, or application path
was promoted.

## Operator flow

1. Open Search and choose the corrected DOCX resume.
2. Keep or edit the reviewed title query and exact Northern California locations.
3. Select 24 hours, 3 days, or 7 days. Results are always capped at ten.
4. Run Agent A. Live log output is shown in the desktop window.
5. Review Jobs or open the generated interactive report.
6. Use Agents and Services only when the optional local services are installed.
7. Continue to Agent C only through the existing approval receipt and packet hash
   workflow in the Python CLI.

## Desktop pages

- Dashboard: pipeline doctor and optional-service health.
- Search: bounded Agent A discovery with resume-aware inputs.
- Jobs: latest CSV shortlist and safe external job links.
- Browser: persistent, allowlisted job-board login sessions.
- Agents: Paperclip team status and explicit start action.
- Paperclip and Resume-Matcher: embedded local service views.
- Settings: allowlisted JSON configuration editors.

## Process and data boundaries

Electron invokes PowerShell with a fixed script and validated argument array.
It cannot execute arbitrary renderer-provided commands. In development, the
repository root is used. In a packaged app, source and template configuration are
copied to Electron''s per-user data directory. Existing configuration is not
overwritten. Runtime data and reports remain outside the installed executable.

The desktop package requires a compatible system Python. Optional integrations
retain their existing independent installation and authorization requirements.
No resume, browser profile, API key, .env file, or application packet is placed
inside release artifacts.

## Embedded browser policy

The persistent partition is named persist:ai-job-search-browser. Navigation and
new windows are restricted to approved Glassdoor, ZipRecruiter, LinkedIn, Indeed,
and identity-provider domains. Unknown hosts, non-HTTPS external links, preload
injection, Node integration, and browser permission requests are rejected.

This browser can support manual login and job review. It does not bypass access
controls, CAPTCHAs, or a site''s terms, and it does not authorize application
submission.

## Validation

Run from gui:

    npm.cmd test
    npm.cmd run lint
    npm.cmd run build
    node --check electron/main.cjs
    node --check electron/preload.cjs

Run the Python suite from the repository root after any integration change.

- Applications: refreshes and displays the durable application dashboard with totals, text search, status filters, direct links, and an interactive-report button.

### Outcome dropdown

Each Applications row includes a bounded Outcome dropdown. The renderer asks for confirmation before changing a status. The Electron handler accepts only a 16-character application identity and `interview`, `denied`, or `not_selected`; it invokes the fixed `application-flag` CLI command rather than accepting arbitrary shell input. A successful change exposes Undo, which invokes `application-undo` and restores the previous SQLite and registry status atomically. The updated registry and reports stay local.
