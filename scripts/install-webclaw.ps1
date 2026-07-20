param(
    [string]$InstallDir = (Join-Path (Split-Path -Parent $PSScriptRoot) 'tools\webclaw')
)

$ErrorActionPreference = 'Stop'
$Headers = @{ 'User-Agent' = 'AI-Job-Search-Pipeline' }
$Release = Invoke-RestMethod -Uri 'https://api.github.com/repos/0xMassi/webclaw/releases/latest' -Headers $Headers
$Asset = $Release.assets | Where-Object { $_.name -match 'x86_64-pc-windows-msvc\.zip$' } | Select-Object -First 1
$Checksums = $Release.assets | Where-Object { $_.name -eq 'SHA256SUMS' } | Select-Object -First 1

if (-not $Asset) {
    throw "No Windows x86_64 WebClaw asset was found in release $($Release.tag_name)."
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("webclaw-install-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

try {
    $Archive = Join-Path $TempDir $Asset.name
    Invoke-WebRequest -Uri $Asset.browser_download_url -Headers $Headers -OutFile $Archive

    if ($Checksums) {
        $ChecksumFile = Join-Path $TempDir 'SHA256SUMS'
        Invoke-WebRequest -Uri $Checksums.browser_download_url -Headers $Headers -OutFile $ChecksumFile
        $ExpectedLine = Get-Content $ChecksumFile | Where-Object { $_ -match [regex]::Escape($Asset.name) } | Select-Object -First 1
        if (-not $ExpectedLine) {
            throw "Checksum for $($Asset.name) was not present in SHA256SUMS."
        }
        $ExpectedHash = ($ExpectedLine -split '\s+')[0].ToUpperInvariant()
        $ActualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Archive).Hash.ToUpperInvariant()
        if ($ActualHash -ne $ExpectedHash) {
            throw 'WebClaw archive checksum verification failed.'
        }
    }

    Expand-Archive -LiteralPath $Archive -DestinationPath $InstallDir -Force
    $Executable = Get-ChildItem -LiteralPath $InstallDir -Recurse -Filter 'webclaw.exe' | Select-Object -First 1
    if (-not $Executable) {
        throw 'webclaw.exe was not found after extracting the release archive.'
    }

    $Target = Join-Path $InstallDir 'webclaw.exe'
    if ($Executable.FullName -ne $Target) {
        Copy-Item -LiteralPath $Executable.FullName -Destination $Target -Force
    }

    & $Target --version
    Write-Host "Installed WebClaw $($Release.tag_name) at $Target"
}
finally {
    Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}
