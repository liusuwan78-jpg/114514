# 网易云音乐下载器（Windows XP 兼容版）

一个命令行网易云音乐下载工具，**纯 Python 实现，不依赖 ffmpeg / mutagen**。直接下载网易云原生 MP3（最高 320kbps），并手工写入封面与元数据。

## 特点

- 单曲 / 搜索 / 歌手 / 歌单 / 榜单 / 每日推荐
- **Windows XP SP3 兼容**：32 位单文件 exe，XP / Win7 / Win8 / Win10 / Win11 通用
- 无需 ffmpeg：直接下原生 MP3，exe 体积小、启动快
- 无需 mutagen：内置 ID3v2.3 写入器，封面、标题、歌手、专辑、年份
- 控制台用 `WriteConsoleW` 输出，任何语言版本的 XP 都不乱码
- U 盘便携：配置与下载目录跟随 exe

## 直接使用（推荐）

去 [Releases](https://github.com/liusuwan78-jpg/114514/releases) 下载 `netease_downloader.exe`，双击打开即可（无参数会进入交互菜单）。

## 从源码运行

需要 Python 3.4+（XP 上请用 Python 3.4.4 32 位）：

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
| `--version` | 显示版本 |

## 登录

VIP / 灰色歌曲需要登录。在网易云网页版登录后，从浏览器 Cookie 复制 `MUSIC_U` 的值，用 `--cookie` 传入，或在交互菜单的"设置"里填入。

## 打包（自动）

推送到 `main` 会触发 GitHub Actions：安装 Python 3.4.4（32 位）、PyInstaller 3.4 打包，并把 `netease_downloader.exe` 发布到 Release。

## 说明

- XP 需要 SP3；32 位 exe 在 64 位系统上同样可运行。
- exe 同目录会生成 `.netease_downloader.json`（配置）和 `netease_downloader_error.log`（出错日志）。
- 杀毒软件可能对 PyInstaller 打包程序误报，添加信任即可。

## 免责声明

本工具仅供学习交流，请尊重版权，下载的音乐请勿用于商业用途。
