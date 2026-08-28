# Security and Privacy

## Security goals

Expedient Employment is designed to keep user data local, constrain automation, make external effects visible, and fail closed at process and network boundaries.

The protected data includes resumes, profile answers, provider credentials, assistant transcripts, attachments, browser sessions, job notes, and application packets.

## Desktop boundary

- The renderer has no Node.js integration.
- Context isolation and Chromium sandboxing are enabled.
- A Content Security Policy blocks arbitrary script, object, form, and network sources.
- Webview attachment strips preload access and forces isolation, sandboxing, and web security.
- Webviews can load only approved HTTPS session domains or fixed loopback service ports.
- Permission requests are denied by default.
- Popup creation is denied. Approved session URLs may be opened through the operating system browser.
- Renderer IPC methods map to fixed handlers with bounded identifiers and payloads.

### FreeChain credential boundary

The installed FreeChain provider uses `http://127.0.0.1:4853/v1` with bearer authentication. Credential material is never returned to the renderer, logs, transcripts, command arguments, or documentation.

The desktop first uses a valid encrypted record. When no saved record is available, it imports in order from the process `FREECHAIN_ACCESS_KEY`, an explicitly configured environment file, and the allowlisted per-user FreeChain environment file. Electron `safeStorage` protects the saved value at the current Windows user boundary, and Electron user data stores ciphertext only. Plaintext is limited to Electron main-process memory and the owned Python control child environment.

Re-import writes a replacement record only after protected persistence succeeds. A missing replacement or protected-write failure leaves the prior encrypted credential visible and clearable. Clear reports success only after deletion succeeds or the record is already absent. Successful credential changes restart only the owned control service. On a shared Windows account, clear the saved key before another person uses the account.

Installed release acceptance verifies that the encrypted record can authenticate a fresh app process while the original import file is temporarily unavailable. The check also confirms that the plaintext credential is absent from the encrypted record and assistant database before restoring the import file.

## Local service boundary

- The service binds only to loopback on a random port.
- A random bearer token is required for every versioned route.
- The token exists only in the Electron main process and Python child environment.
- Request and response bodies are capped.
- Unknown routes, methods, identifiers, and JSON shapes fail closed.
- The app kills only child processes it owns.

## Tool and subprocess boundary

- Tools use JSON Schema validation before execution.
- The broker enforces policy before calling the handler.
- Commands use argument arrays, not shell interpolation.
- Executables and command catalogs are fixed or resolved through validated paths.
- Timeouts, cancellation, result caps, and error redaction apply at the broker boundary.
- Job-pipeline subprocesses remove the control provider environment and credential before launch.
- Provider response content and tool arguments have the active credential removed before execution or transcript persistence.
- External-action approval is bound to the exact normalized call digest.
- Scheduled execution cannot invoke external-action tools.

## Network boundary

The safe public-page client rejects private, loopback, link-local, multicast, reserved, and otherwise non-global targets. It checks every DNS answer, revalidates redirects, and verifies the connected peer against the approved resolution. Response size and MIME type are bounded.

Fixed loopback adapters validate their exact host, port, scheme, and URL shape. Remote assistant providers require HTTPS.

only-cli is used through a fixed typed adapter. Its optional fingerprint-impersonation dependency is omitted. Untrusted arbitrary URLs should use the safe public-page client when DNS pinning is required.

## Resume and attachment handling

- DOCX extraction is local.
- Archive and XML parse failures are contained.
- DTD and entity declarations are rejected before XML parsing.
- Contact details are redacted before optional model context.
- Image attachments are content-addressed and bounded by type, count, and size.
- Images remain local unless the user opts in to provider upload for that message.

## Automation and anti-bot behavior

The application detects challenges, throttles retries, honors cooldowns and site policy, applies circuit controls, and requests visible user handoff.

It does not bypass CAPTCHA, spoof fingerprints, replay credentials, conceal automation, manipulate browser detection APIs, or evade anti-bot controls. Login and challenge completion are user-controlled activities.

## Privacy release gates

Release verification scans three separate surfaces:

1. the tracked source snapshot;
2. the assembled installer payload;
3. the intended outgoing commit range.

Scans report aggregate categories without printing matched values. Local override files, reports, databases, provider credentials, user attachments, and caches are excluded from packaging.

Repository-history sanitation is a separate operation from source and package sanitation because it changes commit identities. Do not publish all historical refs without running the history gate for the exact remote update.

## Dependency and source license boundary

Original application source is MIT. Integrated source revisions are recorded in `docs/PROVENANCE.md`. Third-party dependencies retain their own licenses and are listed in `THIRD_PARTY_NOTICES.md`.

Packaged Python runs with bytecode writes disabled so installed resource directories do not accumulate host-path cache files.

Restricted-license product source is not copied into the application. Comparable capabilities are original implementations based only on public product requirements.

### Dependency audit snapshot for 2026-08-26

- The locked GUI tree and locked only-cli tree each report zero known vulnerabilities.
- The default core Python project resolves one platform dependency and reports zero known vulnerabilities.
- The locked root development tree pins `@openai/codex` 0.150.1 and `paperclipai` 2026.824.1. It reports six known vulnerabilities: five moderate and one high. The high finding is in `undici` 5.29.0 through Paperclip's Cursor adapter dependency chain. The current `@cursor/sdk` 1.0.29 requires `@connectrpc/connect-node` 1.x, which requires `undici` 5.x, while the audited fix requires `undici` 6.28.0 or newer. `npm audit fix` found no compatible update and offered only a forced breaking Paperclip downgrade, which was not applied. These root development tools are not bundled in the Windows payload, but the finding remains visible for upstream remediation.
- Updating optional `browser-use[core]` from 0.13.6 to 0.13.8 reduces its resolved metadata audit from 53 known vulnerabilities to six across `click` 8.3.1, `mcp` 1.26.0, and `pypdf` 6.14.2. The residual advisory payload text is intentionally not reproduced here. This optional group is installed only into a separate user-requested runtime and is not bundled in the Windows payload.
- `python-jobspy` 1.1.82 remains the current selected release. Its isolated metadata audit reports one advisory in transitive `markdownify` 0.13.1. The audited fix is 0.14.1, but JobSpy requires `markdownify>=0.13.1,<0.14.0`. JobSpy is also optional, isolated, and not bundled in the Windows payload.

The Windows installer is currently unsigned. File checksums provide integrity evidence, not publisher identity or code-signing assurance.

## Reporting a vulnerability

Use the repository's private security reporting channel when available. Do not attach real resumes, credentials, session exports, or application packets to a public issue.
