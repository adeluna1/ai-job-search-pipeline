param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ($PipelineArgs.Count -eq 0) {
    throw 'Provide a pipeline command.'
}
$RuntimeName = switch ($PipelineArgs[0]) {
    'agent-a-find' { 'jobspy-runtime' }
    'agent-c-browser' { 'browser-use-runtime' }
    default { '' }
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
