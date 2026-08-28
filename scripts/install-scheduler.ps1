[CmdletBinding()]
param(
    [ValidateSet('Install', 'Uninstall', 'Status')]
    [string]$Action = 'Install',
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DataRoot = (Join-Path $env:APPDATA 'expedient-employment\control'),
    [ValidateRange(5, 1440)]
    [int]$WakeMinutes = 15
)

$ErrorActionPreference = 'Stop'
$taskName = 'Expedient Employment Scheduled Hunt'

if ($Action -eq 'Uninstall') {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output 'Removed the Expedient Employment scheduled wake.'
    } else {
        Write-Output 'The Expedient Employment scheduled wake is not installed.'
    }
    exit 0
}

if ($Action -eq 'Status') {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Output "Installed: $($existing.State)"
        exit 0
    }
    Write-Output 'Not installed.'
    exit 1
}

$resolvedProject = (Resolve-Path -LiteralPath $ProjectRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedProject 'job_pipeline\scheduler_cli.py'))) {
    throw 'Project root does not contain the scheduler wake module.'
}
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
$resolvedData = (Resolve-Path -LiteralPath $DataRoot).Path

$pythonCommand = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
}
if (-not $pythonCommand) {
    throw 'Python was not found on PATH.'
}

$arguments = @(
    '-B', '-m', 'job_pipeline.scheduler_cli',
    'run-due',
    '--project-root', ('"{0}"' -f $resolvedProject),
    '--data-root', ('"{0}"' -f $resolvedData),
    '--limit', '10'
) -join ' '
$taskAction = New-ScheduledTaskAction `
    -Execute $pythonCommand.Source `
    -Argument $arguments `
    -WorkingDirectory $resolvedProject
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $WakeMinutes)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -Hidden
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Description 'Wakes Expedient Employment to run due local job discovery, scoring, and draft workflows. No employer submission authority.' `
    -Action $taskAction `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Output "Installed the Expedient Employment scheduled wake every $WakeMinutes minute(s)."
