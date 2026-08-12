$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_paperclip-common.ps1')

if (-not (Test-PaperclipHealth)) {
    throw 'Paperclip is not healthy at http://127.0.0.1:3100. Run scripts\start-paperclip.ps1 first.'
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
        $params.Body = $Body | ConvertTo-Json -Depth 8 -Compress
    }
    $response = Invoke-RestMethod @params
    if ($response -is [System.Array]) {
        foreach ($item in $response) {
            Write-Output $item
        }
        return
    }
    Write-Output $response
}

$company = @(Invoke-PaperclipApi -Method GET -Path '/companies') |
    Where-Object { $_.name -eq 'AI Job Search Team' } |
    Select-Object -First 1
if (-not $company) {
    throw 'AI Job Search Team was not found. Run scripts\setup-paperclip.ps1 first.'
}

$agents = @(Invoke-PaperclipApi -Method GET -Path "/companies/$($company.id)/agents")
$desired = [ordered]@{
    'Agent A - Recruiter' = 'active'
    'Agent B - Verifier' = 'active'
    'Agent C - Application Assistant' = 'paused'
}
$results = @()

foreach ($entry in $desired.GetEnumerator()) {
    $targetName = [string]$entry.Key
    $targetState = [string]$entry.Value
    $agent = @($agents | Where-Object { $_.name -eq $targetName })[0]
    if (-not $agent) {
        throw "Missing Paperclip agent: $targetName"
    }
    $agentId = [string]$agent.id
    $parsedId = [guid]::Empty
    if (-not [guid]::TryParse($agentId, [ref]$parsedId)) {
        throw "Paperclip returned an invalid agent ID for $targetName`: '$agentId'"
    }
    $action = if ($targetState -eq 'active') { 'resume' } else { 'pause' }
    $updated = Invoke-PaperclipApi -Method POST -Path "/agents/$agentId/$action" -Body @{}
    $results += [ordered]@{
        id = $updated.id
        name = $updated.name
        status = $updated.status
        operationalRole = $updated.metadata.pipelineRole
    }
}

$summary = [ordered]@{
    activatedAt = (Get-Date).ToUniversalTime().ToString('o')
    paperclipUrl = 'http://127.0.0.1:3100'
    company = @{ id = $company.id; name = $company.name }
    agents = $results
    safety = @{
        agentCApprovalGate = 'paused_until_agent_b_apply_recommendation_and_user_confirmation'
        liveApplicationSubmitted = $false
    }
}
$output = Join-Path $script:ProjectRoot 'reports\paperclip_active_status.json'
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $output -Encoding UTF8

Write-Host 'Paperclip operational state updated:'
foreach ($result in $results) {
    Write-Host "  $($result.name): $($result.status)"
}
Write-Host "Status report: $output"
