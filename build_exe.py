#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键打包脚本：将 netease_music_downloader.py + ffmpeg 打包为单个可执行文件
打包后的 exe 自带 ffmpeg，用户无需安装任何依赖即可直接使用。
支持 Windows 7 ~ Windows 11（需用 Python 3.8 打包以兼容 Win7）。

Windows:  python build_exe.py   ->  dist/netease_music_downloader.exe
Linux  :  python build_exe.py   ->  dist/netease_music_downloader
"""

import os
import shutil
import subprocess
import sys
import zipfile
import urllib.request
from typing import Optional


FFMPEG_URL_WINDOWS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
)


def log(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print("\n[错误] %s" % msg, file=sys.stderr, flush=True)
    sys.exit(code)


# ============ 彻底清理 ============
def clean_all():
    log("[清理] 删除旧的构建产物...")
    for d in ("build", "dist", "__pycache__"):
        shutil.rmtree(d, ignore_errors=True)
    for root, dirs, files in os.walk("."):
        for f in files:
            if f.endswith(".spec"):
                try:
                    os.remove(os.path.join(root, f))
                except Exception:
                    pass
        dirs[:] = [d for d in dirs if d not in ("build", "dist", "__pycache__")]
    log("  已清理")


# ============ ffmpeg 准备 ============
def download_file(url, dest):
    log("  下载: %s" % url)
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        log("  下载失败: %s" % e)
        return False


def get_ffmpeg_windows():
    # type: () -> Optional[str]
    dest = "ffmpeg.exe"
    if os.path.exists(dest):
        log("  已存在 ffmpeg.exe，跳过下载")
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
        log("  ffmpeg.exe 就绪 (%.1f MB)" % (os.path.getsize(dest) / 1024 / 1024))
        return dest
    except Exception as e:
        log("  解压失败: %s" % e)
        return None


def get_ffmpeg_unix():
    # type: () -> Optional[str]
    dest = "ffmpeg"
    if os.path.exists(dest):
        return dest
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        shutil.copy2(sys_ffmpeg, dest)
        os.chmod(dest, 0o755)
        log("  使用系统 ffmpeg: %s" % sys_ffmpeg)
        return dest
    log("  未找到系统 ffmpeg，请先安装 ffmpeg")
    return None


# ============ Python 版本检查 ============
def check_python_version():
    major, minor = sys.version_info.major, sys.version_info.minor
    log("[环境] Python %d.%d.%d" % (major, minor, sys.version_info.micro))
    if os.name == "nt":
        # Windows 7 只支持到 Python 3.8
        if major == 3 and minor <= 8:
            log("[环境] ✅ 兼容 Windows 7 ~ 11")
        elif major == 3 and minor <= 11:
            log("[环境] ⚠️  兼容 Windows 8.1 ~ 11（不支持 Win7）")
        else:
            log("[环境] ⚠️  仅支持 Windows 10+（如需 Win7 请用 Python 3.8）")
    if major < 3 or (major == 3 and minor < 8):
        die("Python 版本过低，请使用 Python 3.8 及以上")


# ============ 主流程 ============
def main():
    script = "netease_music_downloader.py"
    if not os.path.exists(script):
        die("找不到 %s" % script)

    log("=" * 56)
    log("  网易云音乐下载器 - 单文件打包 (含 ffmpeg)")
    log("=" * 56)

    check_python_version()

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

    # 3. 确保 PyInstaller 已安装（Win7 兼容用 5.x）
    try:
        import PyInstaller  # noqa
        pi_ver = PyInstaller.__version__
        log("[依赖] 已安装 PyInstaller %s" % pi_ver)
        if os.name == "nt" and sys.version_info <= (3, 8):
            # Win7 需要 PyInstaller 5.x
            major_pi = int(pi_ver.split(".")[0])
            if major_pi >= 6:
                log("[依赖] Win7 兼容需要 PyInstaller 5.x，正在降级...")
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "pyinstaller>=5.0,<6.0"],
                )
    except ImportError:
        log("[依赖] 安装 PyInstaller...")
        if os.name == "nt" and sys.version_info <= (3, 8):
            pkg = "pyinstaller>=5.0,<6.0"
        else:
            pkg = "pyinstaller>=5.0"
        r = subprocess.run([sys.executable, "-m", "pip", "install", pkg])
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
        "--add-binary", "%s%s." % (ffmpeg, sep),
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
        die("打包失败，请查看上方错误信息")

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
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        if r.returncode == 0 and ("网易云" in r.stdout or "netease" in r.stdout.lower()):
            log("  ✅ --help 输出正常")
        else:
            log("  ⚠️  --help 输出异常（非致命）:")
            log((r.stdout or "")[:200] + (r.stderr or "")[:200])
    except Exception as e:
        log("  ⚠️  自检跳过: %s" % e)

    # 6. 清理临时 ffmpeg
    if os.path.exists(ffmpeg_name):
        try:
            os.remove(ffmpeg_name)
        except Exception:
            pass

    log("\n" + "=" * 56)
    log("  ✅ 打包成功！单文件，自带 ffmpeg，零依赖")
    log("  文件: %s" % os.path.abspath(exe_path))
    log("  大小: %.1f MB" % size)
    log("  可直接拷入 U 盘，在任意 Windows 电脑上运行")
    log("=" * 56)
    log("\n使用示例:")
    log("  %s --help" % exe_name)
    log("  %s 259138 -o ./音乐" % exe_name)
    log("  %s --artist 周杰伦" % exe_name)
    log("  %s --playlist 123456789" % exe_name)
    log("  %s --daily --cookie \"MUSIC_U=你的cookie\"" % exe_name)


if __name__ == "__main__":
    main()
