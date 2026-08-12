@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0code-review-graph.ps1" %*
exit /b %ERRORLEVEL%
