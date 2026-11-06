#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐下载器（Windows XP 兼容版）

- 纯 Python，不依赖 ffmpeg / mutagen
- 直接下载网易云原生 MP3（最高 320kbps），手工写入 ID3v2 标签与封面
- 兼容 Python 3.4（Windows XP SP3 能运行的最后一个 Python 3 版本）
- 单文件 32 位 exe，可在 XP / Win7 / Win8 / Win10 / Win11 上运行

支持：单曲 / 搜索 / 歌手 / 歌单 / 榜单 / 每日推荐
"""

import argparse
import base64
import binascii
import datetime
import json
import os
import random
import re
import string
import struct
import sys
import time
import traceback

import requests
from Crypto.Cipher import AES

APP_VERSION = "3.0.0"


# ==================== Windows 控制台（XP 兼容） ====================
_CONSOLE_INPUT_CP936 = False
_OLD_CONSOLE_CP = None
_OLD_STDIN = None


class _WinConsoleWriter(object):
    """直接调用 WriteConsoleW 输出，绕过代码页，任何语言的 XP 都不乱码"""

    def __init__(self, stream, handle_id):
        self._stream = stream
        self._handle_id = handle_id
        self._checked = False
        self._handle = None

    def _console(self):
        if self._checked:
            return self._handle
        self._checked = True
        if os.name != "nt":
            return None
        try:
            import ctypes
            h = ctypes.windll.kernel32.GetStdHandle(self._handle_id)
            if h:
                mode = ctypes.c_ulong(0)
                if ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                    self._handle = h
        except Exception:
            self._handle = None
        return self._handle

    def write(self, text):
        if not text:
            return
        h = self._console()
        if h:
            try:
                import ctypes
                text = text.replace("\r\n", "\n").replace("\n", "\r\n")
                raw = text.encode("utf-16-le")
                n = len(raw) // 2
                buf = ctypes.create_string_buffer(raw, len(raw))
                written = ctypes.c_ulong(0)
                ctypes.windll.kernel32.WriteConsoleW(
                    h, buf, n, ctypes.byref(written), None)
                return
            except Exception:
                pass
        try:
            self._stream.write(text)
        except UnicodeEncodeError:
            try:
                self._stream.buffer.write(text.encode("utf-8", "replace"))
            except Exception:
                pass

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        return bool(self._console())


def _init_console():
    """XP 中文控制台输入用 GBK；输出用 WriteConsoleW，不依赖代码页"""
    global _CONSOLE_INPUT_CP936, _OLD_CONSOLE_CP, _OLD_STDIN
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        try:
            _OLD_CONSOLE_CP = k.GetConsoleCP()
        except Exception:
            _OLD_CONSOLE_CP = None
        _CONSOLE_INPUT_CP936 = bool(k.SetConsoleCP(936))
    except Exception:
        _CONSOLE_INPUT_CP936 = False

    if sys.stdout is not None:
        sys.stdout = _WinConsoleWriter(sys.stdout, -11)   # STD_OUTPUT_HANDLE
    if sys.stderr is not None:
        sys.stderr = _WinConsoleWriter(sys.stderr, -12)   # STD_ERROR_HANDLE

    if _CONSOLE_INPUT_CP936 and sys.stdin is not None and hasattr(sys.stdin, "buffer"):
        try:
            import io
            # 保留旧对象引用，防止被 GC 后关闭底层 buffer
            _OLD_STDIN = sys.stdin
            sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="gbk",
                                         errors="replace")
        except Exception:
            pass


def _restore_console():
    if os.name != "nt" or _OLD_CONSOLE_CP is None:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCP(_OLD_CONSOLE_CP)
    except Exception:
        pass


_init_console()
import atexit
atexit.register(_restore_console)


# ==================== 基础输出 ====================
def log_info(msg):
    print("[INFO] " + msg)


def log_ok(msg):
    print("[OK]   " + msg)


def log_warn(msg):
    print("[WARN] " + msg)


def log_err(msg):
    print("[ERROR] " + msg)


# ==================== 便携路径 ====================
def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


CONFIG_FILE = os.path.join(app_dir(), ".netease_downloader.json")
ERROR_LOG = os.path.join(app_dir(), "netease_downloader_error.log")

BASE_URL = "https://music.163.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

NONCE = b"0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
IV = b"0102030405060708"


def ca_bundle():
    """优先使用打包进 exe 的最新根证书，避免老系统证书过期"""
    p = resource_path("cacert.pem")
    if os.path.exists(p):
        return p
    return True


def log_traceback():
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write("\n[%s]\n%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), traceback.format_exc()))
    except Exception:
        pass


# ==================== 配置 ====================
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def set_cookie(cookie):
    base = "appver=2.0.2; os=pc;"
    if cookie:
        cookie = cookie.strip()
        if cookie.lower().startswith("music_u"):
            cookie = "%s %s" % (base, cookie)
        HEADERS["Cookie"] = cookie
        SESSION.headers["Cookie"] = cookie
    else:
        HEADERS["Cookie"] = base
        SESSION.headers["Cookie"] = base


# ==================== 加密 ====================
def _aes_encrypt(text, key):
    pad = 16 - len(text) % 16
    text = text + chr(pad) * pad
    cipher = AES.new(key, AES.MODE_CBC, IV).encrypt(text.encode("utf-8"))
    return base64.b64encode(cipher).decode("utf-8")


def _rsa_encrypt(text):
    text = text[::-1]
    hex_str = binascii.hexlify(text.encode("utf-8")).decode("ascii")
    rs = pow(int(hex_str, 16), int(PUB_KEY, 16),
             int(MODULUS, 16))
    return format(rs, "x").zfill(256)


def _create_secret_key(size=16):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(size))


def weapi_post(path, data):
    text = json.dumps(data)
    secret_key = _create_secret_key(16)
    params = _aes_encrypt(_aes_encrypt(text, NONCE),
                          secret_key.encode("utf-8"))
    payload = {"params": params, "encSecKey": _rsa_encrypt(secret_key)}
    resp = SESSION.post(BASE_URL + "/weapi" + path, data=payload,
                        timeout=(10, 40), verify=ca_bundle())
    resp.raise_for_status()
    return resp.json()


# ==================== 工具 ====================
def extract_id(text):
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"[?&]id=(\d+)", text) or re.search(r"/(\d+)", text)
    if m:
        return m.group(1)
    raise ValueError("无法从输入中解析 ID: %s" % text)


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_filename(title, artists):
    if artists:
        return safe_filename("%s - %s" % (title, artists))
    return safe_filename(title)


def join_artists(song):
    ar = song.get("ar") or song.get("artists") or []
    return "/".join(a.get("name", "") for a in ar)


# ==================== API ====================
def get_songs_detail(song_ids):
    data = {
        "c": json.dumps([{"id": sid} for sid in song_ids]),
        "ids": json.dumps(song_ids),
    }
    return weapi_post("/v3/song/detail", data).get("songs") or []


def get_song_url(song_id, level="exhigh"):
    """取播放链接。encodeType=mp3 保证返回原生 mp3，无需转码"""
    data = {"ids": json.dumps([song_id]), "level": level, "encodeType": "mp3"}
    try:
        lst = weapi_post("/song/enhance/player/url/v1", data).get("data") or []
        if lst and lst[0].get("url"):
            return lst[0]
    except Exception:
        pass

    # 老接口兜底
    br = {"standard": 128000, "higher": 192000, "exhigh": 320000}.get(level, 320000)
    try:
        d = weapi_post("/song/enhance/player/url",
                       {"ids": json.dumps([song_id]), "br": br})
        lst = d.get("data") or []
        if lst:
            return lst[0]
    except Exception:
        pass
    return {}


def search_songs(keyword, limit=15):
    data = {"s": keyword, "type": 1, "limit": limit, "offset": 0}
    songs = (weapi_post("/search/get", data).get("result") or {}).get("songs", [])
    out = []
    for s in songs:
        fee = s.get("fee", 0)
        out.append({
            "id": s["id"],
            "name": s.get("name", ""),
            "artists": join_artists(s),
            "album": (s.get("album") or s.get("al") or {}).get("name", ""),
            "fee": {0: "免费", 1: "VIP", 4: "付费", 8: "免费"}.get(fee, str(fee)),
        })
    return out


def search_artists(keyword, limit=5):
    data = {"s": keyword, "type": 100, "limit": limit, "offset": 0}
    artists = (weapi_post("/search/get", data).get("result") or {}).get("artists", [])
    return [{"id": a["id"], "name": a.get("name", "")} for a in artists]


def get_artist_hot_songs(artist_id):
    songs = weapi_post("/artist/top/song", {"id": artist_id}).get("songs") or []
    return [{
        "id": s["id"],
        "name": s.get("name", ""),
        "artists": join_artists(s),
        "album": (s.get("al") or {}).get("name", ""),
    } for s in songs]


def get_playlist_detail(playlist_id):
    return weapi_post("/v6/playlist/detail",
                      {"id": playlist_id, "n": 100000, "s": 8}).get("playlist") or {}


def get_toplist():
    lists = weapi_post("/toplist", {}).get("list") or []
    return [{
        "id": l["id"],
        "name": l.get("name", ""),
        "updateFrequency": l.get("updateFrequency", ""),
    } for l in lists]


def get_daily_recommend_songs():
    data = weapi_post("/v1/discovery/recommend/songs", {}).get("data") or {}
    songs = data.get("dailySongs") or []
    return [{
        "id": s["id"],
        "name": s.get("name", ""),
        "artists": join_artists(s),
        "album": (s.get("al") or {}).get("name", ""),
    } for s in songs]


def get_login_status():
    try:
        profile = weapi_post("/w/nuser/account/get", {}).get("profile")
        return profile or None
    except Exception:
        return None


# ==================== ID3v2.3（不依赖 mutagen） ====================
def _synchsafe(n):
    return bytes(bytearray([(n >> 21) & 0x7F, (n >> 14) & 0x7F,
                            (n >> 7) & 0x7F, n & 0x7F]))


def _id3_frame(frame_id, payload):
    return (frame_id.encode("ascii") + struct.pack(">I", len(payload))
            + b"\x00\x00" + payload)


def _utf16_text(text):
    # 编码字节 0x01 = UTF-16（带 BOM）
    return b"\x01\xff\xfe" + text.encode("utf-16-le")


def _apic_frame(cover, mime):
    # 编码、MIME、图片类型(3=封面)、空描述（UTF-16 BOM + 结束符）、图片数据
    return _id3_frame("APIC", b"\x01" + mime + b"\x00\x03"
                      + b"\xff\xfe\x00\x00" + cover)


def _strip_id3(data):
    """去掉 MP3 开头已有的 ID3v2 标签，避免重复叠加"""
    if len(data) >= 10 and data[:3] == b"ID3":
        flags = data[5]
        size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | \
               ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
        total = 10 + size
        if flags & 0x10:  # footer
            total += 10
        if total <= len(data):
            return data[total:]
    return data


def write_tags(mp3_path, detail, cover):
    """手工写 ID3v2.3 标签：标题 / 歌手 / 专辑 / 年份 / 封面"""
    try:
        name = detail.get("name") or ""
        artists = join_artists(detail)
        album = (detail.get("al") or {}).get("name") or ""
        pub = detail.get("publishTime") or (detail.get("al") or {}).get("publishTime")

        frames = b""
        if name:
            frames += _id3_frame("TIT2", _utf16_text(name))
        if artists:
            frames += _id3_frame("TPE1", _utf16_text(artists))
        if album:
            frames += _id3_frame("TALB", _utf16_text(album))
        if pub:
            try:
                year = str(datetime.datetime.fromtimestamp(pub / 1000).year)
                frames += _id3_frame("TYER", _utf16_text(year))
            except Exception:
                pass
        if cover and len(cover) > 2 * 1024 * 1024:
            cover = None  # 异常大图不写入，避免 mp3 体积暴涨
        if cover:
            mime = "image/png" if cover[:4] == b"\x89PNG" else "image/jpeg"
            frames += _apic_frame(cover, mime.encode("ascii"))

        padding = 64
        tag = (b"ID3\x03\x00\x00" + _synchsafe(len(frames) + padding)
               + frames + b"\x00" * padding)

        with open(mp3_path, "rb") as f:
            data = f.read()
        audio = _strip_id3(data)
        with open(mp3_path, "wb") as f:
            f.write(tag)
            f.write(audio)
    except Exception as e:
        print("  [WARN] 写入标签失败（不影响播放）: %s" % e)


# ==================== 下载 ====================
def download_stream(url, dest):
    for attempt in range(3):
        try:
            r = SESSION.get(url, stream=True, timeout=(10, 60),
                            verify=ca_bundle())
            try:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                last = -1
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            pct = got * 100 // total
                            if pct != last and pct % 10 == 0:
                                print("\r  下载中 %d%%" % pct, end="")
                                last = pct
                print("\r  下载完成 (%.1f MB)          " % (got / 1024.0 / 1024.0))
                return got > 1024
            finally:
                r.close()
        except Exception as e:
            if attempt == 2:
                print("\r  下载失败: %s          " % e)
                return False
            time.sleep(1)
    return False


def download_cover(url, size="500y500"):
    """下载封面；加 param 让网易云返回缩小版，避免把几 MB 原图塞进 MP3"""
    if not url:
        return None
    if "param=" not in url:
        url = url + ("&" if "?" in url else "?") + "param=" + size
    try:
        r = SESSION.get(url, timeout=(10, 20), verify=ca_bundle())
        try:
            if r.status_code == 200 and r.content:
                return r.content
        finally:
            r.close()
    except Exception:
        pass
    return None


def download_one(song_id, output_dir, level="exhigh", detail=None):
    if detail is None:
        details = get_songs_detail([song_id])
        if not details:
            log_warn("获取歌曲详情失败: %s" % song_id)
            return None
        detail = details[0]

    name = detail.get("name") or ("song_%s" % song_id)
    artists = join_artists(detail)
    album = (detail.get("al") or {}).get("name") or ""
    cover_url = (detail.get("al") or {}).get("picUrl") or ""

    info = {}
    tried = []
    for lv in (level, "higher", "standard"):
        if lv in tried:
            continue
        tried.append(lv)
        got = get_song_url(song_id, level=lv)
        if got.get("url"):
            info = got
            break

    url = info.get("url")
    if not url:
        log_warn("无法获取「%s」下载链接（VIP / 版权 / 地区限制）" % name)
        return None

    fmt = (info.get("type") or "mp3").lower()
    ext = "mp3" if fmt == "mp3" else fmt
    if not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir)
        except Exception:
            pass

    final_path = os.path.join(output_dir,
                              "%s.%s" % (build_filename(name, artists), ext))
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
        log_info("已存在，跳过: %s" % os.path.basename(final_path))
        return final_path

    br = (info.get("br") or 0) // 1000
    print("  %s - %s  (%s)" % (name, artists, album))
    print("    格式: %s  %dkbps" % (fmt, br))

    if not download_stream(url, final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
        return None

    if ext == "mp3":
        write_tags(final_path, detail, download_cover(cover_url))
    return final_path


def batch_download(songs, output_dir, level="exhigh"):
    total = len(songs)
    if total == 0:
        log_warn("没有可下载的歌曲")
        return

    detail_map = {}
    ids = [str(s["id"]) for s in songs]
    for i in range(0, len(ids), 100):
        try:
            for d in get_songs_detail(ids[i:i + 100]):
                detail_map[str(d["id"])] = d
        except Exception as e:
            log_warn("批量获取详情失败: %s" % e)
        time.sleep(0.2)

    log_info("开始下载，共 %d 首 → %s" % (total, output_dir))
    ok = fail = 0
    for idx, s in enumerate(songs, 1):
        sid = str(s["id"])
        detail = detail_map.get(sid)
        if detail is None:
            log_warn("[%d/%d] 跳过（无详情）: %s" % (idx, total, s.get("name", sid)))
            fail += 1
            continue
        print("\n[%d/%d] " % (idx, total), end="")
        try:
            if download_one(sid, output_dir, level=level, detail=detail):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            log_err("下载异常: %s" % e)
            fail += 1
        time.sleep(0.1)

    print()
    log_ok("完成: 成功 %d 首, 失败 %d 首" % (ok, fail))


# ==================== 交互菜单 ====================
def ask(prompt):
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    except Exception:
        return None
    if v.lower() in ("q", "quit", "exit"):
        return None
    return v


def pick(items, label="请选择"):
    for i, it in enumerate(items, 1):
        print("  [%d] %s" % (i, it))
    v = ask("\n%s (1-%d, q 退出): " % (label, len(items)))
    if v and v.isdigit() and 1 <= int(v) <= len(items):
        return int(v) - 1
    return None


def interactive_menu():
    cfg = load_config()
    set_cookie(cfg.get("cookie"))

    print()
    print("=" * 50)
    print("        网易云音乐下载器 v%s" % APP_VERSION)
    print("=" * 50)

    if cfg.get("cookie"):
        profile = get_login_status()
        if profile:
            log_ok("已登录: %s" % profile.get("nickname", ""))
        else:
            log_warn("Cookie 可能已失效（VIP / 灰色歌曲无法下载）")
    else:
        log_warn("未登录（VIP / 灰色歌曲无法下载，菜单 7 可设置）")

    default_out = cfg.get("output") or os.path.join(app_dir(), "音乐")

    menu = [
        "单曲下载（歌曲 ID）",
        "搜索下载（关键词）",
        "歌手热门歌曲",
        "歌单下载（歌单 ID / 链接）",
        "官方榜单下载",
        "每日推荐（需登录）",
        "设置（登录 Cookie / 下载目录）",
        "退出",
    ]

    while True:
        print()
        for i, m in enumerate(menu, 1):
            print("  [%d] %s" % (i, m))
        choice = ask("\n请选择 (1-%d): " % len(menu))

        if choice is None or choice == "8":
            break

        try:
            if choice == "1":
                sid = ask("输入歌曲 ID 或链接: ")
                if not sid:
                    continue
                sid = extract_id(sid)
                path = download_one(sid, default_out)
                if path:
                    log_ok("已保存: %s" % path)

            elif choice == "2":
                kw = ask("搜索关键词: ")
                if not kw:
                    continue
                res = search_songs(kw, limit=15)
                if not res:
                    log_warn("没有搜索结果")
                    continue
                idx = pick(["%s - %s  [%s]" % (s["name"], s["artists"], s["fee"])
                            for s in res], "选择要下载的歌曲")
                if idx is not None:
                    path = download_one(res[idx]["id"], default_out)
                    if path:
                        log_ok("已保存: %s" % path)

            elif choice == "3":
                kw = ask("歌手名: ")
                if not kw:
                    continue
                artists = search_artists(kw)
                if not artists:
                    log_warn("没有找到歌手")
                    continue
                if len(artists) == 1:
                    ai = 0
                else:
                    ai = pick([a["name"] for a in artists], "选择歌手")
                    if ai is None:
                        continue
                batch_download(get_artist_hot_songs(artists[ai]["id"]), default_out)

            elif choice == "4":
                pid = ask("歌单 ID 或链接: ")
                if not pid:
                    continue
                pid = extract_id(pid)
                pl = get_playlist_detail(pid)
                if not pl:
                    log_warn("歌单不存在")
                    continue
                tracks = pl.get("tracks") or []
                log_info("歌单「%s」，共 %d 首" % (pl.get("name", ""), len(tracks)))
                batch_download([{"id": t["id"], "name": t.get("name", "")}
                                for t in tracks], default_out)

            elif choice == "5":
                lists = get_toplist()
                if not lists:
                    log_warn("获取榜单失败")
                    continue
                idx = pick(["%s (%s)" % (l["name"], l.get("updateFrequency", ""))
                            for l in lists], "选择榜单")
                if idx is None:
                    continue
                pl = get_playlist_detail(lists[idx]["id"])
                tracks = (pl.get("tracks") or [])[:200]
                batch_download([{"id": s["id"], "name": s.get("name", "")}
                                for s in tracks], default_out)

            elif choice == "6":
                songs = get_daily_recommend_songs()
                if not songs:
                    log_warn("获取每日推荐失败，请先登录（菜单 7）")
                    continue
                batch_download(songs, default_out)

            elif choice == "7":
                print()
                new_cookie = ask("粘贴 Cookie 的 MUSIC_U 值（回车跳过）: ")
                if new_cookie:
                    cfg["cookie"] = new_cookie
                    set_cookie(new_cookie)
                    log_ok("Cookie 已保存")
                new_out = ask("下载目录（当前 %s，回车跳过）: " % default_out)
                if new_out:
                    cfg["output"] = new_out
                    default_out = new_out
                save_config(cfg)
                log_ok("设置已保存到 %s" % CONFIG_FILE)

            else:
                log_warn("无效的选项")

        except ValueError as e:
            log_err(str(e))
        except requests.RequestException as e:
            log_err("网络错误: %s" % e)
        except Exception as e:
            log_err("操作失败: %s" % e)
            log_traceback()


# ==================== 命令行入口 ====================
def build_parser():
    p = argparse.ArgumentParser(
        prog="netease_downloader",
        description="网易云音乐下载器 v%s（Windows XP 兼容）" % APP_VERSION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例:
  netease_downloader.exe 259138              # 下载单曲
  netease_downloader.exe --search 青花瓷      # 搜索下载
  netease_downloader.exe --artist 周杰伦      # 歌手热门
  netease_downloader.exe --playlist 3778678   # 歌单
  netease_downloader.exe --toplist            # 榜单
  netease_downloader.exe --daily --cookie "MUSIC_U=xxx"
""")
    p.add_argument("song_id", nargs="?", help="歌曲 ID")
    p.add_argument("-o", "--output", help="输出目录（默认 exe 同目录下 音乐）")
    p.add_argument("-q", "--quality", default="exhigh",
                   choices=["standard", "higher", "exhigh"],
                   help="音质 standard=128k higher=192k exhigh=320k（默认 exhigh）")
    p.add_argument("--cookie", help="登录 Cookie（MUSIC_U=xxx）")
    p.add_argument("--search", metavar="关键词", help="按关键词搜索下载")
    p.add_argument("--artist", metavar="歌手名", help="下载歌手热门歌曲")
    p.add_argument("--playlist", metavar="歌单ID或链接", help="下载整个歌单")
    p.add_argument("--toplist", action="store_true", help="下载官方榜单")
    p.add_argument("--daily", action="store_true", help="下载每日推荐（需登录）")
    p.add_argument("--limit", type=int, default=10, help="搜索/歌手数量上限（默认 10）")
    p.add_argument("--version", action="version", version="%(prog)s " + APP_VERSION)
    return p


