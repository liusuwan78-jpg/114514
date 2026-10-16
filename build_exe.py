#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键打包脚本：将 netease_music_downloader.py + ffmpeg 打包为单个可执行文件
打包后的 exe 自带 ffmpeg，用户无需安装任何依赖即可直接使用。

Windows:  python build_exe.py   ->  dist/netease_music_downloader.exe
Linux  :  python build_exe.py   ->  dist/netease_music_downloader
"""

import os
import shutil
import subprocess
import sys
import zipfile
import urllib.request


FFMPEG_URL_WINDOWS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)


def download_file(url: str, dest: str) -> bool:
    print(f"  下载: {url}")
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  下载失败: {e}")
        return False


def get_ffmpeg_windows() -> str | None:
    """下载 Windows 版 ffmpeg.exe，返回本地路径"""
    dest = "ffmpeg.exe"
    if os.path.exists(dest):
        print(f"  已存在 ffmpeg.exe，跳过下载")
        return dest

    zip_path = "ffmpeg.zip"
    print("[准备] 下载 Windows 版 ffmpeg...")
    if not download_file(FFMPEG_URL_WINDOWS, zip_path):
        return None

    print("[准备] 解压 ffmpeg...")
    try:
        with zipfile.ZipFile(zip_path) as z:
            # 在压缩包中找到 ffmpeg.exe
            ffmpeg_member = None
            for name in z.namelist():
                if name.endswith("bin/ffmpeg.exe"):
                    ffmpeg_member = name
                    break
            if not ffmpeg_member:
                print("  压缩包中未找到 ffmpeg.exe")
                return None
            with z.open(ffmpeg_member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        os.remove(zip_path)
        print(f"  ffmpeg.exe 就绪 ({os.path.getsize(dest)/1024/1024:.1f} MB)")
        return dest
    except Exception as e:
        print(f"  解压失败: {e}")
        return None


def get_ffmpeg_linux() -> str | None:
    """Linux: 优先使用系统 ffmpeg，否则尝试下载静态版本"""
    dest = "ffmpeg"
    if os.path.exists(dest):
        return dest
    # 尝试复制系统 ffmpeg
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        shutil.copy2(sys_ffmpeg, dest)
        os.chmod(dest, 0o755)
        print(f"  使用系统 ffmpeg: {sys_ffmpeg}")
        return dest
    print("  未找到系统 ffmpeg，请先安装 ffmpeg")
    return None


def main():
    script = "netease_music_downloader.py"
    if not os.path.exists(script):
        print(f"[错误] 找不到 {script}")
        sys.exit(1)

    print("=" * 56)
    print("  网易云音乐下载器 - 单文件打包 (含 ffmpeg)")
    print("=" * 56)

    # 1. 获取 ffmpeg
    print("\n[1/3] 准备 ffmpeg...")
    if os.name == "nt":
        ffmpeg = get_ffmpeg_windows()
        ffmpeg_name = "ffmpeg.exe"
    else:
        ffmpeg = get_ffmpeg_linux()
        ffmpeg_name = "ffmpeg"

    if not ffmpeg or not os.path.exists(ffmpeg):
        print("[错误] ffmpeg 准备失败，无法打包")
        sys.exit(1)

    # 2. 清理旧产物
    print("\n[2/3] 清理旧的构建产物...")
    for d in ("build", "dist", "__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)

    # 3. PyInstaller 打包
    print("\n[3/3] PyInstaller 打包中...")
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--clean",
        "--name", "netease_music_downloader",
        "--add-binary", f"{ffmpeg}{sep}.",
        "--hidden-import", "Crypto.Cipher.AES",
        "--hidden-import", "mutagen.id3",
        "--hidden-import", "mutagen.mp3",
        script,
    ]
    print(f"  命令: {' '.join(cmd)}\n")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("\n[错误] 打包失败")
        sys.exit(1)

    exe_name = "netease_music_downloader" + (".exe" if os.name == "nt" else "")
    exe_path = os.path.join("dist", exe_name)

    if os.path.exists(exe_path):
        size = os.path.getsize(exe_path) / 1024 / 1024
        print(f"\n{'=' * 56}")
        print(f"  ✅ 打包成功！单文件，自带 ffmpeg，零依赖")
        print(f"  文件: {exe_path}")
        print(f"  大小: {size:.1f} MB")
        print(f"{'=' * 56}")
        print(f"\n直接使用示例:")
        print(f"  {exe_name} --help")
        print(f"  {exe_name} 259138 -o ./音乐")
        print(f"  {exe_name} --artist 周杰伦")
        print(f"  {exe_name} --playlist 123456789")
        print(f"  {exe_name} --daily --cookie \"MUSIC_U=你的cookie\"")
    else:
        print("\n[错误] 未找到生成的可执行文件")
        sys.exit(1)


if __name__ == "__main__":
    main()
