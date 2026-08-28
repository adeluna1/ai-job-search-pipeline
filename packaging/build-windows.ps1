<#
.SYNOPSIS
    Builds the Expedient Employment Windows release artifacts:
      1. Builds the GUI (npm run build in gui/).
      2. Runs electron-builder for --win dir zip (unpacked dir + portable zip).
      3. Compiles installer/windows.iss with Inno Setup 6 (ISCC.exe).

    Artifacts land in release/ at the repository root:
      - ExpedientEmployment-Setup-<version>.exe   (per-user installer)
      - ExpedientEmployment-portable-<version>.zip (portable zip)

    One-time prerequisite: Inno Setup 6 (https://jrsoftware.org/isinfo.php).
    Nothing is installed globally; electron-builder runs through npx.
#>
param(
    [string]$Version,
    [switch]$SkipOnlyCliInstall,
    [switch]$SkipGuiBuild,
    [switch]$SkipPythonRuntimeInstall
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$GuiDir = Join-Path $RepoRoot 'gui'
$ReleaseDir = Join-Path $RepoRoot 'release'
$StagingRoot = Join-Path ([IO.Path]::GetTempPath()) 'expedient-employment-builder'
$PythonRuntimeDir = Join-Path $RepoRoot 'python-runtime'

if (Test-Path -LiteralPath $StagingRoot) {
    $resolvedStageRoot = (Resolve-Path -LiteralPath $StagingRoot).Path
    $resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (
        -not $resolvedStageRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolvedStageRoot) -ne 'expedient-employment-builder'
    ) {
        throw "Refusing to remove unexpected build staging path: $resolvedStageRoot"
    }
    Remove-Item -LiteralPath $resolvedStageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $StagingRoot | Out-Null

# --- Resolve the app version from gui/package.json ---------------------------
if (-not $Version) {
    $pkg = Get-Content (Join-Path $GuiDir 'package.json') -Raw | ConvertFrom-Json
    $Version = [string]$pkg.version
}
if (-not $Version) { throw 'Could not determine the app version from gui/package.json.' }
Write-Host "Building Expedient Employment $Version"

# --- 1. Build the GUI ---------------------------------------------------------
Push-Location $GuiDir
try {
    if (-not (Test-Path (Join-Path $GuiDir 'node_modules'))) {
        Write-Host 'Installing GUI dependencies (npm install)...'
        & npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed in gui/.' }
    }
    if (-not $SkipOnlyCliInstall) {
        Write-Host 'Installing pinned only-cli runtime without optional fingerprint transport...'
        & npm run only-cli:install
        if ($LASTEXITCODE -ne 0) { throw 'only-cli runtime install failed.' }
    }
    if (-not $SkipPythonRuntimeInstall) {
        if (Test-Path -LiteralPath $PythonRuntimeDir) {
            Remove-Item -LiteralPath $PythonRuntimeDir -Recurse -Force
        }
        New-Item -ItemType Directory -Path $PythonRuntimeDir | Out-Null
        $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
        Write-Host 'Installing the pinned Windows timezone runtime...'
        if ($pyLauncher) {
            & $pyLauncher.Source -3 -m pip install --disable-pip-version-check --no-compile --no-deps --target $PythonRuntimeDir 'tzdata==2026.3'
        } else {
            $pythonCommand = (Get-Command python.exe -ErrorAction Stop).Source
            & $pythonCommand -m pip install --disable-pip-version-check --no-compile --no-deps --target $PythonRuntimeDir 'tzdata==2026.3'
        }
        if ($LASTEXITCODE -ne 0) { throw 'tzdata runtime install failed.' }
    } elseif (-not (Test-Path -LiteralPath (Join-Path $PythonRuntimeDir 'tzdata'))) {
        throw 'SkipPythonRuntimeInstall was requested but python-runtime/tzdata is missing.'
    }
    if (-not $SkipGuiBuild) {
        Write-Host 'Building the GUI (npm run build)...'
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'GUI build failed.' }
    } elseif (-not (Test-Path -LiteralPath (Join-Path $GuiDir 'dist\index.html'))) {
        throw 'SkipGuiBuild was requested but gui/dist/index.html is missing.'
    }

    # --- 2. electron-builder: unpacked dir + portable zip ---------------------
    Write-Host 'Running electron-builder (--win dir zip)...'
    $builderSucceeded = $false
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $staleStage = Join-Path $StagingRoot 'win-unpacked.tmp'
        if (Test-Path -LiteralPath $staleStage) {
            $resolvedStage = (Resolve-Path -LiteralPath $staleStage).Path
            $resolvedRelease = [IO.Path]::GetFullPath($StagingRoot)
            if (-not $resolvedStage.StartsWith($resolvedRelease, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove unexpected staging path: $resolvedStage"
            }
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
        & npx --yes electron-builder --config electron-builder.yml --win dir zip "--config.directories.output=$StagingRoot"
        if ($LASTEXITCODE -eq 0) {
            $builderSucceeded = $true
            break
        }
        if ($attempt -lt 2) {
            Write-Warning 'electron-builder failed once; clearing its verified staging directory and retrying.'
            Start-Sleep -Seconds 2
        }
    }
    if (-not $builderSucceeded) { throw 'electron-builder failed after one clean retry.' }
}
finally {
    Pop-Location
}

$UnpackedDir = Join-Path $StagingRoot 'win-unpacked'
if (-not (Test-Path $UnpackedDir)) {
    throw "Expected electron-builder output at $UnpackedDir but it was not created."
}

# --- Collect the portable zip into release/ ----------------------------------
if (-not (Test-Path $ReleaseDir)) { New-Item -ItemType Directory -Path $ReleaseDir | Out-Null }

$zipArtifact = Get-ChildItem $StagingRoot -Filter "*.zip" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $zipArtifact) { throw 'electron-builder did not produce a portable zip.' }
$zipOut = Join-Path $ReleaseDir "ExpedientEmployment-portable-$Version.zip"
Copy-Item $zipArtifact.FullName $zipOut -Force
Write-Host "Portable zip: $zipOut"

# --- 3. Inno Setup installer ---------------------------------------------------
$isccCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
)
$uninstallRoots = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
foreach ($uninstallRoot in $uninstallRoots) {
    $installLocations = Get-ItemProperty $uninstallRoot -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -like 'Inno Setup version 6*' } |
        Select-Object -ExpandProperty InstallLocation -ErrorAction SilentlyContinue
    foreach ($installLocation in $installLocations) {
        if ($installLocation) {
            $isccCandidates += Join-Path $installLocation 'ISCC.exe'
        }
    }
}
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($isccCommand) { $iscc = $isccCommand.Source }
}
if (-not $iscc) {
    throw @(
        'Inno Setup 6 (ISCC.exe) was not found.'
        'Install it from https://jrsoftware.org/isinfo.php (one-time install),'
        'then re-run this script. The portable zip above is already built and usable.'
    ) -join ' '
}

Write-Host "Compiling the installer with $iscc ..."
& $iscc "/DAppVersion=$Version" "/DSourceDir=$UnpackedDir" (Join-Path $RepoRoot 'installer\windows.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

$setupOut = Join-Path $ReleaseDir "ExpedientEmployment-Setup-$Version.exe"
if (-not (Test-Path $setupOut)) {
    throw "Inno Setup finished but $setupOut was not created."
}

Write-Host ''
Write-Host 'Windows release complete:'
Write-Host "  Installer:   $setupOut"
Write-Host "  Portable:    $zipOut"

$resolvedStageRoot = (Resolve-Path -LiteralPath $StagingRoot).Path
$resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
if (
    $resolvedStageRoot.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -and
    (Split-Path -Leaf $resolvedStageRoot) -eq 'expedient-employment-builder'
) {
    Remove-Item -LiteralPath $resolvedStageRoot -Recurse -Force
}
