#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐下载器（纯 Python 版，无需 ffmpeg）

直接下载网易云 CDN 的原生 MP3，用 mutagen 写入封面与元数据。
不依赖 ffmpeg，因此打包后的 exe 体积小、启动快、不会卡在下载转码工具上。

支持：单曲 / 搜索 / 歌手 / 歌单 / 榜单 / 每日推荐

依赖：requests, pycryptodome, mutagen
"""

import argparse
import base64
import datetime
import json
import os
import random
import re
import string
import sys
import time
from typing import Optional

import requests
from Crypto.Cipher import AES


# ============ Windows 控制台编码 & 防闪退 ============
def _fix_windows_console() -> None:
    """Windows 控制台切换 UTF-8，避免中文乱码 / 闪退"""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _pause_on_exit() -> None:
    """双击运行时（无参数）结束后暂停，避免窗口一闪而过"""
    if os.name != "nt":
        return
    # 命令行带参数运行时，不暂停，方便脚本调用
    if len(sys.argv) > 1:
        return
    try:
        import msvcrt
        print("\n按任意键退出...", end="", flush=True)
        msvcrt.getch()
    except Exception:
        try:
            input("\n按回车键退出...")
        except Exception:
            pass


_fix_windows_console()


# ============ 颜色 ============
class C:
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def init(cls):
        if os.name == "nt":
            try:
                import ctypes
                # 开启 Windows 控制台 ANSI 颜色支持
                ctypes.windll.kernel32.SetConsoleMode(
                    ctypes.windll.kernel32.GetStdHandle(-11), 7
                )
            except Exception:
                # 老系统不支持则关闭颜色
                for attr in ("RED", "GREEN", "YELLOW", "BLUE", "MAGENTA",
                             "CYAN", "GRAY", "BOLD", "RESET"):
                    setattr(cls, attr, "")


C.init()


def log_info(msg):
    print("%s %s" % (C.CYAN + "[INFO]" + C.RESET, msg))


def log_ok(msg):
    print("%s %s" % (C.GREEN + "[OK]" + C.RESET, msg))


def log_warn(msg):
    print("%s %s" % (C.YELLOW + "[WARN]" + C.RESET, msg))


def log_err(msg):
    print("%s %s" % (C.RED + "[ERROR]" + C.RESET, msg))


# ============ 便携路径 ============
def app_dir() -> str:
    """exe 所在目录（便携：配置和下载都跟着 exe 走）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


BASE_URL = "https://music.163.com"
CONFIG_FILE = os.path.join(app_dir(), ".netease_downloader.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}

NONCE = b"0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
IV = b"0102030405060708"


# ============ 配置 ============
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def set_cookie(cookie: Optional[str]) -> None:
    base = "appver=2.0.2; os=pc;"
    if cookie:
        cookie = cookie.strip()
        if not cookie.startswith("appver"):
            cookie = "%s %s" % (base, cookie)
        HEADERS["Cookie"] = cookie
    else:
        HEADERS["Cookie"] = base


def get_login_status() -> Optional[dict]:
    try:
        profile = weapi_post("/w/nuser/account/get", {}).get("profile")
        return profile or None
    except Exception:
        return None


# ============ 加密 ============
def _aes_encrypt(text: str, key: bytes) -> str:
    pad = 16 - len(text) % 16
    text = text + chr(pad) * pad
    cipher = AES.new(key, AES.MODE_CBC, IV).encrypt(text.encode("utf-8"))
    return base64.b64encode(cipher).decode("utf-8")


def _rsa_encrypt(text: str) -> str:
    text = text[::-1]
    rs = pow(int(text.encode("utf-8").hex(), 16), int(PUB_KEY, 16), int(MODULUS, 16))
    return format(rs, "x").zfill(256)


def _create_secret_key(size: int = 16) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(size))


