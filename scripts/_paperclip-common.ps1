$ErrorActionPreference = 'Stop'

$script:ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$script:PaperclipDataDir = Join-Path $script:ProjectRoot '.paperclip-runtime'
$bundledRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
$script:NodeBin = Join-Path $bundledRuntime 'node\bin'
$script:PnpmBin = Join-Path $bundledRuntime 'bin\fallback\pnpm.cmd'
$script:LocalPaperclip = Join-Path $script:ProjectRoot 'node_modules\.bin\paperclipai.ps1'

if (-not (Test-Path (Join-Path $script:NodeBin 'node.exe'))) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if (-not $nodeCommand) {
        throw 'Node.js 20+ was not found. Install Node.js or run this project from Codex with its bundled runtime.'
    }
    $script:NodeBin = Split-Path -Parent $nodeCommand.Source
}
if (-not (Test-Path $script:PnpmBin)) {
    $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
    if (-not $pnpmCommand) {
        throw 'pnpm was not found. Install pnpm or run this project from Codex with its bundled runtime.'
    }
    $script:PnpmBin = $pnpmCommand.Source
}

$script:ProjectBin = Join-Path $script:ProjectRoot 'node_modules\.bin'
$env:Path = "$script:ProjectBin;$script:NodeBin;$(Split-Path -Parent $script:PnpmBin);$env:Path"
$env:PAPERCLIP_TELEMETRY_DISABLED = '1'

function Invoke-Paperclip {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$CommandArgs,
        [switch]$Json
    )

    $tail = @('--data-dir', $script:PaperclipDataDir)
    if ($Json) {
        $tail += '--json'
    }
    if (Test-Path $script:LocalPaperclip) {
        $output = & $script:LocalPaperclip @CommandArgs @tail
    }
    else {
        $output = & $script:PnpmBin dlx paperclipai @CommandArgs @tail
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Paperclip command failed: $($CommandArgs -join ' ')"
    }
    if ($Json) {
        return ($output -join "`n") | ConvertFrom-Json
    }
    return $output
}

function Test-PaperclipHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:3100/api/health' -TimeoutSec 3
        return $health.status -eq 'ok'
    }
    catch {
        return $false
    }
}
