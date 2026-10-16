#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐批量下载器
功能：单曲/搜索/歌手/榜单/歌单/每日推荐 批量下载为带封面元数据的 MP3

依赖：requests, pycryptodome, mutagen, ffmpeg
安装：pip install requests pycryptodome mutagen
打包 EXE：python build_exe.py
"""

import argparse
import base64
import datetime
import json
import os
import random
import re
import string
import subprocess
import sys
import tempfile
import time
from typing import Optional, Union

import requests
from Crypto.Cipher import AES
from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPE1
from mutagen.mp3 import MP3

try:
    import colorama
    colorama.init()
    _HAS_COLORAMA = True
except ImportError:
    _HAS_COLORAMA = False


# ============ 资源路径（兼容 PyInstaller 打包） ============
def resource_path(relative: str) -> str:
    """获取资源文件路径：PyInstaller 打包后从 _MEIPASS 取，否则从源码目录取"""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative)


def get_ffmpeg_path() -> Optional[str]:
    """查找 ffmpeg：优先使用打包进 exe 的，其次系统 PATH"""
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled = resource_path(exe_name)
    if os.path.exists(bundled):
        return bundled
    # 回退到系统 PATH
    from shutil import which
    return which("ffmpeg")


# ============ 彩色输出 ============
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"

    _enabled = True

    @classmethod
    def init(cls):
        # colorama 已在 import 时初始化，兼容 Windows 8.1
        if not sys.stdout.isatty():
            cls._enabled = False

    @classmethod
    def _wrap(cls, color, text):
        if not cls._enabled:
            return str(text)
        return "%s%s%s" % (color, text, cls.RESET)

    @classmethod
    def red(cls, t): return cls._wrap(cls.RED, t)
    @classmethod
    def green(cls, t): return cls._wrap(cls.GREEN, t)
    @classmethod
    def yellow(cls, t): return cls._wrap(cls.YELLOW, t)
    @classmethod
    def blue(cls, t): return cls._wrap(cls.BLUE, t)
    @classmethod
    def magenta(cls, t): return cls._wrap(cls.MAGENTA, t)
    @classmethod
    def cyan(cls, t): return cls._wrap(cls.CYAN, t)
    @classmethod
    def gray(cls, t): return cls._wrap(cls.GRAY, t)
    @classmethod
    def bold(cls, t): return cls._wrap(cls.BOLD, t)


def log_info(msg): print(f"{Color.cyan('[INFO]')} {msg}")
def log_ok(msg): print(f"{Color.green('[OK]')} {msg}")
def log_warn(msg): print(f"{Color.yellow('[WARN]')} {msg}")
def log_err(msg): print(f"{Color.red('[ERROR]')} {msg}")


# ============ 网易云 API 加密参数 ============
NONCE = b"0CoJUm6Qyw8W8jud"
PUB_KEY = "010001"
MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725"
    "152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312"
    "ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424"
    "d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)
IV = b"0102030405060708"

BASE_URL = "https://music.163.com"
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".netease_downloader.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}


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
    except Exception as e:
        log_warn(f"保存配置失败: {e}")


def set_cookie(cookie: Optional[str]) -> None:
    base = "appver=2.0.2; os=pc;"
    if cookie:
        cookie = cookie.strip()
        if not cookie.startswith("appver"):
            cookie = f"{base} {cookie}"
        HEADERS["Cookie"] = cookie
    else:
        HEADERS["Cookie"] = base


def get_login_status() -> Optional[dict]:
    """获取当前登录账号信息，未登录返回 None"""
    try:
        result = weapi_post("/w/nuser/account/get", {})
        profile = result.get("profile")
        if profile:
            return profile
    except Exception:
        pass
    return None


# ============ 加密函数 ============
def _aes_encrypt(text: str, key: bytes) -> str:
    pad = 16 - len(text) % 16
    text = text + chr(pad) * pad
    encryptor = AES.new(key, AES.MODE_CBC, IV)
    cipher = encryptor.encrypt(text.encode("utf-8"))
    return base64.b64encode(cipher).decode("utf-8")


def _rsa_encrypt(text: str) -> str:
    text = text[::-1]
    rs = pow(int(text.encode("utf-8").hex(), 16), int(PUB_KEY, 16), int(MODULUS, 16))
    return format(rs, "x").zfill(256)


def _create_secret_key(size: int = 16) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(size))


def encrypted_request(data: dict) -> dict:
    text = json.dumps(data)
    secret_key = _create_secret_key(16)
    params = _aes_encrypt(_aes_encrypt(text, NONCE), secret_key.encode("utf-8"))
    enc_sec_key = _rsa_encrypt(secret_key)
    return {"params": params, "encSecKey": enc_sec_key}


def weapi_post(path: str, data: dict) -> dict:
    url = f"{BASE_URL}/weapi{path}"
    payload = encrypted_request(data)
    resp = requests.post(url, data=payload, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ============ 工具函数 ============
def extract_id(input_str: str) -> str:
    input_str = input_str.strip()
    if input_str.isdigit():
        return input_str
    m = re.search(r"[?&]id=(\d+)", input_str)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)", input_str)
    if m:
        return m.group(1)
    raise ValueError(f"无法从输入中解析 ID: {input_str}")


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_filename(title: str, artist: str) -> str:
    """统一命名：歌曲名 - 歌手名"""
    if artist:
        return safe_filename(f"{title} - {artist}")
    return safe_filename(title)


# ============ API 封装 ============
def get_songs_detail(song_ids: list) -> list:
    """批量获取歌曲详情"""
    c = json.dumps([{"id": sid} for sid in song_ids])
    data = {"c": c, "ids": json.dumps(song_ids)}
    result = weapi_post("/v3/song/detail", data)
    return result.get("songs") or []


def get_songs_url(song_ids: list, level: str = "exhigh") -> list:
    """批量获取歌曲播放链接"""
    data = {"ids": json.dumps(song_ids), "level": level, "encodeType": "aac"}
    result = weapi_post("/song/enhance/player/url/v1", data)
    return result.get("data") or []


def search_songs(keyword: str, limit: int = 10) -> list:
    data = {"s": keyword, "type": 1, "limit": limit, "offset": 0}
    result = weapi_post("/search/get", data)
    songs = (result.get("result") or {}).get("songs", [])
    out = []
    for s in songs:
        artists = "/".join(a["name"] for a in s.get("artists", s.get("ar", [])))
        album = (s.get("album") or s.get("al") or {}).get("name", "")
        fee = s.get("fee", 0)
        fee_label = {0: "免费", 1: "VIP", 4: "付费", 8: "免费"}.get(fee, str(fee))
        out.append({"id": s["id"], "name": s.get("name", ""),
                    "artists": artists, "album": album, "fee": fee_label})
    return out


def search_artists(keyword: str, limit: int = 5) -> list:
    data = {"s": keyword, "type": 100, "limit": limit, "offset": 0}
    result = weapi_post("/search/get", data)
    artists = (result.get("result") or {}).get("artists", [])
    return [{"id": a["id"], "name": a.get("name", "")} for a in artists]


def get_artist_hot_songs(artist_id: str) -> list:
    data = {"id": artist_id}
    result = weapi_post("/artist/top/song", data)
    songs = result.get("songs") or []
    out = []
    for s in songs:
        artists = "/".join(a["name"] for a in s.get("ar", []))
        album = (s.get("al") or {}).get("name", "")
        out.append({"id": s["id"], "name": s.get("name", ""),
                    "artists": artists, "album": album})
    return out


def get_playlist_detail(playlist_id: str) -> dict:
    data = {"id": playlist_id, "n": 100000, "s": 8}
    result = weapi_post("/v6/playlist/detail", data)
    return result.get("playlist") or {}


def get_toplist() -> list:
    """获取所有榜单"""
    result = weapi_post("/toplist", {})
    lists = result.get("list") or []
    return [{"id": l["id"], "name": l.get("name", ""),
             "updateFrequency": l.get("updateFrequency", ""),
             "playCount": l.get("playCount", 0)} for l in lists]


def get_daily_recommend_songs() -> list:
    """获取每日推荐歌曲（需登录）"""
    result = weapi_post("/v1/discovery/recommend/songs", {})
    data = result.get("data") or {}
    songs = data.get("dailySongs") or []
    out = []
    for s in songs:
        artists = "/".join(a["name"] for a in s.get("ar", []))
        album = (s.get("al") or {}).get("name", "")
        out.append({"id": s["id"], "name": s.get("name", ""),
                    "artists": artists, "album": album})
    return out


# ============ 下载管线 ============
def download_file(url: str, dest: str) -> bool:
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            if pct != last_pct and pct % 10 == 0:
                                print(f"\r  {Color.cyan('下载中...')} {pct}%", end="", flush=True)
                                last_pct = pct
            print(f"\r  {Color.green('下载完成')} ({downloaded/1024/1024:.1f} MB)          ")
            return True
    except Exception as e:
        print(f"\r  {Color.red('下载失败')}: {e}                              ")
        return False


def convert_to_mp3(src: str, dest: str, bitrate: str = "320k") -> bool:
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        log_err("未找到 ffmpeg，请先安装 ffmpeg 并加入系统 PATH")
        return False
    cmd = [ffmpeg, "-y", "-i", src, "-c:a", "libmp3lame",
           "-b:a", bitrate, "-map_metadata", "-1", dest]
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  {Color.red('ffmpeg 转换失败')}: {e}")
        return False


def set_mp3_tags(mp3_path: str, info: dict, cover_data: Optional[bytes]) -> None:
    try:
        audio = MP3(mp3_path)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        if info.get("name"):
            tags.add(TIT2(encoding=3, text=info["name"]))
        artists = "/".join(a["name"] for a in info.get("ar", []))
        if artists:
            tags.add(TPE1(encoding=3, text=artists))
        album = (info.get("al") or {}).get("name")
        if album:
            tags.add(TALB(encoding=3, text=album))
        pub_time = (info.get("publishTime") or (info.get("al") or {}).get("publishTime"))
        if pub_time:
            try:
                year = datetime.datetime.fromtimestamp(pub_time / 1000).year
                tags.add(TDRC(encoding=3, text=str(year)))
            except Exception:
                pass
        if cover_data:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data))
        tags.save(mp3_path)
    except Exception as e:
        print(f"  {Color.yellow('写入元数据失败')}（不影响播放）: {e}")


def download_cover(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.content
    except Exception:
        pass
    return None


def download_one_song(song_id: str, output_dir: str, level: str = "exhigh",
                      bitrate: str = "320k", detail: Optional[dict] = None) -> Optional[str]:
    """下载单曲，返回最终文件路径或 None"""
    if detail is None:
        details = get_songs_detail([song_id])
        if not details:
            return None
        detail = details[0]

    name = detail.get("name", f"song_{song_id}")
    artists = "/".join(a["name"] for a in detail.get("ar", []))
    album = (detail.get("al") or {}).get("name", "")
    cover_url = (detail.get("al") or {}).get("picUrl", "")

    # 获取播放链接（尝试降级音质）
    url_info = None
    song_url = None
    for lv in (level, "higher", "standard"):
        url_list = get_songs_url([song_id], level=lv)
        if url_list:
            url_info = url_list[0]
            song_url = url_info.get("url")
            if song_url:
                break

    if not song_url:
        log_warn(f"无法获取「{name}」的下载链接（VIP/版权/区域限制）")
        return None

    os.makedirs(output_dir, exist_ok=True)
    filename = build_filename(name, artists)
    final_path = os.path.join(output_dir, f"{filename}.mp3")

    if os.path.exists(final_path):
        log_info(f"已存在，跳过: {filename}.mp3")
        return final_path

    print(f"  {Color.magenta(name)} - {artists}  ({Color.gray(album)})")
    print(f"    链接: {url_info.get('type', '?')} {url_info.get('br', 0)//1000}kbps")

    tmp_raw = os.path.join(tempfile.gettempdir(), f"netease_{song_id}.tmp")
    if not download_file(song_url, tmp_raw):
        return None

    ok = convert_to_mp3(tmp_raw, final_path, bitrate=bitrate)
    try:
        os.remove(tmp_raw)
    except OSError:
        pass
    if not ok:
        return None

    cover_data = download_cover(cover_url)
    set_mp3_tags(final_path, detail, cover_data)
    return final_path


def batch_download(songs: list, output_dir: str, level: str = "exhigh",
                   bitrate: str = "320k") -> None:
    """批量下载歌曲列表，songs 为 [{"id":..., "name":..., ...}, ...]"""
    total = len(songs)
    if total == 0:
        log_warn("没有可下载的歌曲")
        return

    # 先批量获取详情（每批 100 首）
    all_ids = [str(s["id"]) for s in songs]
    detail_map = {}
    for i in range(0, len(all_ids), 100):
        batch = all_ids[i:i+100]
        details = get_songs_detail(batch)
        for d in details:
            detail_map[str(d["id"])] = d
        time.sleep(0.3)

    log_info(f"开始批量下载，共 {Color.bold(total)} 首，目标目录: {output_dir}")
    success, fail, skip = 0, 0, 0
    for idx, s in enumerate(songs, 1):
        sid = str(s["id"])
        detail = detail_map.get(sid)
        if detail is None:
            log_warn(f"[{idx}/{total}] 跳过（无详情）: {s.get('name', sid)}")
            fail += 1
            continue
        print(f"\n{Color.bold(f'[{idx}/{total}]')} ", end="")
        path = download_one_song(sid, output_dir, level=level, bitrate=bitrate, detail=detail)
        if path:
            success += 1
        else:
            fail += 1
        time.sleep(0.2)

    print()
    log_ok(f"批量下载完成: 成功 {Color.green(success)} 首, 失败 {Color.red(fail)} 首")


# ============ 交互菜单 ============
def select_from_list(items: list, label: str = "请选择") -> Optional[int]:
    for i, item in enumerate(items, 1):
        print(f"  {Color.cyan(f'[{i}]')} {item}")
    try:
        choice = input(f"\n{label} (1-{len(items)}, q 退出): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if choice.lower() == "q":
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(items):
        return int(choice) - 1
    return None


def interactive_menu(args) -> None:
    cfg = load_config()
    cookie = args.cookie or cfg.get("cookie")
    set_cookie(cookie)

    while True:
        print(f"\n{Color.bold(Color.magenta('========== 网易云音乐下载器 =========='))}")
        profile = get_login_status()
        if profile:
            log_ok(f"已登录: {Color.bold(profile.get('nickname', '?'))}")
        else:
            log_warn("未登录（VIP/每日推荐功能不可用）")

        print(f"""
  {Color.cyan('1')}. 单曲下载
  {Color.cyan('2')}. 搜索下载
  {Color.cyan('3')}. 歌手热门
  {Color.cyan('4')}. 歌单下载
  {Color.cyan('5')}. 榜单下载
  {Color.cyan('6')}. 每日推荐（需登录）
  {Color.cyan('7')}. 设置登录
  {Color.cyan('0')}. 退出
