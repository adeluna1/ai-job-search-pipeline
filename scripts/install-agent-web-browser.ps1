param(
    [switch]$Build,
    [switch]$RunTests
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceRoot = Join-Path $ProjectRoot 'tools\upstream\agent-web-browser'
$PatchPath = Join-Path $ProjectRoot 'patches\agent-web-browser\0001-allow-documented-job-board-navigation.patch'
$Repository = 'https://github.com/BarnsL/agent-web-browser.git'
$PinnedCommit = 'cf96d04c6f2e369a4574786f75957c040cb7bf9f'

if (-not (Test-Path -LiteralPath $SourceRoot)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SourceRoot) | Out-Null
    & git clone $Repository $SourceRoot
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not clone Agent Web Browser.'
    }
}

$safeSource = (Resolve-Path $SourceRoot).Path.Replace('\', '/')
$currentCommit = (& git -c "safe.directory=$safeSource" -C $SourceRoot rev-parse HEAD).Trim()
if ($currentCommit -ne $PinnedCommit) {
    throw "Agent Web Browser is at $currentCommit; expected reviewed commit $PinnedCommit."
}

$previousPreference = $ErrorActionPreference
$ErrorActionPreference = 'SilentlyContinue'
& git -c "safe.directory=$safeSource" -C $SourceRoot apply --reverse --check $PatchPath 2>$null
$patchAlreadyApplied = $LASTEXITCODE -eq 0
$ErrorActionPreference = $previousPreference

if ($patchAlreadyApplied) {
    Write-Host 'Reviewed job-board navigation patch is already applied.'
}
else {
    & git -c "safe.directory=$safeSource" -C $SourceRoot apply --check $PatchPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Agent Web Browser patch state is unknown; inspect the source before building.'
    }
    & git -c "safe.directory=$safeSource" -C $SourceRoot apply $PatchPath
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not apply the narrow Glassdoor/ZipRecruiter navigation patch.'
    }
}

Write-Host "Agent Web Browser source ready at reviewed commit $PinnedCommit"
Write-Host 'Safe pipeline mode: first-party Glassdoor/ZipRecruiter navigation and visible-text reads only.'

if ($RunTests -or $Build) {
    $cargoCommand = Get-Command cargo -ErrorAction SilentlyContinue
    if ($cargoCommand) {
        $cargoPath = $cargoCommand.Source
    }
    else {
        $cargoPath = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
    }
    if (-not (Test-Path -LiteralPath $cargoPath)) {
        throw (
            'Rust Cargo is not installed. Install Rust stable plus Microsoft C++ Build Tools, ' +
            'then rerun this script with -RunTests or -Build.'
        )
    }
}

if ($RunTests) {
    & $cargoPath test --manifest-path (Join-Path $SourceRoot 'src-tauri\Cargo.toml')
    if ($LASTEXITCODE -ne 0) {
        throw 'Agent Web Browser Rust tests failed.'
    }
}

if ($Build) {
    & $cargoPath build --release --manifest-path (Join-Path $SourceRoot 'src-tauri\Cargo.toml')
    if ($LASTEXITCODE -ne 0) {
        throw 'Agent Web Browser release build failed.'
    }
    Write-Host "Built: $(Join-Path $SourceRoot 'src-tauri\target\release\smab.exe')"
}
