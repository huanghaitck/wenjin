@echo off
setlocal
set "WEBVIEW=%~dp0MicrosoftEdgeWebView2RuntimeInstallerX64.exe"

reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv >nul 2>&1
if errorlevel 1 reg query "HKCU\Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" /v pv >nul 2>&1
if errorlevel 1 (
  if not exist "%WEBVIEW%" (
    echo WebView2 offline installer is missing.
    exit /b 2
  )
  "%WEBVIEW%" /silent /install
  if errorlevel 1 exit /b 3
)

for %%F in ("%~dp0wenjin-0.1.3-x64-setup.exe") do (
  start "" /wait "%%~fF"
  exit /b %errorlevel%
)

echo Wenjin installer is missing.
exit /b 4