def main():
    args = build_parser().parse_args()

    cfg = load_config()
    cookie = args.cookie or cfg.get("cookie")
    set_cookie(cookie)
    if args.cookie:
        cfg["cookie"] = args.cookie
        save_config(cfg)

    output = args.output or cfg.get("output") or os.path.join(app_dir(), "音乐")

    if not any([args.song_id, args.search, args.artist, args.playlist,
                args.toplist, args.daily]):
        interactive_menu()
        return 0

    if args.song_id:
        if not download_one(extract_id(args.song_id), output, level=args.quality):
            log_err("下载失败")
            return 1

    elif args.search:
        res = search_songs(args.search, limit=args.limit)
        if not res:
            log_err("没有搜索结果")
            return 1
        batch_download(res, output, level=args.quality)

    elif args.artist:
        artists = search_artists(args.artist, limit=args.limit)
        if not artists:
            log_err("没有找到歌手")
            return 1
        batch_download(get_artist_hot_songs(artists[0]["id"]),
                       output, level=args.quality)

    elif args.playlist:
        pl = get_playlist_detail(extract_id(args.playlist))
        if not pl:
            log_err("歌单不存在")
            return 1
        batch_download([{"id": t["id"], "name": t.get("name", "")}
                        for t in (pl.get("tracks") or [])],
                       output, level=args.quality)

    elif args.toplist:
        lists = get_toplist()
        if not lists:
            log_err("获取榜单失败")
            return 1
        pl = get_playlist_detail(lists[0]["id"])
        tracks = (pl.get("tracks") or [])[:200]
        batch_download([{"id": s["id"], "name": s.get("name", "")}
                        for s in tracks], output, level=args.quality)

    elif args.daily:
        songs = get_daily_recommend_songs()
        if not songs:
            log_err("获取每日推荐失败，请确认已登录")
            return 1
        batch_download(songs, output, level=args.quality)

    return 0


def pause_on_exit():
    """双击运行时（无参数）结束后暂停，避免窗口一闪而过"""
    if os.name != "nt" or len(sys.argv) > 1:
        return
    try:
        import msvcrt
        sys.stdout.write("\n按任意键退出...")
        sys.stdout.flush()
        msvcrt.getch()
    except Exception:
        pass


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except KeyboardInterrupt:
        print("\n已取消")
        code = 130
    except SystemExit:
        raise
    except Exception as e:
        log_err("程序异常: %s" % e)
        log_traceback()
        code = 1
    pause_on_exit()
    sys.exit(code)
