#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
酷狗音乐下载器（Windows XP 兼容版）

- 纯 Python，只依赖 requests，不依赖 ffmpeg / mutagen
- 下载 MP3（有 320k / FLAC 就优先，拿不到自动降到 128k）
- 自动保存同名 .lrc 歌词，手工写入 ID3v2 标签与封面
- 兼容 Python 3.4（Windows XP SP3 能运行的最后一个 Python 3 版本）
- 单文件 32 位 exe，可在 XP / Win7 / Win8 / Win10 / Win11 上运行

支持：单曲 / 搜索 / 榜单
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import struct
import sys
import time
import traceback

import requests

APP_VERSION = "1.0.0"


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


CONFIG_FILE = os.path.join(app_dir(), ".kugou_downloader.json")
ERROR_LOG = os.path.join(app_dir(), "kugou_downloader_error.log")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kugou.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

SEARCH_URL = "https://songsearch.kugou.com/song_search_v2"
INFO_URL = "https://m.kugou.com/app/i/getSongInfo.php"
PLAY_URL = "https://wwwapi.kugou.com/play/songinfo"
LYRIC_SEARCH_URL = "https://krcs.kugou.com/search"
LYRIC_DOWN_URL = "https://lyrics.kugou.com/download"
RANK_LIST_URL = "https://m.kugou.com/rank/list"
RANK_INFO_URL = "https://m.kugou.com/rank/info/"

SIGN_SECRET = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"


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


def default_output_dir():
    return os.path.join(app_dir(), "音乐")


def _device_ids():
    """酷狗服务端要求稳定的 mid / dfid，存在配置里复用"""
    cfg = load_config()
    changed = False
    mid = cfg.get("mid")
    if not mid:
        mid = hashlib.md5(("%s-%s" % (time.time(), os.name)).encode("utf-8")).hexdigest()
        cfg["mid"] = mid
        changed = True
    dfid = cfg.get("dfid")
    if not dfid:
        rnd = hashlib.md5(("%s-dfid" % time.time()).encode("utf-8")).hexdigest()
        dfid = "%s-%s-%s-%s-%s" % (rnd[:8], rnd[8:12], rnd[12:16],
                                   rnd[16:20], rnd[20:32])
        cfg["dfid"] = dfid
        changed = True
    uuid = cfg.get("uuid")
    if not uuid:
        uuid = hashlib.md5(("uuid-%s" % time.time()).encode("utf-8")).hexdigest()
        cfg["uuid"] = uuid
        changed = True
    if changed:
        save_config(cfg)
    return cfg["mid"], cfg["dfid"], cfg["uuid"]


def set_cookie(cookie):
    if not cookie:
        return
    cookie = cookie.strip()
    HEADERS["Cookie"] = cookie
    SESSION.headers["Cookie"] = cookie


# ==================== 网络 ====================
def http_json(url, params=None, timeout=(10, 30)):
    r = SESSION.get(url, params=params, timeout=timeout,
                    verify=ca_bundle())
    try:
        r.raise_for_status()
        return r.json()
    finally:
        r.close()


# ==================== 工具 ====================
def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def build_filename(title, artists):
    if artists:
        name = safe_filename("%s - %s" % (title, artists))
    else:
        name = safe_filename(title)
    # XP 的完整路径限制 260 字符，文件名过长会直接保存失败
    return name[:110]


def fix_image_url(url, size="480"):
    """酷狗图片地址里带 {size} 占位符，替换成目标尺寸"""
    if not url:
        return ""
    for token in ("{size}", "%7Bsize%7D"):
        if token in url:
            return url.replace(token, size)
    return url


# ==================== API：搜索 ====================
def search_songs(keyword, limit=10, page=1):
    params = {
        "keyword": keyword,
        "page": page,
        "pagesize": limit,
        "platform": "WebFilter",
        "userid": 0,
        "clientver": 2000,
        "iscorrection": 1,
        "privilege_filter": 0,
        "filter": 10,
    }
    d = http_json(SEARCH_URL, params)
    lists = (d.get("data") or {}).get("lists") or []
    out = []
    for s in lists:
        out.append({
            "hash": s.get("FileHash") or "",
            "hash_high": s.get("HQFileHash") or "",
            "hash_sq": s.get("SQFileHash") or "",
            "name": s.get("SongName") or "",
            "singer": s.get("SingerName") or "",
            "album": s.get("AlbumName") or "",
            "album_id": str(s.get("AlbumID") or ""),
            "duration": int(s.get("Duration") or 0),
            "cover": fix_image_url(s.get("Image") or s.get("AlbumImage") or ""),
            "file_size": int(s.get("FileSize") or 0),
            "privilege": s.get("Privilege", 0),
        })
    return out


