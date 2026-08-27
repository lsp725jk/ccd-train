@echo off
REM ============================================
REM  CCD Train - Desktop mode (PySide6 shell)
REM  Requires: backend\.venv with PySide6 installed
REM ============================================
cd /d %~dp0

if exist backend\.venv\Lib\site-packages\PySide6 goto run
echo [INFO] PySide6 not found, installing from tsinghua mirror...
backend\.venv\Scripts\python.exe -m pip install PySide6 -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60

:run
echo Starting CCD Train desktop...
echo Close the window to stop the service.
backend\.venv\Scripts\python.exe desktop\qt_main.py
pause
