@echo off
setlocal
chcp 65001 >nul
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "BATCH=%~1"
if "%BATCH%"=="" set "BATCH=downloads"
:refresh
cls
call "%PY%" "%~dp0paper_tool.py" progress --out "%BATCH%"
echo.
echo Usage: progress.cmd [batch folder] ^(default: downloads^) - Ctrl+C to stop.
timeout /t 10 /nobreak >nul
goto refresh
