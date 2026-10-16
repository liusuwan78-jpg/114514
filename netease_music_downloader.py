#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐下载器
功能：根据网易云音乐歌曲 ID 或 URL 下载歌曲，并转换为 MP3 格式（含封面、歌手、专辑等元数据）

依赖：requests, pycryptodome, mutagen, ffmpeg
安装：pip install requests pycryptodome mutagen
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse, parse_qs

import requests
from Crypto.Cipher import AES
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TCON, TRCK, TDRC
from mutagen.mp3 import MP3

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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}

BASE_URL = "https://music.163.com"


def set_cookie(cookie: str | None) -> None:
    """设置请求 Cookie（传入登录后的 cookie 可下载 VIP/付费歌曲）"""
    base = "appver=2.0.2; os=pc;"
    if cookie:
        cookie = cookie.strip()
        if not cookie.startswith("appver"):
            cookie = f"{base} {cookie}"
        HEADERS["Cookie"] = cookie
    else:
        HEADERS["Cookie"] = base


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
    import random
    import string
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


# ============ 业务函数 ============
def extract_song_id(input_str: str) -> str:
    """从 URL 或纯数字中提取歌曲 ID"""
    input_str = input_str.strip()
    if input_str.isdigit():
        return input_str
    # 匹配 URL 中的 id 参数或 /song?id=xxx
    m = re.search(r"[?&]id=(\d+)", input_str)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)", input_str)
    if m:
        return m.group(1)
    raise ValueError(f"无法从输入中解析歌曲 ID: {input_str}")


def get_song_detail(song_id: str) -> dict:
    """获取歌曲详情（歌名、歌手、专辑、封面等）"""
    data = {"c": json.dumps([{"id": song_id}]), "ids": json.dumps([song_id])}
    result = weapi_post("/v3/song/detail", data)
    songs = result.get("songs") or []
    if not songs:
        raise RuntimeError(f"未找到歌曲 ID={song_id} 的信息")
    return songs[0]


def get_song_url(song_id: str, level: str = "exhigh") -> dict:
    """获取歌曲播放/下载链接"""
    data = {
        "ids": json.dumps([song_id]),
        "level": level,
        "encodeType": "aac",
    }
    result = weapi_post("/song/enhance/player/url/v1", data)
    data_list = result.get("data") or []
    if not data_list:
        raise RuntimeError("未获取到歌曲播放地址")
    return data_list[0]


def download_file(url: str, dest: str) -> None:
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
                            print(f"\r  下载中... {pct}%", end="", flush=True)
                            last_pct = pct
        print(f"\r  下载完成 ({downloaded/1024/1024:.1f} MB)")


def convert_to_mp3(src: str, dest: str, bitrate: str = "320k") -> bool:
    """使用 ffmpeg 将音频转换为 MP3；若源已是 MP3 则直接复制"""
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-c:a", "libmp3lame", "-b:a", bitrate,
        "-map_metadata", "-1",  # 先清除旧元数据，后面再写入
        dest,
    ]
    try:
        subprocess.run(
            cmd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ffmpeg 转换失败: {e}")
        return False


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def set_mp3_tags(mp3_path: str, info: dict, cover_data: bytes | None) -> None:
    """为 MP3 文件写入元数据：标题、歌手、专辑、流派、封面"""
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
        # 专辑发行时间（毫秒时间戳 -> 年份）
        pub_time = (info.get("publishTime")
                    or (info.get("al") or {}).get("publishTime"))
        if pub_time:
            try:
                import datetime
                year = datetime.datetime.fromtimestamp(pub_time / 1000).year
                tags.add(TDRC(encoding=3, text=str(year)))
            except Exception:
                pass

        if cover_data:
            tags.add(APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=cover_data,
            ))
        tags.save(mp3_path)
    except Exception as e:
        print(f"  写入元数据失败（不影响播放）: {e}")


