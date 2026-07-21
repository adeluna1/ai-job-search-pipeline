@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0agent-run.ps1" %*
exit /b %ERRORLEVEL%
