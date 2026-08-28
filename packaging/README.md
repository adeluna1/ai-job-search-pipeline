# Packaging Expedient Employment

This directory contains the release build scripts. The packaging produces a
desktop app that bundles the entire job-hunting pipeline (Python package,
CLI entrypoints, scripts, config templates, and docs) inside the Electron
application's resources under `pipeline/`, so end users do not need a separate
source checkout.

## Artifacts

All artifacts land in `release/` at the repository root:

| Artifact | Platform | Produced by |
|---|---|---|
| `ExpedientEmployment-Setup-<version>.exe` | Windows | Inno Setup (per-user installer, no admin required) |
| `ExpedientEmployment-portable-<version>.zip` | Windows | electron-builder `zip` target |
| `Expedient Employment-<version>.dmg` / `.zip` | macOS | electron-builder `mac` targets |
| `Expedient Employment-<version>.AppImage` | Linux | electron-builder `linux` target |

The version is read from `gui/package.json` — bump it there before a release.

## Windows release

One-time prerequisite: **Inno Setup 6** from <https://jrsoftware.org/isinfo.php>
(the script checks `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`,
`C:\Program Files\Inno Setup 6\ISCC.exe`, then PATH).

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1
```

After a successful dependency install and GUI build, packaging-only retries can
use `-SkipOnlyCliInstall -SkipPythonRuntimeInstall -SkipGuiBuild`. The script
refuses either runtime skip when its required files are missing, and refuses the
GUI skip when the production entry file is missing.

The script will:

1. Install the pinned only-cli runtime and `tzdata==2026.3`, then run
   `npm run build` in `gui/` (installing GUI dependencies first if needed).
2. Run `npx --yes electron-builder --config electron-builder.yml --win dir zip`
   from `gui/`. Temporary Electron extraction is placed under the operating
   system temporary directory so source-tree watchers cannot lock its rename.
3. Copy the portable zip to `release/ExpedientEmployment-portable-<version>.zip`.
4. Locate ISCC.exe through default paths, PATH, or the Inno Setup uninstall
   registry entries, then compile `installer/windows.iss` into
   `release/ExpedientEmployment-Setup-<version>.exe`.

The installer is per-user: it installs to
`%LOCALAPPDATA%\Programs\Expedient Employment`, adds a Start Menu shortcut,
offers an optional desktop shortcut, and registers an uninstaller. No
administrator rights are required.

If Inno Setup is missing, the script stops with a friendly message — the
portable zip is still produced and usable on its own.

## macOS / Linux release

```bash
./packaging/build-posix.sh          # auto-detects the host platform
./packaging/build-posix.sh mac      # dmg + zip   (must run on macOS)
./packaging/build-posix.sh linux    # AppImage    (must run on Linux)
```

> **Note:** macOS installers can only be built on macOS, and Linux AppImages on
> Linux. Cross-building is not supported by this setup. These targets are
> defined but not yet smoke-tested — see ISSUES.md (EE-5).

## What goes into the package

`gui/electron-builder.yml` declares `extraResources` that copy the following
into `resources/pipeline/` inside the packaged app:

- `job_pipeline/` (without `__pycache__`)
- `python-runtime/tzdata` (the pinned IANA timezone fallback, staged at the repository root)
- `run.ps1`, `run.cmd`, `scripts/`
- `config/*.json` (excluding `*.local.json` — user-private config never ships)
- `docs/`, `README.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md`
- the Git-pinned only-cli production runtime, installed with optional dependencies omitted

Runtime data (`data/`, `reports/`, `logs/`) is never packaged; it is created at
run time. Version 2.0.0 completed the installed-layout service, tool, shortcut,
and scheduler verification tracked as ISSUES.md EE-9.

## Suggested release checklist

1. Bump `version` in `gui/package.json`.
2. Run `python -m unittest discover -s tests`.
3. Run the renderer tests, lint, build, and Electron boundary tests.
4. Run dependency, static-analysis, tracked-source privacy, and package-payload privacy gates.
5. Run `packaging/build-windows.ps1` and platform-native POSIX builders where applicable.
6. Install the result, run one installed only-cli workflow, verify the scheduled wake, and check the Start Menu shortcut.
7. Sign and timestamp the Windows artifacts when a trusted signing certificate is available.
8. Create a release and attach the verified artifacts.