""")
        choice = input(f"{Color.bold('输入编号: ')}").strip()

        if choice == "1":
            sid = input("歌曲 ID 或链接: ").strip()
            if sid:
                download_one_song(extract_id(sid), args.output, args.quality, args.bitrate)
                print(f"\n{Color.green('完成')}")
        elif choice == "2":
            kw = input("搜索关键词: ").strip()
            if kw:
                results = search_songs(kw, limit=args.search_limit)
                if not results:
                    log_warn("未找到相关歌曲")
                    continue
                items = ["%s - %s  | %s  | %s" % (s['name'], s['artists'], s['album'], s['fee'])
                         for s in results]
                sel = select_from_list(items, "选择歌曲")
                if sel is not None:
                    batch_download([results[sel]], args.output, args.quality, args.bitrate)
        elif choice == "3":
            kw = input("歌手名: ").strip()
            if kw:
                artists = search_artists(kw)
                if not artists:
                    log_warn("未找到相关歌手")
                    continue
                items = [a["name"] for a in artists]
                sel = select_from_list(items, "选择歌手")
                if sel is not None:
                    aid = artists[sel]["id"]
                    log_info("正在获取「%s」的热门歌曲..." % artists[sel]['name'])
                    hot = get_artist_hot_songs(str(aid))
                    log_info("共 %d 首" % len(hot))
                    sub = input("下载前几首？(回车=全部): ").strip()
                    if sub.isdigit():
                        hot = hot[:int(sub)]
                    batch_download(hot, os.path.join(args.output, "歌手_" + artists[sel]['name']),
                                   args.quality, args.bitrate)
        elif choice == "4":
            pid = input("歌单 ID 或链接: ").strip()
            if pid:
                pid = extract_id(pid)
                log_info("获取歌单信息...")
                pl = get_playlist_detail(pid)
                if not pl:
                    log_err("获取歌单失败")
                    continue
                name = pl.get("name", "歌单")
                track_ids = [t["id"] for t in pl.get("trackIds", [])]
                log_info("歌单「%s」共 %d 首" % (name, len(track_ids)))
                sub = input("下载前几首？(回车=全部): ").strip()
                if sub.isdigit():
                    track_ids = track_ids[:int(sub)]
                songs = [{"id": tid} for tid in track_ids]
                batch_download(songs, os.path.join(args.output, "歌单_" + name),
                               args.quality, args.bitrate)
        elif choice == "5":
            toplist = get_toplist()
            items = ["%s  (%s)" % (t['name'], t['updateFrequency']) for t in toplist]
            sel = select_from_list(items, "选择榜单")
            if sel is not None:
                tid = str(toplist[sel]["id"])
                log_info("获取榜单「%s」..." % toplist[sel]['name'])
                pl = get_playlist_detail(tid)
                track_ids = [t["id"] for t in pl.get("trackIds", [])]
                songs = [{"id": tid2} for tid2 in track_ids]
                batch_download(songs, os.path.join(args.output, "榜单_" + toplist[sel]['name']),
                               args.quality, args.bitrate)
        elif choice == "6":
            if not profile:
                log_err("请先在第 7 项设置登录")
                continue
            log_info("获取每日推荐...")
            daily = get_daily_recommend_songs()
            if not daily:
                log_warn("未获取到每日推荐")
                continue
            log_info("共 %d 首推荐歌曲" % len(daily))
            batch_download(daily, os.path.join(args.output, "每日推荐"),
                           args.quality, args.bitrate)
        elif choice == "7":
            ck = input("粘贴 Cookie（MUSIC_U=...）: ").strip()
            if ck:
                cfg["cookie"] = ck
                save_config(cfg)
                set_cookie(ck)
                log_ok("已保存登录信息")
        elif choice == "0":
            log_info("再见！")
            break
        else:
            log_warn("无效编号")


# ============ CLI 入口 ============
def main():
    Color.init()
    parser = argparse.ArgumentParser(
        description=Color.magenta("网易云音乐批量下载器") + " — 单曲/搜索/歌手/榜单/歌单/每日推荐",
        epilog="""
