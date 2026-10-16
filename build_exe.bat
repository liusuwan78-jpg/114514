@echo off
title 网易云音乐下载器 - 打包工具

echo ============================================================
echo   网易云音乐下载器 - EXE 打包工具
echo   支持 Windows 7 ~ 11，打包后可拷入 U 盘直接使用
echo ============================================================
echo.

REM ---- 自动查找 Python ----
set "PYTHON_CMD="

echo [1/3] 正在查找 Python...

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    echo   找到: python
    goto found
)

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    echo   找到: py -3
    goto found
)

if exist "C:\Python38\python.exe" (
    set "PYTHON_CMD=C:\Python38\python.exe"
    echo   找到: C:\Python38\python.exe
    goto found
)
if exist "C:\Python39\python.exe" (
    set "PYTHON_CMD=C:\Python39\python.exe"
    echo   找到: C:\Python39\python.exe
    goto found
)
if exist "C:\Python310\python.exe" (
    set "PYTHON_CMD=C:\Python310\python.exe"
    echo   找到: C:\Python310\python.exe
    goto found
)
if exist "C:\Python311\python.exe" (
    set "PYTHON_CMD=C:\Python311\python.exe"
    echo   找到: C:\Python311\python.exe
    goto found
)

echo.
echo [错误] 未检测到 Python！
echo.
echo 请先安装 Python（推荐 3.8，可兼容 Win7~Win11）：
echo   下载地址: https://www.python.org/downloads/
echo   安装时务必勾选 "Add Python to PATH"
echo.
pause
exit /b 1

:found
echo.
%PYTHON_CMD% --version
echo.

REM ---- 安装依赖 ----
echo [2/3] 安装依赖包...
echo 可能需要 1-2 分钟，请耐心等待...
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败，请检查网络连接
    echo.
    pause
    exit /b 1
)
echo   依赖安装完成。
echo.

REM ---- 执行打包 ----
echo [3/3] 开始打包（约需 2-5 分钟，请耐心等待）...
echo.
%PYTHON_CMD% build_exe.py
set "BUILD_RESULT=%errorlevel%"

echo.
if %BUILD_RESULT%==0 (
    echo ============================================================
    echo   打包成功！exe 文件在 dist 文件夹中
    echo   可直接拷入 U 盘，在任意 Windows 电脑上运行
    echo ============================================================
) else (
    echo [错误] 打包失败，错误代码: %BUILD_RESULT%
)

echo.
pause
