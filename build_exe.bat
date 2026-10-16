@echo off
chcp 65001 >nul
echo ============================================
echo   网易云音乐下载器 - EXE 打包脚本 (Windows)
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+ 并加入 PATH
    pause
    exit /b 1
)

REM 安装依赖
echo [1/2] 安装依赖包...
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM 执行打包
echo.
echo [2/2] 开始打包...
python build_exe.py

echo.
pause
