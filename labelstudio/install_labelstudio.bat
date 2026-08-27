@echo off
chcp 936 >nul
REM ============================================
REM  Label Studio 标注服务 - 首次安装
REM  使用独立 venv（Python 3.12），不影响 ccd-train 后端环境
REM ============================================
cd /d %~dp0

set "TMP=%~dp0.tmp"
set "TEMP=%~dp0.tmp"
set "UV_CACHE_DIR=%~dp0.uv-cache"

where uv >nul 2>nul
if %errorlevel%==0 (
    echo [1/2] 使用 uv 创建独立环境并安装 label-studio（清华镜像）...
    uv venv .venv --python 3.12
    uv pip install --python .venv\Scripts\python.exe label-studio --index-url https://pypi.tuna.tsinghua.edu.cn/simple
    goto :run_fix
)

echo [1/2] 未找到 uv，改用 py -3.12 创建环境（如失败请安装 uv：pip install uv）
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install label-studio -i https://pypi.tuna.tsinghua.edu.cn/simple

:run_fix
echo [2/2] 首次启动初始化数据库...
.venv\Scripts\label-studio.exe start --port 8081 --no-browser --username admin --password admin123 --user-token dsh-ccd-token
echo.
echo 若启动成功，请运行 fix_legacy_token.py 启用 API Token 后重启服务。
pause
