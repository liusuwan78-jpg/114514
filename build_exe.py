#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本：将 netease_music_downloader.py 打包为单文件可执行程序

使用方法:
    Windows: python build_exe.py
    生成的 exe 在 dist/ 目录下

注意:
    - Windows 下生成 netease_music_downloader.exe
    - 生成的 exe 自带 Python 运行时，用户无需安装 Python
    - 但 ffmpeg 仍需用户自行安装并加入系统 PATH（用于音频转码）
"""

import os
import shutil
import subprocess
import sys


def main():
    script = "netease_music_downloader.py"
    if not os.path.exists(script):
        print(f"[错误] 找不到 {script}，请确保在脚本所在目录运行")
        sys.exit(1)

    print("=" * 50)
    print("  网易云音乐下载器 - EXE 打包")
    print("=" * 50)

    # 清理旧的构建产物
    for d in ("build", "dist", "__pycache__"):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",               # 打包成单个 exe
        "--console",               # 控制台程序（保留命令行输出）
        "--clean",                 # 清理缓存
        "--name", "netease_music_downloader",
        "--hidden-import", "Crypto.Cipher.AES",
        "--hidden-import", "mutagen.id3",
        "--hidden-import", "mutagen.mp3",
        script,
    ]

    print(f"\n执行: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("\n[错误] 打包失败")
        sys.exit(1)

    exe_name = "netease_music_downloader"
    if os.name == "nt":
        exe_name += ".exe"
    exe_path = os.path.join("dist", exe_name)

    if os.path.exists(exe_path):
        size = os.path.getsize(exe_path) / 1024 / 1024
        print(f"\n{'=' * 50}")
        print(f"  ✅ 打包成功!")
        print(f"  文件: {exe_path}")
        print(f"  大小: {size:.1f} MB")
        print(f"{'=' * 50}")
        print(f"\n使用示例:")
        print(f"  {exe_name} --help")
        print(f"  {exe_name} 259138 -o ./音乐")
        print(f"  {exe_name} --artist 周杰伦")
        print(f"  {exe_name} --playlist 123456789")
        print(f"  {exe_name} --daily --cookie 'MUSIC_U=xxx'")
    else:
        print("\n[错误] 未找到生成的可执行文件")
        sys.exit(1)


if __name__ == "__main__":
    main()
