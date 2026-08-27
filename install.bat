@echo off
chcp 936 >nul
REM ============================================
REM  CCD Train 平台 - 环境安装（首次部署运行）
REM  需要：Python 3.10+ 已安装并加入 PATH
REM ============================================
cd /d %~dp0

echo [1/3] 创建虚拟环境...
if not exist backend\.venv (
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败，请确认 Python 已安装且版本 >= 3.10
        pause
        exit /b 1
    )
)

echo [2/3] 安装 PyTorch CUDA 版（约 2.5GB，需几分钟）...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip -q
backend\.venv\Scripts\python.exe -m pip install torch==2.13.0+cu126 torchvision==0.28.0+cu126 --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 (
    echo [提示] 官方源下载失败，尝试镜像源（阿里云）...
    backend\.venv\Scripts\python.exe -m pip install torch==2.13.0+cu126 torchvision==0.28.0+cu126 --index-url https://mirrors.aliyun.com/pytorch-wheels/cu126/
    if errorlevel 1 (
        echo [错误] torch 安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

echo [3/3] 安装平台依赖（清华源）...
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo  安装完成！运行 start.bat 启动平台
echo ============================================
pause