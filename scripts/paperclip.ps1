param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PaperclipArgs
)

. (Join-Path $PSScriptRoot '_paperclip-common.ps1')
Invoke-Paperclip -CommandArgs $PaperclipArgs
