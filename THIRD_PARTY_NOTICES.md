# Third-party notice

This project integrates with, but does not vendor or modify, WebClaw:

- Project: https://github.com/0xMassi/webclaw
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Reference commit used during implementation: `81e4ac2e93d9b160d9e36e28d65b7f92fad3a331`
- Release setup targets: the current GitHub `latest` release at install time

WebClaw remains a separate executable. Review its license and the terms of any websites or API providers you use.

The optional local multi-agent control plane uses these pinned development dependencies:

- Paperclip AI `2026.707.0`: https://github.com/paperclipai/paperclip (MIT License)
- OpenAI Codex CLI `0.144.6`: https://github.com/openai/codex (Apache License 2.0)

They are installed through pnpm into `node_modules/`; this repository does not commit their package contents.

The specialist adapters integrate with these separately installed or separately run projects:

- JobSpy `1.1.82`: https://github.com/speedyapply/JobSpy (MIT License). Reference commit `fda080a373e8226f3fd60635323f5da9af9892b1`. Installed only under ignored `tools/jobspy-runtime/`.
- Resume-Matcher `1.2.0`: https://github.com/srbhr/Resume-Matcher (Apache License 2.0). Reference commit `dd9b5c3b7a341a62c3a86f7a84e8e30786e6153d`. The pipeline calls a user-controlled HTTP service and does not vendor its backend or frontend.
- browser-use `0.13.6`: https://github.com/browser-use/browser-use (MIT License). Reference commit `2be09b6c5eb702a9287684b42b27e7042a1aba29`. Installed only under ignored `tools/browser-use-runtime/`.

JobSpy and browser-use use different isolated runtimes because their current `markdownify` constraints are incompatible. The repository does not copy code from LinkedIn auto-apply repositories. Such projects were reviewed only for common field categories; this project implements its own truthful field catalog, does not include anti-detection behavior, and routes unknown questions to a human.
