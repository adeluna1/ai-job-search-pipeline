# Packaging AI Job Search Pipeline

This directory builds the selectively integrated Electron desktop interface and
Windows release artifacts. The package includes this repository''s Python source,
scripts, configuration templates, and documentation. It does not bundle Python,
JobSpy, Paperclip, Docker, Resume-Matcher, browser-use, WebClaw, or Agent Web
Browser runtimes.

## Runtime requirements

- Windows 10 or later.
- Python 3.10+ available on PATH for pipeline commands.
- Internet access for live discovery and verification.
- Node.js 20+ only when Paperclip is used.
- Docker Desktop only when Resume-Matcher is used.
- Optional integrations must be installed with the repository scripts.

The installed application copies the bundled pipeline to its per-user Electron
data directory on first run. Runtime data, reports, and local configuration stay
writable there. Existing user configuration is preserved during upgrades.

## Build artifacts

All final artifacts land in the repository release directory:

| Artifact | Platform |
|---|---|
| AIJobSearchPipeline-Setup-<version>.exe | Windows per-user installer |
| AIJobSearchPipeline-portable-<version>.zip | Windows portable package |
| AI Job Search Pipeline-<version>.dmg or .zip | macOS |
| AI Job Search Pipeline-<version>.AppImage | Linux |

The version comes from gui/package.json.

## Windows build

Install Node.js and Inno Setup 6, then run:

    powershell -NoProfile -ExecutionPolicy Bypass -File .\packaging\build-windows.ps1

The script installs GUI dependencies if needed, runs tests and the production
build, creates the Electron unpacked directory and zip, then compiles the Inno
Setup installer. If Inno Setup is absent, the Electron zip may already exist but
the installer step stops with an actionable error.

## Package contents

electron-builder copies these project assets into resources/pipeline:

- job_pipeline and command entry points
- scripts and non-private JSON configuration templates
- pyproject.toml
- docs, README, license, and third-party notices

It intentionally excludes .env files, local configuration, resumes, job data,
reports, logs, dependency runtimes, browser profiles, and API keys.

## Release checklist

1. Update the version in gui/package.json.
2. Run npm.cmd test, npm.cmd run lint, and npm.cmd run build in gui.
3. Run the Python test suite from the repository root.
4. Run packaging/build-windows.ps1.
5. Smoke-test search, report opening, and embedded login on a clean Windows user.
6. Publish checksums with the GitHub Release.