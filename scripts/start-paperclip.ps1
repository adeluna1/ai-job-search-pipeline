$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_paperclip-common.ps1')

if (Test-PaperclipHealth) {
    Write-Host 'Paperclip is already running at http://127.0.0.1:3100'
    exit 0
}

$serverScript = Join-Path $PSScriptRoot 'paperclip-server.ps1'
$process = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $serverScript) `
    -WindowStyle Hidden `
    -PassThru

$deadline = (Get-Date).AddMinutes(3)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    if (Test-PaperclipHealth) {
        Write-Host "Paperclip started (process $($process.Id)): http://127.0.0.1:3100"
        exit 0
    }
    if ($process.HasExited) {
        throw "Paperclip exited before becoming healthy (exit code $($process.ExitCode)). Check .paperclip-runtime\instances\default\logs."
    }
}

throw 'Paperclip did not become healthy within three minutes. Check .paperclip-runtime\instances\default\logs.'
