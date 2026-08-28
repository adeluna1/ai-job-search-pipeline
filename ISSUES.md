# Expedient Employment — Issue Tracker

Lightweight ticketing for this repository. Statuses: **Open**, **In progress**, **Done**.

## Summary

| ID | Title | Status | Priority | Area |
|---|---|---|---|---|
| EE-1 | Washed-out contrast on outline buttons in the GUI | Done | Medium | gui |
| EE-2 | Paperclip and Resume-Matcher do not auto-start with the GUI | Done | High | gui / services |
| EE-3 | Add Engine Start buttons to the Paperclip and Resume-Matcher pages | Done | Medium | gui |
| EE-4 | Resume-Matcher requires Docker Desktop; no graceful fallback without it | Open | Medium | integrations |
| EE-5 | macOS and Linux packaging targets are defined but untested | Open | Medium | packaging |
| EE-6 | Paperclip data directory (`.paperclip-runtime/`) is not portable across machines or moved checkouts | Open | Low | paperclip |
| EE-7 | GUI Paperclip auto-launch requires Node.js on PATH | Open | Medium | gui / services |
| EE-8 | Pipeline scripts depend on PowerShell; macOS/Linux require `pwsh` and several launchers are Windows-oriented | Open | Medium | scripts / cross-platform |
| EE-9 | Packaged app: pipeline resource resolution in installed layouts needs end-to-end verification | Done | High | packaging |
| EE-10 | Windows installer is not Authenticode-signed | Open | Medium | packaging / trust |

---

## EE-1 — Washed-out contrast on outline buttons in the GUI

- **Status:** Done
- **Priority:** Medium
- **Area:** gui

**Description:** Buttons using the `outline` variant rendered with insufficient contrast against the dark app background, making labels hard to read.

**Resolution:** The outline button styles were corrected in the shared button component so the variant meets readable contrast in both themes. Verified visually in the running app.

## EE-2 — Paperclip and Resume-Matcher do not auto-start with the GUI

- **Status:** Done
- **Priority:** High
- **Area:** gui / services

**Description:** Launching the desktop app showed the Paperclip and Resume-Matcher pages as offline until the user started each service manually from scripts or Docker.

**Resolution:** The Electron main process now attempts a best-effort, non-blocking auto-launch of both backends when the app becomes ready (Paperclip via the local Node runtime, Resume-Matcher via Docker). Window creation never waits on service startup, and pre-existing healthy services are detected and reused.

## EE-3 — Add Engine Start buttons to the Paperclip and Resume-Matcher pages

- **Status:** Done
- **Priority:** Medium
- **Area:** gui

**Description:** The embedded Paperclip and Resume-Matcher pages had no in-app way to start their respective engines; users had to drop to the terminal.

**Resolution:** Both embedded pages now expose an **Engine Start** button that launches the corresponding backend and reports the resulting health state inline.

## EE-4 — Resume-Matcher requires Docker Desktop; no graceful fallback without it

- **Status:** Open
- **Priority:** Medium
- **Area:** integrations

**Description:** The optional ATS-evidence feature depends on the pinned `ghcr.io/srbhr/resume-matcher:1.2.0` container. On machines without Docker Desktop (or where Docker is not running), the GUI's Resume-Matcher page and Engine Start simply fail, and Agent B's `--resume-matcher` path is unavailable.

**Notes / next steps:** Detect the missing-Docker case explicitly and surface a clear "Docker Desktop required" message in the GUI; document a non-Docker alternative (running the upstream backend directly with Python 3.13) or mark the feature unavailable. The deterministic score already remains the fallback, so this is a UX gap rather than a correctness bug.

## EE-5 — macOS and Linux packaging targets are defined but untested

- **Status:** Open
- **Priority:** Medium
- **Area:** packaging

**Description:** `gui/electron-builder.yml` defines `mac` (dmg, zip) and `linux` (AppImage) targets alongside the Windows targets, and `packaging/build-posix.sh` drives them, but no macOS or Linux artifact has been produced or smoke-tested yet.

**Notes / next steps:** Build on real macOS and Linux machines (mac installers must be built on macOS). Verify the bundled `pipeline/` extraResources layout resolves correctly at runtime and that `pwsh` detection works on both platforms. Consider adding CI builds.

## EE-6 — Paperclip data directory (`.paperclip-runtime/`) is not portable

- **Status:** Open
- **Priority:** Low
- **Area:** paperclip

**Description:** The Paperclip instance stores its database and configuration under `.paperclip-runtime/` inside the checkout. Moving the repository to a new path or machine can strand absolute paths recorded in that database, and agent adapter configs embed the checkout path.

**Notes / next steps:** Re-running `scripts/setup-paperclip.ps1` after a move repairs adapter configs (it re-applies paths idempotently), which mitigates most of this. Document the re-provisioning step; longer term, consider making stored paths relative or adding a `doctor`-style repair command.

## EE-7 — GUI Paperclip auto-launch requires Node.js on PATH

- **Status:** Open
- **Priority:** Medium
- **Area:** gui / services

**Description:** The GUI's Paperclip auto-launch spawns the control plane through the system Node.js runtime. If Node 20+ is not installed or not on PATH, auto-launch fails and the Paperclip page stays offline even though the rest of the app works.

**Notes / next steps:** Detect the missing-Node case and show a targeted message on the Paperclip page. Evaluate bundling or locating a known runtime (e.g. honoring `NODE_EXE`) as a fallback. The manual workaround is starting Paperclip from `scripts/start-paperclip.ps1`.

## EE-8 — Pipeline scripts depend on PowerShell; macOS/Linux support is partial

- **Status:** Open
- **Priority:** Medium
- **Area:** scripts / cross-platform

**Description:** `run.ps1`, the doctor command, and all Paperclip/agent launcher scripts are PowerShell. On macOS/Linux they require `pwsh`, and some helpers are Windows-only by design (`run.cmd`, `agent-run.cmd`, virtual-environment paths under `tools/*/Scripts`, Inno Setup packaging).

**Notes / next steps:** The GUI already resolves `pwsh` on non-Windows platforms. Remaining work: audit `scripts/agent-run.ps1` and the integration installers for POSIX virtual-env layouts (`bin/` vs `Scripts/`), and provide shell equivalents for the most common entry points. Track packaging verification under EE-5.

## EE-9: Packaged app resource resolution in installed layouts

- **Status:** Done
- **Priority:** High
- **Area:** packaging

**Description:** The electron-builder configuration bundles the pipeline (`job_pipeline/`, `run.ps1`, `scripts/`, `config/`, `docs/`) into `resources/pipeline/` via `extraResources`. In a packaged install the GUI must resolve the pipeline from that resources layout rather than the development checkout layout, and the pipeline writes data (`data/`, `reports/`, `logs/`) that must land somewhere writable in a per-user install.

**Resolution:** Version 2.0.0 was built through the documented Windows release command, installed per-user, and verified from the installed resources. The authenticated control service reported healthy, registered twelve tools, exposed ten only-cli tools and two job tools, and completed an installed only-cli workflow. The Start Menu shortcut targets the installed executable, and the scheduled wake task completed with result zero.

## EE-10: Windows installer is not Authenticode-signed

- **Status:** Open
- **Priority:** Medium
- **Area:** packaging / trust

**Description:** The 2.0.0 installer is built from verified local inputs but has no Authenticode signature. Windows may show an unknown-publisher warning.

**Next step:** Obtain a trusted Windows code-signing certificate, configure the signing environment outside the repository, sign the application executable and installer, then verify the signature and timestamp in the release gate. Do not commit private signing material.
