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

start "" http://localhost:8000
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000