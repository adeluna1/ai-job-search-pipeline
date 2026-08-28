param(
    [switch]$ProbeCodex
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_paperclip-common.ps1')

if (-not (Test-PaperclipHealth)) {
    throw 'Paperclip is not healthy at http://127.0.0.1:3100. Run scripts\start-paperclip.ps1 first.'
}

function Get-PaperclipApi {
    param([Parameter(Mandatory = $true)][string]$Path)
    $response = Invoke-RestMethod -Uri "http://127.0.0.1:3100/api$Path" -TimeoutSec 30
    if ($response -is [System.Array]) {
        foreach ($item in $response) {
            Write-Output $item
        }
        return
    }
    Write-Output $response
}

$company = @(Get-PaperclipApi -Path '/companies') |
    Where-Object { $_.name -eq 'AI Job Search Team' } |
    Select-Object -First 1
if (-not $company) {
    throw 'AI Job Search Team was not found. Run scripts\setup-paperclip.ps1 first.'
}

$expectedAgents = @(
    'Agent A - Recruiter',
    'Agent B - Verifier',
    'Agent C - Application Assistant'
)
$agents = @(Get-PaperclipApi -Path "/companies/$($company.id)/agents")
$agentChecks = @()
foreach ($name in $expectedAgents) {
    $agent = $agents | Where-Object { $_.name -eq $name } | Select-Object -First 1
    if (-not $agent) {
        throw "Missing Paperclip agent: $name"
    }
    if ($agent.status -ne 'paused') {
        throw "$name must be paused for the safe default test; found '$($agent.status)'."
    }
    if ($agent.adapterType -ne 'codex_local') {
        throw "$name must use codex_local; found '$($agent.adapterType)'."
    }
    if ($agent.adapterConfig.dangerouslyBypassApprovalsAndSandbox -ne $false) {
        throw "$name has the unsafe Codex bypass setting enabled."
    }
    $extraArgs = @($agent.adapterConfig.extraArgs)
    if (-not ($extraArgs -contains '--sandbox' -and $extraArgs -contains 'workspace-write')) {
        throw "$name is missing the workspace-write sandbox arguments."
    }
    $agentChecks += [ordered]@{
        name = $name
        id = $agent.id
        status = $agent.status
        sandbox = 'workspace-write'
        bypass = $false
    }
}

$issues = @(Get-PaperclipApi -Path "/companies/$($company.id)/issues")
$expectedIssues = @('AIJ-1', 'AIJ-2', 'AIJ-3')
$missingIssues = @($expectedIssues | Where-Object { $_ -notin $issues.identifier })
if ($missingIssues.Count -gt 0) {
    throw 'Missing starter issue(s): ' + ($missingIssues -join ', ')
}

$runs = @(Get-PaperclipApi -Path "/companies/$($company.id)/heartbeat-runs")
$adapterProbe = $null
if ($ProbeCodex) {
    $firstAgent = @($agents | Where-Object { $_.name -eq 'Agent A - Recruiter' })[0]
    if (-not $firstAgent) {
        throw 'Agent A is unavailable for the Codex adapter probe.'
    }
    $probeBody = @{ adapterConfig = $firstAgent.adapterConfig } | ConvertTo-Json -Depth 12 -Compress
    $adapterProbe = Invoke-RestMethod `
        -Method POST `
        -Uri "http://127.0.0.1:3100/api/companies/$($company.id)/adapters/codex_local/test-environment" `
        -ContentType 'application/json' `
        -Body $probeBody `
        -TimeoutSec 120
    if ($adapterProbe.status -ne 'pass') {
        throw "Codex adapter probe returned '$($adapterProbe.status)'."
    }
}

$summary = [ordered]@{
    testedAt = (Get-Date).ToUniversalTime().ToString('o')
    paperclipUrl = 'http://127.0.0.1:3100'
    company = @{ id = $company.id; name = $company.name }
    agents = $agentChecks
    starterIssues = @($issues | Where-Object { $_.identifier -in $expectedIssues } | ForEach-Object {
        @{ identifier = $_.identifier; status = $_.status; assigneeAgentId = $_.assigneeAgentId }
    })
    heartbeatRunCount = $runs.Count
    codexAdapterProbe = if ($adapterProbe) {
        @{
            status = $adapterProbe.status
            checks = @($adapterProbe.checks | ForEach-Object { @{ code = $_.code; level = $_.level } })
        }
    } else {
        @{ status = 'not_requested' }
    }
}

$output = Join-Path $script:ProjectRoot 'reports\paperclip_validation.json'
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $output -Encoding UTF8
Write-Host "Paperclip validation passed: $($agentChecks.Count) paused agents, $($expectedIssues.Count) starter issues, $($runs.Count) heartbeat run(s)."
Write-Host "Validation report: $output"
