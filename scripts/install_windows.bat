@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 goto :fail
call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\python.exe -m pip install -e ".[gui]"
if errorlevel 1 goto :fail
echo.
echo NanoMerger installed. Start with: .venv\Scripts\nanomerger-gui.exe
echo Install ODA File Converter separately and select its executable in NanoMerger.
pause
exit /b 0
:fail
echo Installation failed. Check Python 3.10+ and network access to pypi.org.
pause
exit /b 1
