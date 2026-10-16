@echo off
title Netease Music Downloader - Build Tool

echo ============================================================
echo   Netease Music Downloader - EXE Build Tool
echo   Supports Windows 7 ~ 11, portable for USB drive
echo ============================================================
echo.

REM ---- Auto-detect Python ----
set "PYTHON_CMD="

echo [Step 1/4] Searching for Python...

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    echo   Found: python
    goto found
)

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    echo   Found: py -3
    goto found
)

if exist "C:\Python38\python.exe" (
    set "PYTHON_CMD=C:\Python38\python.exe"
    echo   Found: C:\Python38\python.exe
    goto found
)
if exist "C:\Python39\python.exe" (
    set "PYTHON_CMD=C:\Python39\python.exe"
    echo   Found: C:\Python39\python.exe
    goto found
)
if exist "C:\Python310\python.exe" (
    set "PYTHON_CMD=C:\Python310\python.exe"
    echo   Found: C:\Python310\python.exe
    goto found
)
if exist "C:\Python311\python.exe" (
    set "PYTHON_CMD=C:\Python311\python.exe"
    echo   Found: C:\Python311\python.exe
    goto found
)

echo.
echo [ERROR] Python not found!
echo.
echo Please install Python first (recommend 3.8 for Win7~Win11):
echo   Download: https://www.python.org/downloads/
echo   IMPORTANT: Check "Add Python to PATH" during install.
echo.
pause
exit /b 1

:found
echo.
%PYTHON_CMD% --version
echo.

REM ---- Install dependencies ----
echo [Step 2/4] Installing dependencies...
echo This may take 1-2 minutes, please wait...
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo Please check network connection and try again.
    echo.
    pause
    exit /b 1
)
echo   Dependencies installed.
echo.

REM ---- Build ----
echo [Step 3/4] Building EXE...
echo This takes 2-5 minutes, please be patient...
echo.
%PYTHON_CMD% build_exe.py
set "BUILD_RESULT=%errorlevel%"

echo.
echo [Step 4/4] Done.
echo.
if %BUILD_RESULT%==0 (
    echo ============================================================
    echo   Build SUCCESS! EXE is in the "dist" folder.
    echo   Copy it to a USB drive and run on any Windows PC.
    echo ============================================================
) else (
    echo [ERROR] Build failed. Error code: %BUILD_RESULT%
)

echo.
pause
