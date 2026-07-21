. (Join-Path $PSScriptRoot '_paperclip-common.ps1')

Push-Location $script:ProjectRoot
try {
    Invoke-Paperclip -CommandArgs @('run')
}
finally {
    Pop-Location
}
