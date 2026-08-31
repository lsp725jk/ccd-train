@echo off
chcp 936 >nul
REM ============================================
REM  CCD Train 一键打包: 前端构建 + PyInstaller + Inno Setup 安装包
REM  前置: frontend\node_modules、backend\.venv、Inno Setup 6
REM ============================================
cd /d %~dp0
setlocal enabledelayedexpansion

set /p VER=<VERSION
if "%VER%"=="" ( echo [错误] 未找到 VERSION 文件 & pause & exit /b 1 )
echo 打包版本: %VER%

echo [1/3] 构建前端...
pushd ..\..\frontend
call npm run build
if errorlevel 1 ( echo [错误] 前端构建失败 & popd & pause & exit /b 1 )
popd

echo [2/3] PyInstaller 打包 (耗时较长, 请耐心等待)...
if exist ..\dist\CCDTrain ( rmdir /s /q ..\dist\CCDTrain )
..\.venv\Scripts\pyinstaller.exe ccd_train.spec --noconfirm --distpath ..\dist --workpath ..\build
if errorlevel 1 ( echo [错误] PyInstaller 打包失败 & pause & exit /b 1 )
REM 配套标注工具 (spec datas 收集异常的兜底, 直接放入打包目录)
if exist ..\tools\X-AnyLabeling-CPU.exe ( copy /y ..\tools\X-AnyLabeling-CPU.exe ..\dist\CCDTrain\ >nul )

echo [3/3] Inno Setup 生成安装包 (版本 %VER%)...
where ISCC >nul 2>nul
if %errorlevel%==0 ( set ISCC_CMD=ISCC.exe ) else ( set ISCC_CMD=C:\Program Files ^(x86^)\Inno Setup 6\ISCC.exe )
%ISCC_CMD% installer.iss /DMyAppVersion=%VER%
if errorlevel 1 ( echo [错误] ISCC 失败, 请确认 Inno Setup 6 已安装 & pause & exit /b 1 )

echo ============================================
echo  完成! 安装包: ..\dist_installer\CCDTrain-Setup-%VER%.exe
echo ============================================
pause
