[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArguments
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $repoRoot "tools\code-review-graph-runtime\Scripts\code-review-graph.exe"

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw @"
Code Review Graph is not installed in the isolated project runtime.
Create tools\code-review-graph-runtime and install code-review-graph==2.3.7 there.
See docs\CODE_REVIEW_GRAPH.md for the complete setup command.
"@
}

if (-not $CommandArguments -or $CommandArguments.Count -eq 0) {
    throw "Pass a command such as build, update, status, detect-changes, or visualize."
}

$env:PYTHONUTF8 = "1"
& $executable @CommandArguments --repo $repoRoot
exit $LASTEXITCODE
