param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Windows CMD/PowerShell 5.1 can split a quoted OR query into several native
# arguments. Reassemble only the value following --query, stopping at the next
# option, then restore phrase quotes for simple title lists.
$RepairedArgs = [System.Collections.Generic.List[string]]::new()
for ($index = 0; $index -lt $PipelineArgs.Count; $index++) {
    $argument = $PipelineArgs[$index]
    $RepairedArgs.Add($argument)
    if ($argument -ne '--query') {
        continue
    }
    $queryParts = [System.Collections.Generic.List[string]]::new()
    while (
        $index + 1 -lt $PipelineArgs.Count -and
        -not $PipelineArgs[$index + 1].StartsWith('--')
    ) {
        $index++
        $queryParts.Add($PipelineArgs[$index])
    }
    $query = ($queryParts -join ' ').Trim()
    if (-not $query) {
        throw '--query requires a value.'
    }
    if ($query -notmatch '"' -and $query -match '(?i)\s+OR\s+') {
        $phrases = @([regex]::Split($query, '(?i)\s+OR\s+'))
        if (@($phrases | Where-Object { $_ -notmatch '^[A-Za-z0-9&+/. -]+$' }).Count -eq 0) {
            $query = ($phrases | ForEach-Object { '"' + $_.Trim() + '"' }) -join ' OR '
        }
    }
    $RepairedArgs.Add($query)
}
$PipelineArgs = $RepairedArgs.ToArray()

if ($PipelineArgs.Count -eq 0) {
    throw 'Provide a pipeline command.'
}

if (
    $PipelineArgs[0] -eq 'agent-a-find' -and
    $PipelineArgs -notcontains '--no-agent-web-browser'
) {
    & (Join-Path $ProjectRoot 'scripts\start-agent-web-browser.ps1')
}

$RuntimeName = switch ($PipelineArgs[0]) {
    'agent-a-find' { 'jobspy-runtime' }
    'agent-c-browser' { 'browser-use-runtime' }
    default { '' }
}
if ($PipelineArgs -contains '--help') {
    $RuntimeName = ''
}
if (-not $RuntimeName) {
    & (Join-Path $ProjectRoot 'run.ps1') @PipelineArgs
    exit $LASTEXITCODE
}
$VenvPython = Join-Path $ProjectRoot "tools\$RuntimeName\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Optional runtime $RuntimeName is missing. Run scripts\install-agent-integrations.ps1 first."
}
$PreviousPython = $env:JOB_PIPELINE_PYTHON
try {
    $env:JOB_PIPELINE_PYTHON = $VenvPython
    & (Join-Path $ProjectRoot 'run.ps1') @PipelineArgs
    exit $LASTEXITCODE
}
finally {
    $env:JOB_PIPELINE_PYTHON = $PreviousPython
}
