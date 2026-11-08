@echo off
setlocal
pushd "%~dp0"
if exist ".runtime\Scripts\python.exe" goto install
py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 (
  set "CC_PY=py -3"
  goto setup
)
python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>&1
if not errorlevel 1 (
  set "CC_PY=python"
  goto setup
)
echo Install Python 3.10 or later, then reopen Start-CiteCargo.cmd.
start "" "https://www.python.org/downloads/"
pause
popd
exit /b 1
:setup
echo Preparing CiteCargo. This only needs to run once.
%CC_PY% -m venv ".runtime"
if errorlevel 1 goto failed
:install
".runtime\Scripts\python.exe" -m pip install --no-index --find-links "app" "paper-tool==1.2.0" >".runtime\setup.log" 2>&1
if errorlevel 1 goto failed
echo CiteCargo is opening in your browser. Keep this window open while working.
".runtime\Scripts\python.exe" -m paper_tool ui %*
if errorlevel 1 goto failed
popd
exit /b 0
:failed
echo CiteCargo could not start. Check Python or the local setup log in .runtime.
pause
popd
exit /b 1
