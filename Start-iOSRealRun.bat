@echo off
setlocal
if "%~1"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-iOSRealRun.ps1" -PauseOnError
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-iOSRealRun.ps1" %*
)
exit /b %errorlevel%
