# -*- coding: utf-8 -*-
"""生成 GBK 编码的双击启动器「export.cmd」。

中文 Windows 的 cmd 按 ANSI(GBK) 逐字节读 .cmd/.bat，写成 UTF-8 会把中文
拆成非法 GBK 序列导致整份脚本解析错乱（连纯 ASCII 行都跟着崩）。
所以：改文案请改下面的 CMD 字符串，再运行本生成器；不要直接改 .cmd。
禁止使用非 GB2312 字符（如箭头、对勾、Emoji）。
"""
from pathlib import Path

CMD = r'''@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0..\.."
set "PYTHONIOENCODING=gbk:replace"
set "PY=%~dp0..\..\.venv\Scripts\python.exe"
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
if not defined GROUP if exist "%~dp0..\..\课题组.txt" set /p GROUP=< "%~dp0..\..\课题组.txt"
echo.
echo 批次目录: !OUT!
echo 正在生成 Excel 台账与完成情况汇报 ...
echo.
if defined GROUP (
  "%PY%" -m paper_tool.reports both --out "!OUT!" --group "!GROUP!"
) else (
  "%PY%" -m paper_tool.reports both --out "!OUT!"
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
'''

target = Path(__file__).resolve().parent / 'export.cmd'
target.write_text(CMD, encoding='gbk', newline='\r\n')
print(f'[OK] 已生成 {target.name} ({target.stat().st_size} bytes, GBK)')
