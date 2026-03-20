@echo off
setlocal

set SCRIPT_DIR=%~dp0
powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%pack.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

endlocal & exit /b %EXIT_CODE%