# ==================== API：歌曲信息 ====================
def get_song_info(song_hash):
    try:
        d = http_json(INFO_URL, {"cmd": "playInfo", "hash": song_hash},
                      timeout=(5, 15))
        if d.get("status") == 1 or d.get("errcode") == 0:
            return d
    except Exception:
        pass
    return {}


def _signed_play_url(album_audio_id, mid, dfid, uuid):
    """官方签名接口：能拿到 320k / FLAC，境外 IP 常被风控，失败就返回空"""
    if not album_audio_id:
        return {}
    params = {
        "srcappid": "2919",
        "clientver": "20000",
        "clienttime": str(int(time.time() * 1000)),
        "mid": mid,
        "uuid": uuid,
        "dfid": dfid,
        "appid": "1014",
        "platid": "4",
        "encode_album_audio_id": str(album_audio_id),
        "token": "",
        "userid": "0",
    }
    raw = "".join("%s=%s" % (k, params[k]) for k in sorted(params))
    params["signature"] = hashlib.md5(
        (SIGN_SECRET + raw + SIGN_SECRET).encode("utf-8")).hexdigest()
    try:
        d = http_json(PLAY_URL, params, timeout=(5, 12))
    except Exception:
        return {}
    data = d.get("data") or {}
    url = data.get("play_url") or data.get("play_backup_url")
    if not url:
        return {}
    return {
        "url": url,
        "bitrate": int(data.get("bitrate") or 0),
        "ext": (data.get("extname") or "mp3").lower(),
        "size": int(data.get("filesize") or 0),
    }


def get_song_url(song):
    """优先高音质，逐级降级：FLAC -> 320k -> 128k"""
    mid, dfid, uuid = _device_ids()

    # 1) 官方签名接口（能拿到 320k / FLAC）
    base = get_song_info(song.get("hash") or "")
    best = _signed_play_url(base.get("album_audio_id"), mid, dfid, uuid)
    if best.get("url"):
        return best

    # 2) 旧移动端接口，逐个 hash 试探，取码率最高的一个
    candidates = []
    for h in (song.get("hash_sq"), song.get("hash_high"),
              song.get("hash"), song.get("file_hash")):
        if h and h not in candidates:
            candidates.append(h)

    best = {}
    seen_urls = []
    for h in candidates:
        info = base if h == (song.get("hash") or "") and base else get_song_info(h)
        url = info.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.append(url)
        item = {
            "url": url,
            "bitrate": int(info.get("bitRate") or 0),
            "ext": (info.get("extName") or "mp3").lower(),
            "size": int(info.get("fileSize") or 0),
            "info": info,
        }
        if not best or item["bitrate"] > best.get("bitrate", 0):
            best = item
    return best


# ==================== API：榜单 ====================
def get_rank_list():
    d = http_json(RANK_LIST_URL, {"json": "true"})
    ranks = (d.get("rank") or {}).get("list") or []
    return [{
        "rankid": str(r.get("rankid") or ""),
        "name": r.get("rankname") or "",
        "count": r.get("rank_count") or r.get("count") or 0,
    } for r in ranks]


def get_rank_songs(rankid, limit=30):
    params = {"rankid": rankid, "page": 1, "pagesize": limit, "json": "true"}
    d = http_json(RANK_INFO_URL, params)
    lst = (d.get("songs") or {}).get("list") or []
    out = []
    for s in lst:
        duration = int(s.get("duration") or 0)
        out.append({
            "hash": s.get("hash") or "",
            "hash_high": s.get("hash_high") or s.get("320hash") or "",
            "hash_sq": s.get("hash_super") or s.get("sqhash") or "",
            "name": s.get("songname") or "",
            "singer": s.get("singername") or (s.get("filename") or "").split(" - ")[0],
            "album": "",
            "album_id": str(s.get("album_id") or ""),
            "duration": duration,
            "cover": "",
            "file_size": int(s.get("filesize") or 0),
            "privilege": s.get("privilege", 0),
        })
    # 酷狗会忽略 pagesize，这里自己截断
    return out[:limit]


