@echo off
cd /d "%~dp0.."
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run scripts\install_windows.bat first.
  pause
  exit /b 1
)
start "NanoMerger" ".venv\Scripts\pythonw.exe" -m nanomerger.desktop_entry %*
