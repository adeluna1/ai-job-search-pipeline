$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$env:PAPERCLIP_TELEMETRY_DISABLED = '1'

# Locate Node.js 20+ on PATH (cross-platform). Override with NODE_EXE if needed.
$node = $env:NODE_EXE
if (-not $node) {
    $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCommand) { $node = $nodeCommand.Source }
}
if (-not $node -or -not (Test-Path $node)) {
    throw 'Node.js 20+ was not found on PATH. Install Node.js (https://nodejs.org) or set NODE_EXE to the node executable.'
}

$entry = Join-Path $root 'node_modules\paperclipai\dist\index.js'
$dataDir = Join-Path $root '.paperclip-runtime'
$log = Join-Path $dataDir 'server-out.log'

if (-not (Test-Path $entry)) {
    throw "Paperclip is not installed at $entry. Run 'npm install' (or pnpm install) at the repository root first."
}

$healthy = $false
try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:3100/api/health' -TimeoutSec 3
    if ($h.status -eq 'ok') { $healthy = $true }
} catch {}
if ($healthy) { Write-Host 'Already healthy on 3100'; exit 0 }

if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }

$p = Start-Process -FilePath $node -ArgumentList "`"$entry`" run --data-dir `"$dataDir`"" -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru
Write-Host "spawned PID $($p.Id)"
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    try {
        $h = Invoke-RestMethod -Uri 'http://127.0.0.1:3100/api/health' -TimeoutSec 3
        if ($h.status -eq 'ok') { Write-Host 'HEALTHY'; exit 0 }
    } catch {}
    if ($p.HasExited) { Write-Host "EXITED code $($p.ExitCode)"; exit 1 }
}
Write-Host 'NOT HEALTHY after 180s'
exit 1
