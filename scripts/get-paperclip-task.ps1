$ErrorActionPreference = 'Stop'

$apiUrl = $env:PAPERCLIP_API_URL
$taskId = $env:PAPERCLIP_TASK_ID
$apiKey = $env:PAPERCLIP_API_KEY

if (-not $apiUrl -or -not $taskId -or -not $apiKey) {
    throw 'PAPERCLIP_API_URL, PAPERCLIP_TASK_ID, and PAPERCLIP_API_KEY are required.'
}

$headers = @{ Authorization = "Bearer $apiKey" }
$issue = Invoke-RestMethod -Uri "$apiUrl/api/issues/$taskId" -Headers $headers -TimeoutSec 30

[ordered]@{
    id = $issue.id
    identifier = $issue.identifier
    title = $issue.title
    description = $issue.description
    status = $issue.status
    priority = $issue.priority
    projectId = $issue.projectId
    goalId = $issue.goalId
} | ConvertTo-Json -Depth 4
