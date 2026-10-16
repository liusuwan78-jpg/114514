@echo off
title Netease Music Downloader - Build Tool

echo ============================================================
echo   Netease Music Downloader - EXE Build Tool
echo   Supports Windows 7 ~ 11, portable for USB drive
echo ============================================================
echo.

REM ---- Auto-detect Python ----
set "PYTHON_CMD="

where python >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
    goto found
)

where py >nul 2>&1
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
    goto found
)

REM Try common install paths
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
    echo [ERROR] Python not found!
    echo.
    echo Please install Python first (recommend 3.8 for Win7~Win11):
    echo   Download: https://www.python.org/downloads/
    echo   IMPORTANT: Check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

:found
echo [1/3] Python detected: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

REM ---- Install dependencies ----
echo [2/3] Installing dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to install dependencies. Please check your network.
    echo.
    pause
    exit /b 1
)
echo.

REM ---- Build ----
echo [3/3] Building EXE (takes 2-5 minutes, please wait)...
echo.
%PYTHON_CMD% build_exe.py
set "BUILD_RESULT=%errorlevel%"

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
