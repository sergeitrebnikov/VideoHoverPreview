@echo off
cd /d "%~dp0"
set "APP_ROOT=%~dp0"
powershell -WindowStyle Hidden -NoProfile -Command "Get-Process pythonw,python,ffmpeg,ffplay -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($env:APP_ROOT) } | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
wscript.exe //nologo "%~dp0run.vbs"
