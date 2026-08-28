param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PipelineArgs
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PreviousDontWriteBytecode = $env:PYTHONDONTWRITEBYTECODE
$env:PYTHONDONTWRITEBYTECODE = '1'
Push-Location $ProjectRoot
try {
    $PythonCommand = $env:JOB_PIPELINE_PYTHON
    if (-not $PythonCommand) {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $PythonCommand = 'python'
        }
        elseif (Get-Command py -ErrorAction SilentlyContinue) {
            $PythonCommand = 'py'
        }
        else {
            throw 'Python 3.10+ was not found. Install Python or set JOB_PIPELINE_PYTHON.'
        }
    }

    if ($PipelineArgs.Count -gt 0 -and $PipelineArgs[0] -eq 'test') {
        & $PythonCommand -m unittest discover -s tests -v
    }
    else {
        & $PythonCommand -m job_pipeline @PipelineArgs
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    $env:PYTHONDONTWRITEBYTECODE = $PreviousDontWriteBytecode
}
