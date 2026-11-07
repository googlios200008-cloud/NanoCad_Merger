# Сборка EXE на Windows. Основная логика вынесена в build_exe.py для PyCharm.
# Пример: powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 --onefile
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
& $python .\build_exe.py @args
exit $LASTEXITCODE