# ==================== API：歌词 ====================
def _norm_name(text):
    return re.sub(r"[\s（）()\[\]【】\-_]", "", text or "").lower()


def get_lyric(song_hash, duration=0, name="", singer=""):
    """返回 LRC 文本；无歌词或失败返回空串"""
    if not song_hash:
        return ""
    try:
        d = http_json(LYRIC_SEARCH_URL, {
            "ver": 1, "man": "yes", "client": "mobi", "keyword": "",
            "duration": duration, "hash": song_hash,
        }, timeout=(5, 15))
    except Exception:
        return ""

    cands = d.get("candidates") or []
    if not cands:
        return ""

    # 酷狗返回的候选里有 live / DJ / 翻唱版本，先按歌名+歌手匹配，再比时长
    n_name = _norm_name(name)
    n_singer = _norm_name(singer)
    scored = []
    for c in cands:
        score = 0
        c_name = _norm_name(c.get("song"))
        c_singer = _norm_name(c.get("singer"))
        if n_name and c_name:
            if c_name == n_name:
                score += 5
            elif c_name in n_name or n_name in c_name:
                score += 2
        if n_singer and c_singer and (c_singer in n_singer
                                      or n_singer in c_singer):
            score += 3
        c_dur = (c.get("duration") or 0) / 1000.0
        diff = abs(c_dur - duration) if duration else 0
        scored.append((-score, diff, c))
    if not scored:
        return ""
    scored.sort(key=lambda x: (x[0], x[1]))
    best = scored[0][2]

    try:
        r = http_json(LYRIC_DOWN_URL, {
            "ver": 1, "client": "pc", "id": best.get("id"),
            "accesskey": best.get("accesskey"), "fmt": "lrc",
            "charset": "utf8",
        }, timeout=(5, 15))
    except Exception:
        return ""

    content = r.get("content") or ""
    if not content:
        return ""
    try:
        text = base64.b64decode(content).decode("utf-8", "replace")
    except Exception:
        return ""
    return text.replace("\ufeff", "").replace("\r\n", "\n")


def save_lyric(lrc_path, text):
    """保存为 UTF-8 带 BOM 的 .lrc（千千静听 / 酷狗等播放器都能识别）"""
    if not text or not text.strip():
        return False
    try:
        with open(lrc_path, "wb") as f:
            f.write(b"\xef\xbb\xbf")
            f.write(text.replace("\r\n", "\n").encode("utf-8"))
        return True
    except Exception:
        return False


def save_lyric_for(song_hash, duration, audio_path, name="", singer=""):
    """为已下载的音频保存同名 .lrc，已有歌词则跳过"""
    lrc_path = os.path.splitext(audio_path)[0] + ".lrc"
    if os.path.exists(lrc_path) and os.path.getsize(lrc_path) > 10:
        return
    if save_lyric(lrc_path, get_lyric(song_hash, duration, name, singer)):
        log_ok("歌词: %s" % os.path.basename(lrc_path))


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


def write_tags(mp3_path, name, artists, album, cover=None, year=None):
    """手工写 ID3v2.3 标签：标题 / 歌手 / 专辑 / 年份 / 封面"""
    try:
        frames = b""
        if name:
            frames += _id3_frame("TIT2", _utf16_text(name))
        if artists:
            frames += _id3_frame("TPE1", _utf16_text(artists))
        if album:
            frames += _id3_frame("TALB", _utf16_text(album))
        if year:
            frames += _id3_frame("TYER", _utf16_text(str(year)))
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
        return True
    except Exception as e:
        log_warn("写入标签失败（不影响播放）: %s" % e)
        return False


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


def download_cover(url):
    if not url:
        return None
    try:
        r = SESSION.get(url, timeout=(10, 20), verify=ca_bundle())
        try:
            if r.status_code == 200 and r.content and len(r.content) < 2 * 1024 * 1024:
                return r.content
        finally:
            r.close()
    except Exception:
        pass
    return None


