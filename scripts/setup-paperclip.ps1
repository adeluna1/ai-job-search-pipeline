$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_paperclip-common.ps1')

if (-not (Test-PaperclipHealth)) {
    & (Join-Path $PSScriptRoot 'start-paperclip.ps1')
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

function Find-ByName {
    param($Collection, [string]$Name)
    return @($Collection) | Where-Object { $_.name -eq $Name } | Select-Object -First 1
}

function Ensure-Agent {
    param(
        [string]$CompanyId,
        [string]$Name,
        [string]$Role,
        [string]$Title,
        [string]$Icon,
        [string]$Capabilities,
        [string]$BundleFolder,
        [AllowNull()][string]$ReportsTo
    )

    $agents = Invoke-PaperclipApi -Method 'GET' -Path "/companies/$CompanyId/agents"
    $agent = Find-ByName $agents $Name
    $bundleRoot = Join-Path $script:ProjectRoot "paperclip\agents\$BundleFolder"
    $resumePath = Join-Path $env:USERPROFILE 'Downloads\Albert Deluna ResumeV1.docx'
    $applicationProfile = Join-Path $script:ProjectRoot 'data\application_profile.json'
    $pythonPath = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $codexExe = Get-ChildItem -LiteralPath (Join-Path $script:ProjectRoot 'node_modules\.pnpm') -Recurse -Filter 'codex.exe' |
        Where-Object { $_.FullName -like '*@openai+codex*\vendor\x86_64-pc-windows-msvc\bin\codex.exe' } |
        Select-Object -First 1
    if (-not $codexExe) {
        throw 'The project-local Codex executable was not found. Run pnpm install before configuring Paperclip.'
    }

    $adapterConfig = @{
        command = $codexExe.FullName
        cwd = $script:ProjectRoot
        timeoutSec = 900
        dangerouslyBypassApprovalsAndSandbox = $false
        # Keep Codex workspace boundaries while avoiding the administrator-only
        # elevated Windows sandbox bootstrap in unattended Paperclip runs.
        extraArgs = @(
            '--sandbox', 'workspace-write',
            '--add-dir', $script:ProjectRoot,
            '-c', 'windows.sandbox="unelevated"',
            '-c', 'sandbox_workspace_write.network_access=true'
        )
        env = @{
            JOB_PIPELINE_PROJECT_ROOT = $script:ProjectRoot
            JOB_PIPELINE_RESUME = $resumePath
            JOB_PIPELINE_APPLICATION_PROFILE = $applicationProfile
            JOB_PIPELINE_PYTHON = $pythonPath
        }
    }

    if (-not $agent) {
        $payload = @{
            name = $Name
            role = $Role
            title = $Title
            icon = $Icon
            capabilities = $Capabilities
            adapterType = 'codex_local'
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
        if ($ReportsTo) {
            $payload.reportsTo = $ReportsTo
        }
        $agent = Invoke-PaperclipApi -Method 'POST' -Path "/companies/$CompanyId/agents" -Body $payload
        Write-Host "Created $Name ($($agent.id))"
    }
    else {
        Write-Host "Using existing $Name ($($agent.id))"
    }

    # Re-apply the safe adapter contract on every setup run so upgrades and
    # existing installations cannot retain Paperclip's permissive defaults.
    $agent = Invoke-PaperclipApi -Method 'PATCH' -Path "/agents/$($agent.id)" -Body @{
        adapterConfig = $adapterConfig
        replaceAdapterConfig = $false
    }

    $bundlePayload = @{
        mode = 'external'
        rootPath = $bundleRoot
        entryFile = 'AGENTS.md'
        clearLegacyPromptTemplate = $true
    }
    Invoke-PaperclipApi -Method 'PATCH' -Path "/agents/$($agent.id)/instructions-bundle" -Body $bundlePayload | Out-Null
    return $agent
}

$companyName = 'AI Job Search Team'
$companies = Invoke-PaperclipApi -Method 'GET' -Path '/companies'
$company = Find-ByName $companies $companyName
if (-not $company) {
    $companyPayload = @{
        name = $companyName
        description = 'Three-agent recruiting workflow: JobSpy/WebClaw discovery, independent deterministic and optional ATS verification, then an approval-gated browser-use application.'
        budgetMonthlyCents = 0
    }
    $company = Invoke-PaperclipApi -Method 'POST' -Path '/companies' -Body $companyPayload
    Write-Host "Created company $companyName ($($company.id))"
}

$goals = Invoke-PaperclipApi -Method 'GET' -Path "/companies/$($company.id)/goals"
$goalTitle = 'Land a strong-fit Recruiting Coordinator role'
$goal = @($goals) | Where-Object { $_.title -eq $goalTitle } | Select-Object -First 1
if (-not $goal) {
    $goal = Invoke-PaperclipApi -Method 'POST' -Path "/companies/$($company.id)/goals" -Body @{
        title = $goalTitle
        description = 'Find fresh roles, verify evidence-based fit, and apply only after candidate review and confirmation.'
        level = 'company'
        status = 'active'
    }
    Write-Host "Created goal $goalTitle ($($goal.id))"
}

$agentA = Ensure-Agent `
    -CompanyId $company.id `
    -Name 'Agent A - Recruiter' `
    -Role 'ceo' `
    -Title 'Recruiting Lead and Job Scout' `
    -Icon 'search' `
    -Capabilities 'Discover Recruiting Coordinator roles through JobSpy/WebClaw, hard-enforce exact geography, freshness, active state, and applied exclusions, then hand at most 10 resume-ranked current-run leads to Agent B.' `
    -BundleFolder 'agent-a' `
    -ReportsTo $null

$agentB = Ensure-Agent `
    -CompanyId $company.id `
    -Name 'Agent B - Verifier' `
    -Role 'researcher' `
    -Title 'Match Analyst and Posting Verifier' `
    -Icon 'shield' `
    -Capabilities 'Independently recheck at most 10 leads for exact geography, known-date freshness, applied history, active employer source, resume evidence, and gaps; optionally add authorized Resume-Matcher evidence.' `
    -BundleFolder 'agent-b' `
    -ReportsTo $agentA.id

$agentC = Ensure-Agent `
    -CompanyId $company.id `
    -Name 'Agent C - Application Assistant' `
    -Role 'general' `
    -Title 'Approval-Gated Application Assistant' `
    -Icon 'target' `
    -Capabilities 'Recheck applied history, prepare truthful packets, and use exact-domain browser-use only after packet-hash-bound confirmation; never invent answers or submit without exact approval.' `
    -BundleFolder 'agent-c' `
    -ReportsTo $agentA.id

$projects = Invoke-PaperclipApi -Method 'GET' -Path "/companies/$($company.id)/projects"
$projectName = 'Recruiting Coordinator Search'
$project = Find-ByName $projects $projectName
if (-not $project) {
    $project = Invoke-PaperclipApi -Method 'POST' -Path "/companies/$($company.id)/projects" -Body @{
        name = $projectName
        description = 'Paperclip-controlled pipeline backed by JobSpy, WebClaw, optional Resume-Matcher evidence, deterministic matching, and approval-gated browser-use packets.'
        status = 'in_progress'
        goalIds = @($goal.id)
        leadAgentId = $agentA.id
        color = '#2563EB'
        icon = 'target'
    }
    Write-Host "Created project $projectName ($($project.id))"
}

# Pause before assigning starter work so the installation cannot spend model credits unexpectedly.
foreach ($agent in @($agentA, $agentB, $agentC)) {
    try {
        Invoke-PaperclipApi -Method 'POST' -Path "/agents/$($agent.id)/pause" -Body @{} | Out-Null
    }
    catch {
        Write-Host "$($agent.name) was already paused or could not be paused: $($_.Exception.Message)"
    }
}

$issues = Invoke-PaperclipApi -Method 'GET' -Path "/companies/$($company.id)/issues?projectId=$($project.id)"
$starterIssues = @(
    @{
        title = 'A: Discover fresh Recruiting Coordinator roles'
        description = 'Use one bounded multi-board call and the corrected resume. Apply exact requested locations, a 7-day known-date gate, active-page verification, and applied/sent exclusions. Return the current run top 10 or fewer with coverage evidence; never pad the list.'
        assignee = $agentA.id
        priority = 'high'
    },
    @{
        title = 'B: Independently verify the shortlist'
        description = 'Start only after Agent A posts no more than 10 qualified IDs and exact scope. Recheck employer URLs, geography, known-date freshness, applied history, fit evidence, and gaps. Resume-Matcher is optional and requires explicit authorization.'
        assignee = $agentB.id
        priority = 'high'
    },
    @{
        title = 'C: Prepare approval-gated application packets'
        description = 'Start only for Agent B apply recommendations. Recheck applied history, prepare truthful packets, create a browser dry-run and hash-bound pending receipt, and never execute or submit without exact acceptance.'
        assignee = $agentC.id
        priority = 'medium'
    }
)

foreach ($starter in $starterIssues) {
    $existing = @($issues) | Where-Object { $_.title -eq $starter.title } | Select-Object -First 1
    if (-not $existing) {
        Invoke-PaperclipApi -Method 'POST' -Path "/companies/$($company.id)/issues" -Body @{
            title = $starter.title
            description = $starter.description
            status = 'backlog'
            priority = $starter.priority
            assigneeAgentId = $starter.assignee
            projectId = $project.id
            goalId = $goal.id
        } | Out-Null
        Write-Host "Created starter issue: $($starter.title)"
    }
    else {
        Invoke-PaperclipApi -Method 'PATCH' -Path "/issues/$($existing.id)" -Body @{
            description = $starter.description
            priority = $starter.priority
            assigneeAgentId = $starter.assignee
        } | Out-Null
        Write-Host "Updated starter issue: $($starter.title)"
    }
}

$summary = @{
    configuredAt = (Get-Date).ToUniversalTime().ToString('o')
    paperclipUrl = 'http://127.0.0.1:3100'
    company = @{ id = $company.id; name = $company.name }
    goal = @{ id = $goal.id; title = $goal.title }
    project = @{ id = $project.id; name = $project.name }
    agents = @(
        @{ id = $agentA.id; name = $agentA.name; role = 'discovery'; status = 'paused' },
        @{ id = $agentB.id; name = $agentB.name; role = 'verification'; status = 'paused' },
        @{ id = $agentC.id; name = $agentC.name; role = 'application'; status = 'paused' }
    )
    safety = @{
        agentsPausedByDefault = $true
        applicationConfirmationRequired = $true
        liveApplicationSubmitted = $false
    }
}
$summaryPath = Join-Path $script:ProjectRoot 'reports\paperclip_setup.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host ''
Write-Host 'Paperclip job-search team is configured and paused by default.'
Write-Host "Dashboard: http://127.0.0.1:3100"
Write-Host "Setup summary: $summaryPath"
