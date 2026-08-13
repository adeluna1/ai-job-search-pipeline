@echo off
rem agent-run.ps1 repairs quoted OR queries split by legacy CMD/PowerShell forwarding.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agent-run.ps1" %*
exit /b %ERRORLEVEL%