def download_one(song, output_dir):
    song_hash = song.get("hash") or ""
    if not song_hash:
        log_warn("缺少歌曲 hash，无法下载")
        return None

    name = song.get("name") or ""
    singer = song.get("singer") or ""
    album = song.get("album") or ""
    cover_url = song.get("cover") or ""
    duration = song.get("duration") or 0

    got = get_song_url(song)
    if not got.get("url"):
        # 用详情补齐展示信息（搜索结果可能缺字段）
        info = get_song_info(song_hash)
        name = name or info.get("songName") or ""
        singer = singer or info.get("author_name") or ""
        album = album or info.get("album_name") or ""
        log_warn("无法获取「%s」下载链接（VIP / 版权 / 地区限制）" % (name or song_hash))
        return None

    info = got.get("info") or {}
    name = name or info.get("songName") or ""
    singer = singer or info.get("author_name") or ""
    album = album or info.get("album_name") or ""
    if not cover_url:
        cover_url = fix_image_url(info.get("album_img") or "")
    if not duration:
        duration = int((info.get("timeLength") or 0) / 1000)

    ext = got.get("ext") or "mp3"
    if ext not in ("mp3", "flac", "m4a"):
        ext = "mp3"

    if not os.path.isdir(output_dir):
        try:
            os.makedirs(output_dir)
        except Exception:
            pass

    final_path = os.path.join(output_dir,
                              "%s.%s" % (build_filename(name or song_hash, singer), ext))
    if os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
        log_info("已存在，跳过: %s" % os.path.basename(final_path))
        save_lyric_for(song_hash, duration, final_path, name, singer)
        return final_path

    print("  %s - %s  (%s)" % (name, singer, album or "未知专辑"))
    print("    格式: %s  %dkbps" % (ext, got.get("bitrate") or 0))

    if not download_stream(got["url"], final_path):
        try:
            os.remove(final_path)
        except OSError:
            pass
        return None

    if ext == "mp3":
        write_tags(final_path, name, singer, album,
                   download_cover(cover_url))
    save_lyric_for(song_hash, duration, final_path, name, singer)
    return final_path


def batch_download(songs, output_dir):
    total = len(songs)
    if total == 0:
        log_warn("没有可下载的歌曲")
        return
    ok = 0
    for i, s in enumerate(songs):
        print("\n[%d/%d]" % (i + 1, total))
        try:
            if download_one(s, output_dir):
                ok += 1
        except Exception as e:
            log_err("下载失败: %s" % e)
            log_traceback()
    print("\n完成：成功 %d / %d" % (ok, total))


# ==================== 交互菜单 ====================
def _ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("")
        return ""


def _pick_song(songs):
    if not songs:
        log_warn("没有搜索结果")
        return None
    for i, s in enumerate(songs):
        priv = "免费" if s.get("privilege") in (0, 8) else "VIP"
        print("  %2d. %s - %s  [%s]" % (i + 1, s.get("name"), s.get("singer"), priv))
    sel = _ask("选择序号（0 取消）: ")
    if not sel.isdigit():
        return None
    idx = int(sel)
    if idx < 1 or idx > len(songs):
        return None
    return songs[idx - 1]


def interactive_menu(output_dir, cookie=""):
    while True:
        print("")
        print("=" * 48)
        print(" 酷狗音乐下载器 v%s（XP 兼容版）" % APP_VERSION)
        print("=" * 48)
        print(" 1. 搜索并下载")
        print(" 2. 下载单曲（链接 / 哈希）")
        print(" 3. 下载榜单")
        print(" 4. 设置")
        print(" 0. 退出")
        choice = _ask("请选择: ")

        if choice == "0":
            return
        elif choice == "1":
            kw = _ask("搜索关键词: ")
            if not kw:
                continue
            try:
                songs = search_songs(kw, limit=15)
            except Exception as e:
                log_err("搜索失败: %s" % e)
                log_traceback()
                continue
            song = _pick_song(songs)
            if song:
                try:
                    download_one(song, output_dir)
                except Exception as e:
                    log_err("下载失败: %s" % e)
                    log_traceback()
        elif choice == "2":
            text = _ask("歌曲链接或 hash: ")
            song = parse_song_input(text)
            if song:
                try:
                    download_one(song, output_dir)
                except Exception as e:
                    log_err("下载失败: %s" % e)
                    log_traceback()
        elif choice == "3":
            try:
                ranks = get_rank_list()
            except Exception as e:
                log_err("获取榜单失败: %s" % e)
                continue
            for i, r in enumerate(ranks):
                print("  %2d. %s" % (i + 1, r["name"]))
            sel = _ask("选择榜单序号（0 取消）: ")
            if not sel.isdigit() or int(sel) < 1 or int(sel) > len(ranks):
                continue
            rank = ranks[int(sel) - 1]
            num = _ask("下载前 N 首（默认 10）: ")
            limit = int(num) if num.isdigit() and int(num) > 0 else 10
            try:
                songs = get_rank_songs(rank["rankid"], limit)
                batch_download(songs, output_dir)
            except Exception as e:
                log_err("榜单下载失败: %s" % e)
                log_traceback()
        elif choice == "4":
            print("  当前下载目录: %s" % output_dir)
            new_dir = _ask("新的下载目录（回车保持不变）: ")
            if new_dir:
                output_dir = new_dir
                cfg = load_config()
                cfg["output_dir"] = output_dir
                save_config(cfg)
            print("  当前 Cookie: %s" % ("已设置" if cookie else "未设置"))
            new_cookie = _ask("新的 Cookie（回车保持不变）: ")
            if new_cookie:
                cookie = new_cookie
                cfg = load_config()
                cfg["cookie"] = cookie
                save_config(cfg)
                set_cookie(cookie)
        else:
            print("  无效选项")