示例:
  交互菜单:  python3 netease_music_downloader.py
  单曲下载:  python3 netease_music_downloader.py 259138 -o ./音乐
  搜索下载:  python3 netease_music_downloader.py --search 青花瓷
  歌手下载:  python3 netease_music_downloader.py --artist 周杰伦
  歌单下载:  python3 netease_music_downloader.py --playlist 123456789
  榜单下载:  python3 netease_music_downloader.py --toplist
  每日推荐:  python3 netease_music_downloader.py --daily --cookie 'MUSIC_U=xxx'
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("song", nargs="?", help="歌曲 ID 或 URL")
    parser.add_argument("-o", "--output", default="downloads", help="输出目录（默认 downloads）")
    parser.add_argument("-q", "--quality", default="exhigh",
                        choices=["standard", "higher", "exhigh", "lossless", "hires"],
                        help="音质等级（默认 exhigh）")
    parser.add_argument("--bitrate", default="320k", help="输出 MP3 比特率（默认 320k）")
    parser.add_argument("--cookie", default=None,
                        help="登录 Cookie（也可通过环境变量 NETEASE_COOKIE 设置）")
    parser.add_argument("--search", metavar="关键词", help="搜索歌曲并下载")
    parser.add_argument("--artist", metavar="歌手名", help="下载歌手热门歌曲")
    parser.add_argument("--playlist", metavar="歌单ID/URL", help="下载歌单全部歌曲")
    parser.add_argument("--toplist", action="store_true", help="列出榜单并选择下载")
    parser.add_argument("--daily", action="store_true", help="下载每日推荐（需登录）")
    parser.add_argument("--search-limit", type=int, default=10, help="搜索结果数量")
    parser.add_argument("--limit", type=int, default=0, help="下载前 N 首（0=全部）")
    args = parser.parse_args()

    # Cookie 优先级：CLI > 环境变量 > 配置文件
    cfg = load_config()
    cookie = args.cookie or os.environ.get("NETEASE_COOKIE") or cfg.get("cookie")
    set_cookie(cookie)

    # 如果没有任何模式参数且没有单曲参数，进入交互菜单
    no_mode = not any([args.search, args.artist, args.playlist,
                       args.toplist, args.daily, args.song])
    if no_mode:
        interactive_menu(args)
        return

    # 单曲下载
    if args.song:
        download_one_song(extract_id(args.song), args.output, args.quality, args.bitrate)
        return

    # 搜索
    if args.search:
        results = search_songs(args.search, limit=args.search_limit)
        if not results:
            log_warn(f"未找到与「{args.search}」相关的歌曲")
            return
        items = [f"{s['name']} - {s['artists']}  | 专辑: {s['album']}  | {s['fee']}"
                 for s in results]
        sel = select_from_list(items, "选择要下载的歌曲")
        if sel is not None:
            batch_download([results[sel]], args.output, args.quality, args.bitrate)
        return

    # 歌手
    if args.artist:
        artists = search_artists(args.artist)
        if not artists:
            log_warn(f"未找到歌手「{args.artist}」")
            return
        if len(artists) == 1:
            aid = artists[0]["id"]
            aname = artists[0]["name"]
        else:
            items = [a["name"] for a in artists]
            sel = select_from_list(items, "选择歌手")
            if sel is None:
                return
            aid = artists[sel]["id"]
            aname = artists[sel]["name"]
        hot = get_artist_hot_songs(str(aid))
        log_info(f"「{aname}」热门歌曲共 {len(hot)} 首")
        if args.limit > 0:
            hot = hot[:args.limit]
        batch_download(hot, os.path.join(args.output, f"歌手_{aname}"),
                       args.quality, args.bitrate)
        return

    # 歌单
    if args.playlist:
        pid = extract_id(args.playlist)
        pl = get_playlist_detail(pid)
        if not pl:
            log_err("获取歌单失败")
            return
        name = pl.get("name", "歌单")
        track_ids = [t["id"] for t in pl.get("trackIds", [])]
        log_info(f"歌单「{name}」共 {len(track_ids)} 首")
        if args.limit > 0:
            track_ids = track_ids[:args.limit]
        songs = [{"id": tid} for tid in track_ids]
        batch_download(songs, os.path.join(args.output, f"歌单_{name}"),
                       args.quality, args.bitrate)
        return

    # 榜单
    if args.toplist:
        toplist = get_toplist()
        items = [f"{t['name']}  ({t['updateFrequency']})" for t in toplist]
        sel = select_from_list(items, "选择榜单")
        if sel is not None:
            tid = str(toplist[sel]["id"])
            pl = get_playlist_detail(tid)
            track_ids = [t["id"] for t in pl.get("trackIds", [])]
            if args.limit > 0:
                track_ids = track_ids[:args.limit]
            songs = [{"id": tid2} for tid2 in track_ids]
            batch_download(songs, os.path.join(args.output, f"榜单_{toplist[sel]['name']}"),
                           args.quality, args.bitrate)
        return

    # 每日推荐
    if args.daily:
        profile = get_login_status()
        if not profile:
            log_err("下载每日推荐需要先登录，请使用 --cookie 传入 Cookie 或在交互菜单中设置")
            return
        log_info(f"已登录: {profile.get('nickname')}")
        daily = get_daily_recommend_songs()
        if not daily:
            log_warn("未获取到每日推荐")
            return
        log_info(f"每日推荐共 {len(daily)} 首")
        if args.limit > 0:
            daily = daily[:args.limit]
        batch_download(daily, os.path.join(args.output, "每日推荐"),
                       args.quality, args.bitrate)
        return


if __name__ == "__main__":
    main()
