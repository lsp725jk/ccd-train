@echo off
chcp 936 >nul
REM ============================================
REM  Label Studio 标注服务 - 启动脚本
REM  前置：install_labelstudio.bat 完成安装
REM  端口 8081（ccd-train 后端 8000 不受影响）
REM  Token: dsh-ccd-token（与 sync_ls.py 一致）
REM ============================================
cd /d %~dp0

if not exist .venv (
    echo [错误] 未找到 .venv，请先运行 install_labelstudio.bat
    pause
    exit /b 1
)

set "TMP=%~dp0.tmp"
set "TEMP=%~dp0.tmp"
set "LABEL_STUDIO_BASE_DATA_DIR=%~dp0data"
set "LABEL_STUDIO_USERNAME=admin"
set "LABEL_STUDIO_PASSWORD=admin123"
set "LABEL_STUDIO_USER_TOKEN=dsh-ccd-token"

echo 启动 Label Studio 标注服务...
echo 地址: http://localhost:8081
echo 账号: admin / admin123    按 Ctrl+C 停止
echo.

.venv\Scripts\label-studio.exe start --port 8081 --no-browser