def weapi_post(path: str, data: dict) -> dict:
    text = json.dumps(data)
    secret_key = _create_secret_key(16)
    params = _aes_encrypt(_aes_encrypt(text, NONCE), secret_key.encode("utf-8"))
    payload = {"params": params, "encSecKey": _rsa_encrypt(secret_key)}
    resp = requests.post(BASE_URL + "/weapi" + path, data=payload,
                         headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ============ 工具 ============
def extract_id(text: str) -> str:
    text = text.strip()
    if text.isdigit():
        return text
    m = re.search(r"[?&]id=(\d+)", text) or re.search(r"/(\d+)", text)
    if m:
        return m.group(1)
    raise ValueError("无法从输入中解析 ID: %s" % text)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_filename(title: str, artists: str) -> str:
    return safe_filename("%s - %s" % (title, artists)) if artists else safe_filename(title)


# ============ API ============
def get_songs_detail(song_ids: list) -> list:
    data = {
        "c": json.dumps([{"id": sid} for sid in song_ids]),
        "ids": json.dumps(song_ids),
    }
    return weapi_post("/v3/song/detail", data).get("songs") or []


def get_song_url(song_id, level: str = "exhigh") -> dict:
    """取播放链接。encodeType=mp3 保证返回 mp3（无需 ffmpeg 转码）"""
    data = {"ids": json.dumps([song_id]), "level": level, "encodeType": "mp3"}
    lst = weapi_post("/song/enhance/player/url/v1", data).get("data") or []
    return lst[0] if lst else {}


def search_songs(keyword: str, limit: int = 10) -> list:
    data = {"s": keyword, "type": 1, "limit": limit, "offset": 0}
    songs = (weapi_post("/search/get", data).get("result") or {}).get("songs", [])
    out = []
    for s in songs:
        fee = s.get("fee", 0)
        out.append({
            "id": s["id"],
            "name": s.get("name", ""),
            "artists": "/".join(a["name"] for a in s.get("artists", s.get("ar", []))),
            "album": (s.get("album") or s.get("al") or {}).get("name", ""),
            "fee": {0: "免费", 1: "VIP", 4: "付费", 8: "免费"}.get(fee, str(fee)),
        })
    return out


def search_artists(keyword: str, limit: int = 5) -> list:
    data = {"s": keyword, "type": 100, "limit": limit, "offset": 0}
    artists = (weapi_post("/search/get", data).get("result") or {}).get("artists", [])
    return [{"id": a["id"], "name": a.get("name", "")} for a in artists]


def get_artist_hot_songs(artist_id) -> list:
    songs = weapi_post("/artist/top/song", {"id": artist_id}).get("songs") or []
    return [{
        "id": s["id"],
        "name": s.get("name", ""),
        "artists": "/".join(a["name"] for a in s.get("ar", [])),
        "album": (s.get("al") or {}).get("name", ""),
    } for s in songs]


def get_playlist_detail(playlist_id) -> dict:
    return weapi_post("/v6/playlist/detail",
                      {"id": playlist_id, "n": 100000, "s": 8}).get("playlist") or {}


def get_toplist() -> list:
    lists = weapi_post("/toplist", {}).get("list") or []
    return [{
        "id": l["id"],
        "name": l.get("name", ""),
        "updateFrequency": l.get("updateFrequency", ""),
        "playCount": l.get("playCount", 0),
    } for l in lists]


def get_daily_recommend_songs() -> list:
    data = weapi_post("/v1/discovery/recommend/songs", {}).get("data") or {}
    songs = data.get("dailySongs") or []
    return [{
        "id": s["id"],
        "name": s.get("name", ""),
        "artists": "/".join(a["name"] for a in s.get("ar", [])),
        "album": (s.get("al") or {}).get("name", ""),
    } for s in songs]


# ============ 下载 ============
def download_stream(url: str, dest: str) -> bool:
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            got = 0
            last = -1
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got * 100 // total
                        if pct != last and pct % 10 == 0:
                            print("\r  %s %d%%" % (C.CYAN + "下载中" + C.RESET, pct),
                                  end="", flush=True)
                            last = pct
            print("\r  %s (%.1f MB)          " % (C.GREEN + "下载完成" + C.RESET,
                                                  got / 1024 / 1024))
            return got > 1024
    except Exception as e:
        print("\r  %s %s          " % (C.RED + "下载失败" + C.RESET, e))
        return False


def download_cover(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


def write_tags(mp3_path: str, info: dict, cover: Optional[bytes]) -> None:
    """用 mutagen 写 ID3v2 标签 + 封面（无需 ffmpeg）"""
    try:
        from mutagen.id3 import (ID3, ID3NoHeaderError, TIT2, TPE1, TALB,
                                 TDRC, APIC)
    except Exception:
        return
    try:
        try:
            tags = ID3(mp3_path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("TIT2")
        tags.delall("TPE1")
        tags.delall("TALB")
        tags.delall("TDRC")
        tags.delall("APIC")
        if info.get("name"):
            tags.add(TIT2(encoding=3, text=info["name"]))
        artists = "/".join(a["name"] for a in info.get("ar", []))
        if artists:
            tags.add(TPE1(encoding=3, text=artists))
        album = (info.get("al") or {}).get("name")
        if album:
            tags.add(TALB(encoding=3, text=album))
        pub = info.get("publishTime") or (info.get("al") or {}).get("publishTime")
        if pub:
            try:
                tags.add(TDRC(encoding=3,
                              text=str(datetime.datetime.fromtimestamp(pub / 1000).year)))
            except Exception:
                pass
        if cover:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
        tags.save(mp3_path, v2_version=3)
    except Exception as e:
        print("  %s（不影响播放）: %s" % (C.YELLOW + "写入标签失败" + C.RESET, e))


def download_one(song_id, output_dir: str, level: str = "exhigh",
                 detail: Optional[dict] = None) -> Optional[str]:
    if detail is None:
        details = get_songs_detail([song_id])
        if not details:
            log_warn("获取歌曲详情失败: %s" % song_id)
            return None
        detail = details[0]

    name = detail.get("name", "song_%s" % song_id)
    artists = "/".join(a["name"] for a in detail.get("ar", []))
    album = (detail.get("al") or {}).get("name", "")
    cover_url = (detail.get("al") or {}).get("picUrl", "")

    # 取链接，逐级降质
    info = {}
    for lv in (level, "higher", "standard"):
        got = get_song_url(song_id, level=lv)
        if got.get("url"):
            info = got
            break

    url = info.get("url")
    if not url:
        log_warn("无法获取「%s」下载链接（VIP / 版权 / 地区限制）" % name)
        return None

    os.makedirs(output_dir, exist_ok=True)
    final_path = os.path.join(output_dir, "%s.mp3" % build_filename(name, artists))

    if os.path.exists(final_path):
        log_info("已存在，跳过: %s.mp3" % build_filename(name, artists))
        return final_path

    fmt = info.get("type", "mp3")
    br = info.get("br", 0) // 1000
    print("  %s - %s  (%s)" % (C.MAGENTA + name + C.RESET, artists, C.GRAY + album + C.RESET))
    print("    格式: %s  %dkbps" % (fmt, br))

    if not download_stream(url, final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
        return None

    write_tags(final_path, detail, download_cover(cover_url))
    return final_path


def batch_download(songs: list, output_dir: str, level: str = "exhigh") -> None:
    total = len(songs)
    if total == 0:
        log_warn("没有可下载的歌曲")
        return

    # 批量拿详情（每批 100）
    detail_map = {}
    ids = [str(s["id"]) for s in songs]
    for i in range(0, len(ids), 100):
        for d in get_songs_detail(ids[i:i + 100]):
            detail_map[str(d["id"])] = d
        time.sleep(0.3)

    log_info("开始下载，共 %s 首 → %s" % (C.BOLD + str(total) + C.RESET, output_dir))
    ok = fail = 0
    for idx, s in enumerate(songs, 1):
        sid = str(s["id"])
        detail = detail_map.get(sid)
        if detail is None:
            log_warn("[%d/%d] 跳过（无详情）: %s" % (idx, total, s.get("name", sid)))
            fail += 1
            continue
        print("\n%s " % (C.BOLD + "[%d/%d]" % (idx, total) + C.RESET), end="")
        if download_one(sid, output_dir, level=level, detail=detail):
            ok += 1
        else:
            fail += 1
        time.sleep(0.2)

    print()
    log_ok("完成: 成功 %s 首, 失败 %s 首"
           % (C.GREEN + str(ok) + C.RESET, C.RED + str(fail) + C.RESET))


# ============ 交互菜单 ============
def ask(prompt: str) -> Optional[str]:
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return None if v.lower() in ("q", "quit", "exit") else v


def pick(items: list, label: str = "请选择") -> Optional[int]:
    for i, it in enumerate(items, 1):
        print("  %s %s" % (C.CYAN + "[%d]" % i + C.RESET, it))
    v = ask("\n%s (1-%d, q 退出): " % (label, len(items)))
    if v and v.isdigit() and 1 <= int(v) <= len(items):
        return int(v) - 1
    return None


def interactive_menu() -> None:
    cfg = load_config()
    cookie = cfg.get("cookie")
    set_cookie(cookie)

    print()
    print(C.BOLD + "=" * 50)
    print("        网易云音乐下载器")
    print("=" * 50 + C.RESET)

    profile = get_login_status() if cookie else None
    if profile:
        log_ok("已登录: %s" % profile.get("nickname", ""))
    else:
        log_warn("未登录（VIP / 灰色歌曲无法下载）")

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
            print("  %s %s" % (C.CYAN + "[%d]" % i + C.RESET, m))
        choice = ask("\n请选择 (1-%d): " % len(menu))

        if choice == "1":
            sid = ask("输入歌曲 ID 或链接: ")
            if not sid:
                continue
            try:
                sid = extract_id(sid)
            except ValueError as e:
                log_err(str(e))
                continue
            download_one(sid, default_out)
            log_ok("文件已保存到: %s" % default_out)

        elif choice == "2":
            kw = ask("搜索关键词: ")
            if not kw:
                continue
            res = search_songs(kw, limit=15)
            if not res:
                log_warn("没有搜索结果")
                continue
            idx = pick(["%s - %s  [%s]" % (s["name"], s["artists"], s["fee"]) for s in res],
                       "选择要下载的歌曲")
            if idx is not None:
                download_one(res[idx]["id"], default_out)

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
            songs = get_artist_hot_songs(artists[ai]["id"])
            batch_download(songs, default_out)

        elif choice == "4":
            pid = ask("歌单 ID 或链接: ")
            if not pid:
                continue
            try:
                pid = extract_id(pid)
            except ValueError as e:
                log_err(str(e))
                continue
            pl = get_playlist_detail(pid)
            if not pl:
                log_warn("歌单不存在")
                continue
            tracks = pl.get("tracks") or []
            log_info("歌单「%s」，共 %d 首" % (pl.get("name", ""), len(tracks)))
            songs = [{"id": t["id"], "name": t.get("name", "")} for t in tracks]
            batch_download(songs, default_out)

        elif choice == "5":
            lists = get_toplist()
            if not lists:
                log_warn("获取榜单失败")
                continue
            idx = pick(["%s (%s)" % (l["name"], l.get("updateFrequency", "")) for l in lists],
                       "选择榜单")
            if idx is None:
                continue
            songs = weapi_post("/playlist/track/all",
                               {"id": lists[idx]["id"], "limit": 200}).get("songs") or []
            batch_download([{"id": s["id"], "name": s.get("name", "")} for s in songs],
                           default_out)

        elif choice == "6":
            songs = get_daily_recommend_songs()
            if not songs:
                log_warn("获取每日推荐失败，请先登录（菜单 7）")
                continue
            batch_download(songs, default_out)

        elif choice == "7":
            print()
            new_cookie = ask("粘贴 Cookie 的 MUSIC_U 值（直接回车跳过）: ")
            if new_cookie:
                cfg["cookie"] = new_cookie
                set_cookie(new_cookie)
                log_ok("Cookie 已保存")
            new_out = ask("下载目录（当前 %s，直接回车跳过）: " % default_out)
            if new_out:
                cfg["output"] = new_out
                default_out = new_out
            save_config(cfg)
            log_ok("设置已保存到 %s" % CONFIG_FILE)

        elif choice == "8" or choice is None:
            break


# ============ 命令行入口 ============
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="netease_downloader",
        description="网易云音乐下载器（纯 Python，无需 ffmpeg）",
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
    return p


def main() -> int:
    args = build_parser().parse_args()

    cfg = load_config()
    cookie = args.cookie or cfg.get("cookie")
    set_cookie(cookie)
    if args.cookie:
        cfg["cookie"] = args.cookie
        save_config(cfg)

    output = args.output or cfg.get("output") or os.path.join(app_dir(), "音乐")

    # 没有任务参数 → 进交互菜单
    if not any([args.song_id, args.search, args.artist, args.playlist,
                args.toplist, args.daily]):
        interactive_menu()
        return 0

    try:
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
            songs = get_artist_hot_songs(artists[0]["id"])
            batch_download(songs, output, level=args.quality)

        elif args.playlist:
            pl = get_playlist_detail(extract_id(args.playlist))
            if not pl:
                log_err("歌单不存在")
                return 1
            songs = [{"id": t["id"], "name": t.get("name", "")}
                     for t in (pl.get("tracks") or [])]
            batch_download(songs, output, level=args.quality)

        elif args.toplist:
            lists = get_toplist()
            if not lists:
                log_err("获取榜单失败")
                return 1
            songs = weapi_post("/playlist/track/all",
                               {"id": lists[0]["id"], "limit": 200}).get("songs") or []
            batch_download([{"id": s["id"], "name": s.get("name", "")} for s in songs],
                           output, level=args.quality)

        elif args.daily:
            songs = get_daily_recommend_songs()
            if not songs:
                log_err("获取每日推荐失败，请确认已登录")
                return 1
            batch_download(songs, output, level=args.quality)

    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except Exception as e:
        log_err("发生错误: %s" % e)
        return 1

    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except Exception as e:
        log_err("未捕获异常: %s" % e)
    _pause_on_exit()
    sys.exit(code)