def download_cover(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        print(f"  下载封面失败: {e}")
    return None


def download_song(song_input: str, output_dir: str, level: str = "exhigh", bitrate: str = "320k") -> str | None:
    song_id = extract_song_id(song_input)
    print(f"[1/5] 解析歌曲 ID: {song_id}")

    detail = get_song_detail(song_id)
    name = detail.get("name", f"song_{song_id}")
    artists = "/".join(a["name"] for a in detail.get("ar", []))
    album = (detail.get("al") or {}).get("name", "")
    cover_url = (detail.get("al") or {}).get("picUrl", "")
    print(f"[2/5] 歌曲信息: {name} - {artists}  (专辑: {album})")

    url_info = get_song_url(song_id, level=level)
    song_url = url_info.get("url")
    if not song_url:
        # 尝试降级音质
        for lv in ("higher", "standard"):
            print(f"  音质 {level} 不可用，尝试 {lv} ...")
            url_info = get_song_url(song_id, level=lv)
            song_url = url_info.get("url")
            if song_url:
                break
    if not song_url:
        print("[错误] 无法获取歌曲下载链接（可能是 VIP 独占或版权/区域限制）")
        print("       提示：可使用 --cookie 传入登录后的 Cookie 以解锁更多歌曲")
        return None

    print(f"[3/5] 获取下载链接成功（{url_info.get('type', 'unknown')}, {url_info.get('br', 0)//1000}kbps）")

    os.makedirs(output_dir, exist_ok=True)
    filename = safe_filename(f"{name} - {artists}") if artists else safe_filename(name)
    tmp_raw = os.path.join(tempfile.gettempdir(), f"netease_{song_id}.tmp")
    final_path = os.path.join(output_dir, f"{filename}.mp3")

    print("[4/5] 下载音频文件...")
    download_file(song_url, tmp_raw)

    print(f"[5/5] 转换为 MP3 ({bitrate}) 并写入元数据...")
    ok = convert_to_mp3(tmp_raw, final_path, bitrate=bitrate)
    try:
        os.remove(tmp_raw)
    except OSError:
        pass
    if not ok:
        return None

    cover_data = download_cover(cover_url)
    set_mp3_tags(final_path, detail, cover_data)

    print(f"\n✅ 下载完成: {final_path}")
    return final_path


def search_songs(keyword: str, limit: int = 10) -> list:
    """按关键词搜索歌曲，返回歌曲列表"""
    data = {"s": keyword, "type": 1, "limit": limit, "offset": 0}
    result = weapi_post("/search/get", data)
    songs = (result.get("result") or {}).get("songs", [])
    out = []
    for s in songs:
        artists = "/".join(a["name"] for a in s.get("artists", s.get("ar", [])))
        album = (s.get("album") or s.get("al") or {}).get("name", "")
        fee = s.get("fee", 0)
        fee_label = {0: "免费", 1: "VIP", 4: "付费", 8: "免费"}.get(fee, str(fee))
        out.append({
            "id": s["id"],
            "name": s.get("name", ""),
            "artists": artists,
            "album": album,
            "fee": fee_label,
        })
    return out


def main():
    parser = argparse.ArgumentParser(
        description="网易云音乐下载器：下载歌曲并保存为带封面元数据的 MP3",
        epilog=(
            "示例:\n"
            "  python3 netease_music_downloader.py 259138\n"
            "  python3 netease_music_downloader.py 'https://music.163.com/#/song?id=259138'\n"
            "  python3 netease_music_downloader.py --search 青花瓷\n"
            "  python3 netease_music_downloader.py 259138 --cookie 'MUSIC_U=xxx' -q lossless\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("song", nargs="?", help="歌曲 ID 或网易云音乐歌曲 URL")
    parser.add_argument("-o", "--output", default=".", help="输出目录（默认当前目录）")
    parser.add_argument(
        "-q", "--quality", default="exhigh",
        choices=["standard", "higher", "exhigh", "lossless", "hires"],
        help="音质等级（默认 exhigh）",
    )
    parser.add_argument("--bitrate", default="320k", help="输出 MP3 比特率（默认 320k）")
    parser.add_argument(
        "--cookie", default=os.environ.get("NETEASE_COOKIE"),
        help="登录后的 Cookie（也可通过环境变量 NETEASE_COOKIE 设置），用于下载 VIP 歌曲",
    )
    parser.add_argument("--search", metavar="关键词", help="按关键词搜索歌曲并选择下载")
    parser.add_argument("--search-limit", type=int, default=10, help="搜索结果数量（默认 10）")
    args = parser.parse_args()

    set_cookie(args.cookie)

    if args.search:
        results = search_songs(args.search, limit=args.search_limit)
        if not results:
            print(f"未找到与「{args.search}」相关的歌曲")
            return
        print(f"搜索「{args.search}」的结果：\n")
        for i, s in enumerate(results, 1):
            print(f"  [{i}] {s['name']} - {s['artists']}  | 专辑: {s['album']}  | {s['fee']}")
        try:
            choice = input(f"\n请输入序号下载 (1-{len(results)})，或 q 退出: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice.lower() == "q":
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(results)):
            print("无效输入")
            return
        sid = results[int(choice) - 1]["id"]
        download_song(str(sid), args.output, level=args.quality, bitrate=args.bitrate)
        return

    if not args.song:
        parser.error("请提供歌曲 ID/URL，或使用 --search 关键词搜索")

    download_song(args.song, args.output, level=args.quality, bitrate=args.bitrate)


if __name__ == "__main__":
    main()