# ==================== 输入解析 ====================
def parse_song_input(text):
    """支持 32 位 hash、酷狗分享链接（含 hash= 参数）"""
    if not text:
        return None
    text = text.strip()
    h = ""
    if re.match(r"^[0-9A-Fa-f]{32}$", text):
        h = text.upper()
    else:
        m = re.search(r"[?&#]hash=([0-9A-Fa-f]{32})", text)
        if m:
            h = m.group(1).upper()
        else:
            m = re.search(r"([0-9A-Fa-f]{32})", text)
            if m:
                h = m.group(1).upper()
    if not h:
        log_warn("无法识别链接或 hash: %s" % text)
        return None

    info = get_song_info(h)
    if not info:
        log_warn("查询歌曲信息失败，可能是无效 hash")
        return None
    return {
        "hash": h,
        "hash_high": info.get("hash_high") or "",
        "hash_sq": info.get("sqhash") or info.get("hash_super") or "",
        "name": info.get("songName") or "",
        "singer": info.get("author_name") or "",
        "album": info.get("album_name") or "",
        "album_id": str(info.get("albumid") or ""),
        "duration": int((info.get("timeLength") or 0) / 1000),
        "cover": fix_image_url(info.get("album_img") or ""),
        "file_size": int(info.get("fileSize") or 0),
        "privilege": info.get("privilege", 0),
    }


# ==================== 命令行 ====================
def build_parser():
    p = argparse.ArgumentParser(
        description="酷狗音乐下载器 v%s（XP 兼容版）" % APP_VERSION)
    p.add_argument("song", nargs="?", help="歌曲链接或 hash")
    p.add_argument("-o", "--output", default="", help="输出目录")
    p.add_argument("--search", metavar="关键词", help="搜索并下载")
    p.add_argument("--rank", metavar="榜单ID", help="下载指定榜单（默认 TOP500）")
    p.add_argument("--list-ranks", action="store_true", help="列出所有榜单")
    p.add_argument("--limit", type=int, default=0, help="数量限制")
    p.add_argument("--cookie", default="", help="酷狗 Cookie")
    p.add_argument("--version", action="store_true", help="显示版本")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print("酷狗音乐下载器 v%s" % APP_VERSION)
        return 0

    cfg = load_config()
    output_dir = args.output or cfg.get("output_dir") or default_output_dir()
    cookie = args.cookie or cfg.get("cookie") or ""
    if cookie:
        set_cookie(cookie)

    try:
        if args.list_ranks:
            for r in get_rank_list():
                print("%s  %s" % (r["rankid"], r["name"]))
            return 0

        if args.search:
            limit = args.limit or 10
            songs = search_songs(args.search, limit=limit)
            if not songs:
                log_warn("没有搜索结果")
                return 1
            batch_download(songs, output_dir)
            return 0

        if args.rank is not None:
            rankid = args.rank or "8888"
            songs = get_rank_songs(rankid, args.limit or 20)
            batch_download(songs, output_dir)
            return 0

        if args.song:
            song = parse_song_input(args.song)
            if not song:
                return 1
            return 0 if download_one(song, output_dir) else 1

        interactive_menu(output_dir, cookie)
        return 0
    except KeyboardInterrupt:
        print("\n已取消")
        return 1
    except Exception as e:
        log_err("运行出错: %s" % e)
        log_traceback()
        return 1


if __name__ == "__main__":
    sys.exit(main())
