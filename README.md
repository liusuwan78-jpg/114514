# 网易云音乐下载器

一个命令行网易云音乐下载工具，**纯 Python 实现，不依赖 ffmpeg**。直接下载网易云原生 MP3（最高 320kbps），并写入封面与元数据。

## 特点

- 🎵 单曲 / 搜索 / 歌手 / 歌单 / 榜单 / 每日推荐
- 🚫 **无需 ffmpeg**：直接下原生 MP3，exe 体积小、启动快、不会有下载转码工具的坑
- 🖼️ 用 mutagen 写入封面、标题、歌手、专辑、年份
- 🎨 彩色终端 + 编号菜单
- 📦 单文件 exe，U 盘便携（配置与下载目录跟随 exe）

## 直接使用（推荐）

去 [Releases](https://github.com/liusuwan78-jpg/114514/releases) 下载 `netease_downloader.exe`，双击打开即可（无参数会进入交互菜单）。

## 从源码运行

```bash
pip install -r requirements.txt
python netease_downloader.py            # 交互菜单
python netease_downloader.py 259138     # 单曲
python netease_downloader.py --search 青花瓷
python netease_downloader.py --artist 周杰伦
python netease_downloader.py --playlist 3778678
python netease_downloader.py --toplist
python netease_downloader.py --daily --cookie "MUSIC_U=xxx"
```

## 参数

| 参数 | 说明 |
|------|------|
| `song_id` | 歌曲 ID |
| `-o, --output` | 输出目录（默认 exe 同目录的"音乐"文件夹） |
| `-q, --quality` | 音质：standard(128k) / higher(192k) / exhigh(320k) |
| `--cookie` | 登录 Cookie（MUSIC_U=xxx） |
| `--search` | 搜索关键词 |
| `--artist` | 歌手名 |
| `--playlist` | 歌单 ID 或链接 |
| `--toplist` | 官方榜单 |
| `--daily` | 每日推荐（需登录） |
| `--limit` | 搜索/歌手结果数量 |

## 登录

VIP / 灰色歌曲需要登录。在网易云网页版登录后，从浏览器 Cookie 复制 `MUSIC_U` 的值，用 `--cookie` 传入，或在交互菜单的"设置"里填入。

## 打包（自动）

推送到 `main` 会触发 GitHub Actions，在 Windows 机器上自动打包并把 `netease_downloader.exe` 发布到 Release。

## 免责声明

本工具仅供学习交流，请尊重版权，下载的音乐请勿用于商业用途。
