param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('linkedin', 'glassdoor', 'zip_recruiter', 'indeed')]
    [string]$Site
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BaseUrl = 'http://127.0.0.1:7896'

# --- Resolve the site's login URL from config/access_policy.json -------------
$policyPath = Join-Path $ProjectRoot 'config\access_policy.json'
$policy = Get-Content $policyPath -Raw | ConvertFrom-Json
$siteEntry = $policy.session_sites.$Site
if (-not $siteEntry -or -not $siteEntry.login_url) {
    throw "No session_sites entry with a login_url for '$Site' in $policyPath."
}
$loginUrl = [string]$siteEntry.login_url

# --- Ensure AWB is running ----------------------------------------------------
function Test-Bridge {
    try {
        $health = Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 3
        return ($health.ok -eq $true)
    }
    catch {
        return $false
    }
}

if (-not (Test-Bridge)) {
    $awbPath = Join-Path $ProjectRoot 'tools\upstream\agent-web-browser\src-tauri\target\release\AWB.exe'
    if (-not (Test-Path $awbPath)) {
        throw "AWB.exe not found at $awbPath. Build it with cargo build --release first."
    }
    Write-Host "Starting Agent Web Browser..."
    Start-Process $awbPath
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Test-Bridge)) {
        if ((Get-Date) -gt $deadline) { throw 'AWB did not become healthy within 45 seconds.' }
        Start-Sleep -Milliseconds 500
    }
}

# --- Authenticate against the local bridge ------------------------------------
$tokenPath = Join-Path $env:LOCALAPPDATA 'agent-web-browser\api-token'
if (-not (Test-Path $tokenPath)) {
    throw "AWB API token not found at $tokenPath. Start AWB once to create it."
}
$token = (Get-Content $tokenPath -Raw).Trim()
$headers = @{ Authorization = "Bearer $token" }

function Invoke-Bridge {
    param([string]$Method, [string]$Path, [object]$Body = $null)
    $params = @{
        Method     = $Method
        Uri        = "$BaseUrl$Path"
        Headers    = $headers
        TimeoutSec = 20
    }
    if ($null -ne $Body) {
        $params.ContentType = 'application/json'
        $params.Body = ($Body | ConvertTo-Json -Compress)
    }
    $response = Invoke-RestMethod @params
    if ($response.ok -eq $false) { throw "AWB $Path failed: $($response.error)" }
    return $response
}

$platform = @{
    linkedin      = 'linkedin'
    glassdoor     = 'glassdoor'
    zip_recruiter = 'ziprecruiter'
    indeed        = 'indeed'
}[$Site]

# --- Show the window and navigate a site tab to the login page ----------------
Invoke-Bridge -Method POST -Path '/window/show' -Body @{} | Out-Null
$status = Invoke-Bridge -Method GET -Path '/status'
$tab = @($status.tabs | Where-Object { $_.platform -eq $platform } | Select-Object -First 1)
if ($tab.Count -gt 0) {
    $tabId = [int]$tab[0].id
    Invoke-Bridge -Method POST -Path '/tabs/switch' -Body @{ id = $tabId } | Out-Null
    Invoke-Bridge -Method POST -Path '/tabs/navigate' -Body @{ id = $tabId; url = $loginUrl } | Out-Null
}
else {
    Invoke-Bridge -Method POST -Path '/tabs/new' -Body @{ count = 1; url = $loginUrl } | Out-Null
}

Write-Host ''
Write-Host "AWB is showing the $Site login page: $loginUrl"
Write-Host 'Log in inside the AWB window (sessions/cookies persist in its local profile).'
[void](Read-Host 'Press Enter here when you have finished logging in')

# --- Verify the page no longer shows a login wall ------------------------------
$page = Invoke-Bridge -Method GET -Path '/page/text'
$text = ''
if ($page.result -and $page.result.text) { $text = [string]$page.result.text }
$loginMarkers = @(
    'forgot password',
    'email or phone',
    'sign in to',
    'log in to',
    'join now',
    'create an account',
    'new to linkedin'
)
$found = @($loginMarkers | Where-Object { $text -match [regex]::Escape($_) })
$verified = ($text.Trim().Length -gt 0) -and ($found.Count -eq 0)

# --- Persist session state for the pipeline ------------------------------------
$sessionsPath = Join-Path $ProjectRoot 'data\site_sessions.json'
$sessions = @{}
if (Test-Path $sessionsPath) {
    try {
        $existing = Get-Content $sessionsPath -Raw | ConvertFrom-Json
        foreach ($property in $existing.PSObject.Properties) { $sessions[$property.Name] = $property.Value }
    }
    catch {
        $sessions = @{}
    }
}
$sessions[$Site] = [ordered]@{
    site         = $Site
    login_url    = $loginUrl
    logged_in_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    verified     = $verified
}
$dataDir = Split-Path -Parent $sessionsPath
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir | Out-Null }
($sessions | ConvertTo-Json -Depth 5) | Set-Content $sessionsPath -Encoding UTF8

if ($verified) {
    Write-Host "$Site session looks logged in; recorded in $sessionsPath"
    exit 0
}
Write-Host "WARNING: the page still shows login markers ($($found -join ', '))."
Write-Host "Recorded verified=false in $sessionsPath. Re-run this script if login is incomplete."
exit 1
