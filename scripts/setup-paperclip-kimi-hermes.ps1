$ErrorActionPreference = 'Stop'
$script:ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Node.js must be available on PATH (Node 20+). Override with NODE_EXE if needed.
if ($env:NODE_EXE -and (Test-Path $env:NODE_EXE)) {
    $env:Path = (Split-Path -Parent $env:NODE_EXE) + ';' + $env:Path
}
elseif (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js 20+ was not found on PATH. Install Node.js (https://nodejs.org) or set NODE_EXE to the node executable.'
}

function Test-PaperclipHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:3100/api/health' -TimeoutSec 3
        return $health.status -eq 'ok'
    }
    catch { return $false }
}

if (-not (Test-PaperclipHealth)) {
    & (Join-Path $PSScriptRoot 'paperclip-start-local.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Paperclip is not healthy; could not start it.' }
}

function Invoke-PaperclipApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        $Body
    )
    $params = @{
        Method = $Method
        Uri = "http://127.0.0.1:3100/api$Path"
        TimeoutSec = 30
    }
    if ($null -ne $Body) {
        $params.ContentType = 'application/json'
        $params.Body = $Body | ConvertTo-Json -Depth 12 -Compress
    }
    return Invoke-RestMethod @params
}

$hermesExe = Join-Path $script:ProjectRoot 'tools\hermes-runtime\Scripts\hermes.exe'
$resumePath = if ($env:JOB_PIPELINE_RESUME) { $env:JOB_PIPELINE_RESUME } else { Join-Path $env:USERPROFILE 'Downloads\resume.docx' }
$applicationProfile = Join-Path $script:ProjectRoot 'data\application_profile.json'

function Ensure-HermesAgent {
    param(
        [string]$CompanyId,
        [string]$Name,
        [string]$Role,
        [string]$Title,
        [string]$Icon,
        [string]$Capabilities,
        [string]$BundleFolder,
        [string]$Provider,
        [string]$ReportsTo
    )

    $agents = Invoke-PaperclipApi -Method 'GET' -Path "/companies/$CompanyId/agents"
    $agent = @($agents) | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    $bundleRoot = Join-Path $script:ProjectRoot "paperclip\agents\$BundleFolder"

    $adapterConfig = @{
        hermesCommand = $hermesExe
        cwd = $script:ProjectRoot
        timeoutSec = 900
        env = @{
            JOB_PIPELINE_PROJECT_ROOT = $script:ProjectRoot
            JOB_PIPELINE_RESUME = $resumePath
            JOB_PIPELINE_APPLICATION_PROFILE = $applicationProfile
        }
    }
    if ($Provider) { $adapterConfig.provider = $Provider }

    if (-not $agent) {
        $payload = @{
            name = $Name
            role = $Role
            title = $Title
            icon = $Icon
            capabilities = $Capabilities
            adapterType = 'hermes_local'
            adapterConfig = $adapterConfig
            budgetMonthlyCents = 0
            permissions = @{
                canCreateAgents = $false
                canCreateSkills = $false
            }
            metadata = @{
                pipelineRole = $BundleFolder
                externalSubmissionRequiresConfirmation = $true
            }
        }
        if ($ReportsTo) { $payload.reportsTo = $ReportsTo }
        $agent = Invoke-PaperclipApi -Method 'POST' -Path "/companies/$CompanyId/agents" -Body $payload
        Write-Host "Created $Name ($($agent.id))"
    }
    else {
        Write-Host "Using existing $Name ($($agent.id))"
    }

    $agent = Invoke-PaperclipApi -Method 'PATCH' -Path "/agents/$($agent.id)" -Body @{
        adapterConfig = $adapterConfig
        replaceAdapterConfig = $false
    }

    Invoke-PaperclipApi -Method 'PATCH' -Path "/agents/$($agent.id)/instructions-bundle" -Body @{
        mode = 'external'
        rootPath = $bundleRoot
        entryFile = 'AGENTS.md'
        clearLegacyPromptTemplate = $true
    } | Out-Null
    return $agent
}

$companies = Invoke-PaperclipApi -Method 'GET' -Path '/companies'
$company = @($companies) | Where-Object { $_.name -eq 'AI Job Search Team' } | Select-Object -First 1
if (-not $company) { throw 'Company "AI Job Search Team" not found. Run scripts\setup-paperclip.ps1 first.' }

$agentK = Ensure-HermesAgent `
    -CompanyId $company.id `
    -Name 'Agent K - Recruiter (Kimi Coding)' `
    -Role 'ceo' `
    -Title 'Recruiting Lead and Job Scout via Hermes Kimi Coding' `
    -Icon 'search' `
    -Capabilities 'Discover fresh Recruiting Coordinator roles through JobSpy/WebClaw using the Hermes runtime with the Kimi Coding provider; record board coverage and hand qualified leads to verifiers.' `
    -BundleFolder 'agent-a' `
    -Provider 'kimi-coding' `
    -ReportsTo $null

$agentH = Ensure-HermesAgent `
    -CompanyId $company.id `
    -Name 'Agent H - Verifier (Hermes)' `
    -Role 'researcher' `
    -Title 'Match Analyst and Posting Verifier via Hermes' `
    -Icon 'shield' `
    -Capabilities 'Independently verify posting freshness, employer source, requirements, evidence, gaps, and application recommendation through the Hermes runtime with its configured provider.' `
    -BundleFolder 'agent-b' `
    -Provider $null `
    -ReportsTo $agentK.id

Write-Host ''
Write-Host "Kimi/Hermes agents configured (paused by default)."
Write-Host "  Agent K - Recruiter (Kimi Coding): $($agentK.id)"
Write-Host "  Agent H - Verifier (Hermes):       $($agentH.id)"
Write-Host 'Hermes CLI expected at: ' $hermesExe
