# 网易云音乐下载器

一个命令行网易云音乐下载工具，支持单曲、搜索、歌手、歌单、榜单、每日推荐下载，自动转码 MP3 并写入封面和元数据。

## 功能

- 🎵 单曲下载（按歌曲 ID）
- 🔍 搜索下载（关键词搜索，编号选择）
- 👤 歌手热门歌曲下载
- 📋 歌单全量下载
- 📊 网易云官方榜单下载
- 📅 每日推荐下载（需登录）
- 🎧 自动转码 MP3 320kbps
- 🖼️ 自动写入封面、标题、歌手、专辑元数据
- 🎨 彩色终端界面，编号菜单选择
- 📦 可打包为单文件 exe，自带 ffmpeg，零依赖

## 环境要求

- Python 3.8 ~ 3.11（Windows 8.1 请用 3.9 ~ 3.11）
- 可选：ffmpeg（不装也能用，打包时会自动内置）

## 快速使用

```bash
# 安装依赖
pip install -r requirements.txt

# 单曲下载
python netease_music_downloader.py 259138 -o ./音乐

# 搜索下载
python netease_music_downloader.py --search 青花瓷

# 歌手热门
python netease_music_downloader.py --artist 周杰伦

# 歌单下载
python netease_music_downloader.py --playlist 3778678

# 榜单下载
python netease_music_downloader.py --toplist

# 每日推荐（需登录）
python netease_music_downloader.py --daily --cookie "MUSIC_U=你的cookie"
```

无参数运行进入交互菜单：

```
python netease_music_downloader.py
```

## 打包为 exe（Windows）

双击 `build_exe.bat`，或手动执行：

```bash
python build_exe.py
```

自动下载 ffmpeg 并打包为单文件 `dist/netease_music_downloader.exe`（约 125MB），无需安装 Python 或 ffmpeg 即可使用。

## 参数说明

| 参数 | 说明 |
|------|------|
| `song_id` | 歌曲 ID（位置参数） |
| `-o, --output` | 输出目录（默认 `./音乐`） |
| `-q, --quality` | 音质：standard / higher / exhigh / lossless / hires |
| `--bitrate` | MP3 码率（默认 320） |
| `--cookie` | 登录 Cookie（MUSIC_U=xxx） |
| `--search` | 搜索关键词 |
| `--artist` | 歌手名 |
| `--playlist` | 歌单 ID 或 URL |
| `--toplist` | 下载官方榜单 |
| `--daily` | 下载每日推荐（需登录） |
| `--limit` | 搜索/歌手结果数量限制 |

## 登录说明

部分歌曲（VIP/灰色）需要登录才能下载。在网易云网页版登录后，从浏览器 Cookie 中复制 `MUSIC_U` 的值，通过 `--cookie` 传入即可。

## 免责声明

本工具仅供学习交流使用，请尊重版权，下载的音乐请勿用于商业用途。
