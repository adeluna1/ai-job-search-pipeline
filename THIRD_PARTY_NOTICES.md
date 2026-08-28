# Third-party notice

The integrated application lifecycle and discovery improvements include MIT
licensed source from AI Job Search Pipeline at reviewed revision
`3962e0a0ecbaad4c6ab618b0113be1a2611073f4`:

- Project: https://github.com/adeluna1/ai-job-search-pipeline
- License: MIT
- Detailed file ledger: `docs/PROVENANCE.md`

The assistant web tool surface includes a separately installed, Git-pinned
only-cli runtime:

- Project: https://github.com/only-cli/oc
- Reviewed revision: `7f1f109b8e34dcfc2bfb56122a427f3c467a79ca`
- Package version: `0.5.0`
- License: MIT
- Installed location: `gui/only-cli-runtime/node_modules/`

Its optional native fingerprint-impersonation transport is omitted from the
installed and packaged runtime. The Node native transport remains available,
including only-cli's public-page safety checks and challenge detection.

The Windows desktop package also bundles `tzdata 2026.3` from the Python
Software Foundation under Apache License 2.0. This is the standard IANA
timezone fallback used by Python's `zoneinfo` module on systems without a
machine-level timezone database: https://pypi.org/project/tzdata/

This project can integrate with, but does not vendor, package, or modify, WebClaw:

- Project: https://github.com/0xMassi/webclaw
- License: GNU Affero General Public License v3.0 (AGPL-3.0)
- Reference commit used during implementation: `81e4ac2e93d9b160d9e36e28d65b7f92fad3a331`
- Release setup targets: the current GitHub `latest` release at install time

WebClaw remains a separate user-installed executable outside the MIT application distribution. The original MIT web-intelligence and workflow modules do not depend on its source. Review its license and the terms of any websites or API providers you use.

The optional local multi-agent control plane uses these pinned development dependencies:

- Paperclip AI `2026.707.0`: https://github.com/paperclipai/paperclip (MIT License)
- OpenAI Codex CLI `0.144.6`: https://github.com/openai/codex (Apache License 2.0)

They are installed through pnpm into `node_modules/`; this repository does not commit or include their package contents in the desktop installer.

The specialist adapters integrate with these separately installed or separately run projects:

- JobSpy `1.1.82`: https://github.com/speedyapply/JobSpy (MIT License). Reference commit `fda080a373e8226f3fd60635323f5da9af9892b1`. Installed only under ignored `tools/jobspy-runtime/`.
- Resume-Matcher `1.2.0`: https://github.com/srbhr/Resume-Matcher (Apache License 2.0). Reference commit `dd9b5c3b7a341a62c3a86f7a84e8e30786e6153d`. The pipeline calls a user-controlled HTTP service and does not vendor its backend or frontend.
- browser-use `0.13.6`: https://github.com/browser-use/browser-use (MIT License). Reference commit `2be09b6c5eb702a9287684b42b27e7042a1aba29`. Installed only under ignored `tools/browser-use-runtime/`.

JobSpy and browser-use use different isolated runtimes because their current `markdownify` constraints are incompatible. The repository does not copy code from LinkedIn auto-apply repositories. Such projects were reviewed only for common field categories; this project implements its own truthful field catalog, does not attempt to circumvent site access controls, and routes unknown questions to a human.
