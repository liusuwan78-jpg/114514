#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键打包脚本：将 netease_music_downloader.py + ffmpeg 打包为单个可执行文件
打包后的 exe 自带 ffmpeg，用户无需安装任何依赖即可直接使用。

Windows:  python build_exe.py   ->  dist/netease_music_downloader.exe
Linux  :  python build_exe.py   ->  dist/netease_music_downloader
macOS  :  python build_exe.py   ->  dist/netease_music_downloader
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


def log(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print(f"\n[错误] {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ============ 彻底清理 ============
def clean_all():
    log("[清理] 删除旧的构建产物...")
    for d in ("build", "dist", "__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    for root, dirs, files in os.walk("."):
        for f in files:
            if f.endswith(".spec"):
                os.remove(os.path.join(root, f))
        dirs[:] = [d for d in dirs if d not in ("build", "dist", "__pycache__")]
    log("  已清理")


# ============ ffmpeg 准备 ============
def download_file(url: str, dest: str) -> bool:
    log(f"  下载: {url}")
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        log(f"  下载失败: {e}")
        return False


def get_ffmpeg_windows() -> str | None:
    dest = "ffmpeg.exe"
    if os.path.exists(dest):
        log(f"  已存在 ffmpeg.exe，跳过下载")
        return dest

    zip_path = "ffmpeg.zip"
    log("[准备] 下载 Windows 版 ffmpeg...")
    if not download_file(FFMPEG_URL_WINDOWS, zip_path):
        return None

    log("[准备] 解压 ffmpeg...")
    try:
        with zipfile.ZipFile(zip_path) as z:
            ffmpeg_member = None
            for name in z.namelist():
                if name.endswith("bin/ffmpeg.exe"):
                    ffmpeg_member = name
                    break
            if not ffmpeg_member:
                log("  压缩包中未找到 ffmpeg.exe")
                return None
            with z.open(ffmpeg_member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        os.remove(zip_path)
        log(f"  ffmpeg.exe 就绪 ({os.path.getsize(dest)/1024/1024:.1f} MB)")
        return dest
    except Exception as e:
        log(f"  解压失败: {e}")
        return None


def get_ffmpeg_unix() -> str | None:
    dest = "ffmpeg"
    if os.path.exists(dest):
        return dest
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        shutil.copy2(sys_ffmpeg, dest)
        os.chmod(dest, 0o755)
        log(f"  使用系统 ffmpeg: {sys_ffmpeg}")
        return dest
    log("  未找到系统 ffmpeg，请先安装 ffmpeg")
    return None


# ============ 主流程 ============
def main():
    script = "netease_music_downloader.py"
    if not os.path.exists(script):
        die(f"找不到 {script}")

    log("=" * 56)
    log("  网易云音乐下载器 - 单文件打包 (含 ffmpeg)")
    log("  当前环境: %s %d.%d" % (os.name, sys.version_info.major, sys.version_info.minor))
    log("=" * 56)

    # 1. 彻底清理
    clean_all()

    # 2. ffmpeg
    log("\n[1/3] 准备 ffmpeg...")
    if os.name == "nt":
        ffmpeg = get_ffmpeg_windows()
        ffmpeg_name = "ffmpeg.exe"
    else:
        ffmpeg = get_ffmpeg_unix()
        ffmpeg_name = "ffmpeg"

    if not ffmpeg or not os.path.exists(ffmpeg):
        die("ffmpeg 准备失败")

    # 3. 确保 PyInstaller 已安装
    try:
        import PyInstaller  # noqa
    except ImportError:
        log("[依赖] 安装 PyInstaller...")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--break-system-packages",
             "pyinstaller>=6.0"],
        )
        if r.returncode != 0:
            die("PyInstaller 安装失败")

    # 4. PyInstaller 打包
    log("\n[2/3] PyInstaller 打包中（这一步需要几分钟）...")
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--clean",
        "--noconfirm",
        "--name", "netease_music_downloader",
        "--add-binary", f"{ffmpeg}{sep}.",
        "--hidden-import", "Crypto.Cipher.AES",
        "--hidden-import", "mutagen.id3",
        "--hidden-import", "mutagen.mp3",
        "--hidden-import", "colorama",
        "--hidden-import", "charset_normalizer",
        "--collect-all", "colorama",
        script,
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    log("  命令: " + " ".join(cmd))
    result = subprocess.run(cmd, env=env)

    if result.returncode != 0:
        die("打包失败")

    exe_name = "netease_music_downloader" + (".exe" if os.name == "nt" else "")
    exe_path = os.path.join("dist", exe_name)

    if not os.path.exists(exe_path):
        die("未找到生成的可执行文件: " + exe_path)

    size = os.path.getsize(exe_path) / 1024 / 1024

    # 5. 快速自检
    log("\n[3/3] 自检 --help...")
    try:
        r = subprocess.run(
            [exe_path, "--help"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if r.returncode == 0 and "网易云" in r.stdout:
            log("  ✅ --help 输出正常，中文不乱码")
        else:
            log("  ⚠️  --help 输出异常（非致命）:")
            log(r.stdout[:200] + r.stderr[:200])
    except Exception as e:
        log(f"  ⚠️  自检跳过: {e}")

    # 6. 清理临时 ffmpeg
    if os.path.exists(ffmpeg_name):
        try:
            os.remove(ffmpeg_name)
        except Exception:
            pass

    log(f"\n{'=' * 56}")
    log(f"  ✅ 打包成功！单文件，自带 ffmpeg，零依赖")
    log(f"  文件: {os.path.abspath(exe_path)}")
    log(f"  大小: {size:.1f} MB")
    log(f"{'=' * 56}")
    log(f"\n使用示例:")
    log(f"  ./{exe_name} --help")
    log(f"  ./{exe_name} 259138 -o ./音乐")
    log(f"  ./{exe_name} --artist 周杰伦")
    log(f"  ./{exe_name} --playlist 123456789")
    log(f"  ./{exe_name} --daily --cookie \"MUSIC_U=你的cookie\"")


if __name__ == "__main__":
    main()
