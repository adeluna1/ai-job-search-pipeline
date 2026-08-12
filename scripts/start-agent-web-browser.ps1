param(
    [switch]$NoShow
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Executable = Join-Path $ProjectRoot 'tools\upstream\agent-web-browser\src-tauri\target\release\smab.exe'
$BaseUrl = 'http://127.0.0.1:7896'
$TaskName = 'AIJobSearch-AgentWebBrowser-Launch'
$UnsafeFlags = @(
    'SMAB_ALLOW_ARBITRARY_NAVIGATION',
    'SMAB_UNSAFE_TOOLS_ENABLED',
    'SMAB_EXTENSION_MUTATION_ENABLED',
    'SMAB_ALLOW_WRITES'
)

function Test-EnabledFlag([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    return $value -and $value.Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
}

function Get-BrowserHealth {
    try {
        return Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 2
    }
    catch {
        return $null
    }
}

function Get-BrowserHeaders {
    $tokenPath = Join-Path $env:LOCALAPPDATA 'agent-web-browser\api-token'
    if (-not (Test-Path -LiteralPath $tokenPath)) {
        throw 'Agent Web Browser API token is missing. Start the browser once to create it.'
    }
    $token = (Get-Content -Raw -LiteralPath $tokenPath).Trim()
    if ($token.Length -lt 32) {
        throw 'Agent Web Browser API token is invalid.'
    }
    return @{ Authorization = "Bearer $token" }
}

$activeUnsafeFlags = @($UnsafeFlags | Where-Object { Test-EnabledFlag $_ })
if ($activeUnsafeFlags.Count -gt 0) {
    throw "Refusing to start Agent Web Browser outside safe read-only mode. Unset: $($activeUnsafeFlags -join ', ')"
}

$health = Get-BrowserHealth
if (-not $health) {
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw (
            'Agent Web Browser is not built. Run scripts\install-agent-web-browser.ps1 -Build, ' +
            'then retry.'
        )
    }

    # A temporary interactive task launches outside the short-lived automation
    # job object. Deleting only the task definition does not stop the browser.
    $startTime = (Get-Date).AddMinutes(2).ToString('HH:mm')
    & schtasks.exe /Create /TN $TaskName /TR ('"{0}"' -f $Executable) /SC ONCE `
        /ST $startTime /RL LIMITED /IT /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not register the interactive Agent Web Browser launch task.'
    }
    try {
        & schtasks.exe /Run /TN $TaskName | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not start the interactive Agent Web Browser launch task.'
        }
    }
    finally {
        & schtasks.exe /Delete /TN $TaskName /F | Out-Null
    }

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        $health = Get-BrowserHealth
        if ($health.ok) {
            break
        }
    }
    if (-not $health.ok) {
        throw 'Agent Web Browser did not become healthy at http://127.0.0.1:7896.'
    }
}

$headers = Get-BrowserHeaders
if (-not $NoShow) {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/window/show" -Headers $headers `
        -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null
}

$requiredPlatforms = @('glassdoor', 'ziprecruiter')
$status = $null
for ($attempt = 0; $attempt -lt 24; $attempt++) {
    $status = Invoke-RestMethod -Uri "$BaseUrl/status" -Headers $headers -TimeoutSec 3
    $available = @($status.tabs | ForEach-Object { $_.platform })
    if (@($requiredPlatforms | Where-Object { $_ -notin $available }).Count -eq 0) {
        break
    }
    Start-Sleep -Milliseconds 500
}

$available = @($status.tabs | ForEach-Object { $_.platform })
$missing = @($requiredPlatforms | Where-Object { $_ -notin $available })
if ($missing.Count -gt 0) {
    throw "Agent Web Browser started, but required tabs are missing: $($missing -join ', ')"
}

Write-Host 'Agent Web Browser is running with Glassdoor and ZipRecruiter tabs ready.'
