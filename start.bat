@echo off
chcp 936 >nul
REM ============================================
REM  CCD Train 平台 - 一键启动
REM  前置：已运行 install.bat 完成环境安装
REM ============================================
cd /d %~dp0

if not exist backend\.venv (
    echo [错误] 未找到 backend\.venv，请先运行 install.bat
    pause
    exit /b 1
)

echo 启动 CCD Train 平台...
echo 地址: http://localhost:8000 （浏览器将自动打开）
echo 按 Ctrl+C 停止服务
echo.

REM 浏览器在服务启动后自动打开（由后端就绪探测触发，避免先开失败页）
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000