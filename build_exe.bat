@echo off
chcp 65001 >nul 2>&1
title 网易云音乐下载器 - 打包工具

echo ============================================================
echo   网易云音乐下载器 - EXE 打包工具
echo   支持 Windows 7 ~ 11，打包后可拷入 U 盘直接使用
echo ============================================================
echo.

REM ---- 自动查找 Python ----
set "PYTHON_CMD="

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    goto :found
)

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    goto :found
)

REM 尝试常见安装路径
if exist "C:\Python38\python.exe" set "PYTHON_CMD=C:\Python38\python.exe"
if exist "C:\Python39\python.exe" set "PYTHON_CMD=C:\Python39\python.exe"
if exist "C:\Python310\python.exe" set "PYTHON_CMD=C:\Python310\python.exe"
if exist "C:\Python311\python.exe" set "PYTHON_CMD=C:\Python311\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

if "%PYTHON_CMD%"=="" (
    echo.
    echo [错误] 未检测到 Python！
    echo.
    echo 请先安装 Python（推荐 3.8，可兼容 Win7~Win11）：
    echo   下载地址: https://www.python.org/downloads/
    echo   安装时务必勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)

:found
echo [1/3] 检测到 Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM ---- 安装依赖 ----
echo [2/3] 安装依赖包...
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败，请检查网络连接
    echo.
    pause
    exit /b 1
)
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
