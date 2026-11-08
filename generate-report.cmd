@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONIOENCODING=gbk:replace"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
if not "%~1"=="" goto havearg
set "OUT="
set /p "OUT=请输入批次目录(可直接把文件夹拖到本窗口后回车): "
if not defined OUT goto noarg
goto run
:havearg
set "OUT=%~1"
goto run
:noarg
echo [X] 未输入目录，已取消。
goto end
:run
set "OUT=!OUT:"=!"
set "GROUP="
if not "%~2"=="" set "GROUP=%~2"
if not defined GROUP if exist "%~dp0课题组.txt" set /p GROUP=< "%~dp0课题组.txt"
echo.
echo 批次目录: !OUT!
echo 正在生成 Excel 台账与完成情况汇报 ...
echo.
if defined GROUP (
  "%PY%" "%~dp0deliverables.py" both --out "!OUT!" --group "!GROUP!"
) else (
  "%PY%" "%~dp0deliverables.py" both --out "!OUT!"
)
if errorlevel 1 goto failed
echo.
echo [OK] 完成，文件已写入批次目录:
echo     文献清单.xlsx
echo     完成情况汇报.md
goto end
:failed
echo.
echo [X] 生成失败，请看上面的错误信息。
:end
echo.
pause
