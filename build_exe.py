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


# ffmpeg 下载源（按优先级）：国内代理加速 GitHub Release → gyan.dev 官方源兜底
# 结构不同但 zip 内部都有 bin/ffmpeg.exe，解压时统一按 endswith("bin/ffmpeg.exe") 匹配
FFMPEG_URLS_WINDOWS = [
    # mirror.ghproxy.com 代理 GitHub BtbN/FFmpeg-Builds（国内 CDN 加速，约 30MB）
    "https://mirror.ghproxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    # ghfast.top 代理 GitHub BtbN（备用）
    "https://ghfast.top/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    # gyan.dev 官方源（约 110MB，国内直连较慢）
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]


def log(msg):
    try:
        print(msg, flush=True)
    except (UnicodeEncodeError, UnicodeDecodeError):
        fallback = str(msg).encode("ascii", errors="replace").decode("ascii")
        print(fallback, flush=True)


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
def _download_with_progress(url, dest, timeout=60):
    """带进度显示的下载，返回 True=完整、False=损坏或失败"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total = int(total) if total else None
            downloaded = 0
            with open(dest, "wb") as out:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        mb_done = downloaded / 1024 / 1024
                        mb_total = total / 1024 / 1024
                        sys.stderr.write(
                            "\r  下载进度: %d%%  (%.1f / %.1f MB)  " % (pct, mb_done, mb_total)
                        )
                    else:
                        sys.stderr.write("\r  已下载: %.1f MB  " % (downloaded / 1024 / 1024))
                    sys.stderr.flush()
            sys.stderr.write("\n")
        return True
    except Exception as e:
        log("  下载失败: %s" % e)
        return False


def _is_valid_zip(path):
    """验证 zip 文件完整性，坏包（用户强退残留）直接判 False"""
    try:
        with zipfile.ZipFile(path) as z:
            # testzip 会逐个 CRC 校验，任意文件损坏返回第一个坏文件
            return z.testzip() is None
    except zipfile.BadZipFile:
        return False
    except Exception:
        return False


def _cleanup_bad_zip(zip_path):
    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
            log("  已清理损坏的旧 zip 残留")
        except Exception:
            pass


def get_ffmpeg_windows():
    # type: () -> Optional[str]
    dest = "ffmpeg.exe"

    # ---- 最高优先级：本地已有 ffmpeg.exe（用户手动放 / 上次下载好的） ----
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        log("  ✅ 检测到本地 ffmpeg.exe (%.1f MB)，跳过下载" % (os.path.getsize(dest) / 1024 / 1024))
        return dest
    elif os.path.exists(dest):
        log("  本地 ffmpeg.exe 异常小 (%d 字节)，判定为损坏，重新下载" % os.path.getsize(dest))
        os.remove(dest)

    zip_path = "ffmpeg.zip"
    _cleanup_bad_zip(zip_path)

    log("[准备] 下载 Windows 版 ffmpeg...")

    downloaded = False
    for i, url in enumerate(FFMPEG_URLS_WINDOWS):
        label = ["ghproxy 代理 GitHub", "ghfast 代理 GitHub", "gyan.dev 官方源"][i] if i < 3 else "源 %d" % (i + 1)
        log("  [%d/%d] 尝试 %s: %s" % (i + 1, len(FFMPEG_URLS_WINDOWS), label, url))
        # 每个源最多重试 3 次，每次 60 秒超时
        ok = False
        for attempt in range(3):
            if attempt > 0:
                log("  第 %d 次重试..." % (attempt + 1))
            if _download_with_progress(url, zip_path, timeout=60):
                if _is_valid_zip(zip_path):
                    ok = True
                    break
                else:
                    log("  下载完成但 zip 校验失败（%s），清理后重试..." % (
                        "CRC 错误" if os.path.exists(zip_path) else "文件为空"))
                    _cleanup_bad_zip(zip_path)
            else:
                _cleanup_bad_zip(zip_path)
        if ok:
            downloaded = True
            break
        log("  此源下载失败，尝试下一个...")

    if not downloaded:
        log("\n  ❌ 所有自动下载源均失败")
        log("\n  👉 请手动下载 ffmpeg.exe，放到当前目录后重跑脚本")
        log("\n  推荐下载地址（国内可直连）：")
        log("    ① https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
        log("       解压后进入 bin 文件夹，复制 ffmpeg.exe 到本目录")
        log("    ② 或从 3DM / 新浪爱问共享资料 等搜 ffmpeg")
        log("       下载 ffmpeg 9.x essentials 解压，取 bin/ffmpeg.exe")
        log("\n  放好后目录里应该看到 ffmpeg.exe (约 80 MB)")
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
                log("  压缩包中未找到 ffmpeg.exe，可用内容:")
                for n in z.namelist()[:20]:
                    log("    %s" % n)
                _cleanup_bad_zip(zip_path)
                return None
            log("  正在提取 %s ..." % ffmpeg_member)
            with z.open(ffmpeg_member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
        os.remove(zip_path)
        log("  ✅ ffmpeg.exe 就绪 (%.1f MB)" % (os.path.getsize(dest) / 1024 / 1024))
        return dest
    except Exception as e:
        log("  解压失败: %s" % e)
        _cleanup_bad_zip(zip_path)
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

    # 1. 彻底清理（包含上次可能残留的坏 ffmpeg.zip）
    clean_all()
    for junk in ("ffmpeg.zip", "ffmpeg.exe", "ffmpeg"):
        if os.path.exists(junk):
            try:
                os.remove(junk)
            except Exception:
                pass

    # 2. ffmpeg
    log("\n[1/3] 准备 ffmpeg...")
    if os.name == "nt":
        ffmpeg = get_ffmpeg_windows()
        ffmpeg_name = "ffmpeg.exe"
    else:
        ffmpeg = get_ffmpeg_unix()
        ffmpeg_name = "ffmpeg"

    if not ffmpeg or not os.path.exists(ffmpeg):
        die("ffmpeg 准备失败，请查看上方的手动下载指引")

    # 3. 确保 PyInstaller 已安装（Win7 兼容用 5.x）
    try:
        import PyInstaller  # noqa
        pi_ver = PyInstaller.__version__
        log("[依赖] 已安装 PyInstaller %s" % pi_ver)
        if os.name == "nt" and sys.version_info <= (3, 8):
            major_pi = int(pi_ver.split(".")[0])
            if major_pi >= 6:
                log("[依赖] Win7 兼容需要 PyInstaller 5.x，正在降级...")
                subprocess.run(
                    [sys.executable, "-m", "pip", "install",
                     "pyinstaller>=5.0,<6.0", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                     "--disable-pip-version-check"],
                )
    except ImportError:
        log("[依赖] 安装 PyInstaller...")
        if os.name == "nt" and sys.version_info <= (3, 8):
            pkg = "pyinstaller>=5.0,<6.0"
        else:
            pkg = "pyinstaller>=5.0"
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg,
             "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
             "--disable-pip-version-check"],
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
        "--add-binary", "%s%s." % (ffmpeg, sep),
        "--hidden-import", "Crypto.Cipher.AES",
        "--hidden-import", "Crypto.Util.Padding",
        "--hidden-import", "Crypto.Util.strxor",
        "--hidden-import", "Crypto.Random",
        "--hidden-import", "mutagen.id3",
        "--hidden-import", "mutagen.mp3",
        "--hidden-import", "mutagen",
        "--hidden-import", "colorama",
        "--hidden-import", "charset_normalizer",
        "--hidden-import", "idna",
        "--hidden-import", "urllib3",
        "--hidden-import", "requests",
        "--collect-all", "colorama",
        "--collect-all", "Crypto",
        script,
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
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
