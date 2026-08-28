param(
    [switch]$JobSpy,
    [switch]$BrowserUse,
    [switch]$All
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $JobSpy -and -not $BrowserUse -and -not $All) {
    throw 'Choose -JobSpy, -BrowserUse, or -All. Install JobSpy first to follow the staged rollout.'
}

$BootstrapPython = $env:JOB_PIPELINE_PYTHON
if (-not $BootstrapPython) {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $BootstrapPython = 'python'
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $BootstrapPython = 'py'
    }
    else {
        throw 'Python was not found. Set JOB_PIPELINE_PYTHON (3.10+ core; 3.11+ for browser-use).'
    }
}

function Install-AgentRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeName,
        [Parameter(Mandatory = $true)][string]$Package,
        [Parameter(Mandatory = $true)][string]$ImportCode,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )
    $RuntimeRoot = Join-Path $ProjectRoot "tools\$RuntimeName"
    $VenvPython = Join-Path $RuntimeRoot 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        & $BootstrapPython -m venv $RuntimeRoot
        if ($LASTEXITCODE -ne 0) { throw "Could not create $DisplayName runtime." }
    }
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Could not update pip in the $DisplayName runtime." }
    & $VenvPython -m pip install $Package
    if ($LASTEXITCODE -ne 0) { throw "$DisplayName installation failed." }
    & $VenvPython -c $ImportCode
    if ($LASTEXITCODE -ne 0) { throw "$DisplayName import validation failed." }
    Write-Host "$DisplayName runtime ready: $RuntimeRoot"
}

if ($JobSpy -or $All) {
    Install-AgentRuntime `
        -RuntimeName 'jobspy-runtime' `
        -Package 'python-jobspy==1.1.82' `
        -ImportCode 'from jobspy import scrape_jobs' `
        -DisplayName 'JobSpy'
}

if ($BrowserUse -or $All) {
    $BrowserPythonSupported = & $BootstrapPython -c 'import sys; print(int(sys.version_info >= (3, 11)))'
    if ($BrowserPythonSupported -ne '1') {
        throw 'browser-use requires Python 3.11 or newer.'
    }
    Install-AgentRuntime `
        -RuntimeName 'browser-use-runtime' `
        -Package 'browser-use[core]==0.13.8' `
        -ImportCode 'from browser_use import Agent, BrowserProfile' `
        -DisplayName 'browser-use'
}

Write-Host 'Optional runtimes are isolated because JobSpy and browser-use require incompatible markdownify versions.'
Write-Host 'Use scripts\agent-run.cmd; it selects the runtime from the command name.'
