# 酷狗音乐下载器（Windows XP 兼容版）

命令行酷狗音乐下载工具，**纯 Python + requests**，不依赖 ffmpeg / mutagen。下载 MP3 并自动保存同名 `.lrc` 歌词、写入 ID3 标签与封面。

## 特点

- 单曲 / 搜索 / 榜单
- 音质自动降级：优先 320k / FLAC，拿不到自动回到 128k
- 自动保存同名 `.lrc` 歌词，优先按歌名 + 歌手匹配，避免 Live / 翻唱版本串词
- **Windows XP SP3 兼容**：32 位单文件 exe，XP / Win7 / Win8 / Win10 / Win11 通用
- 无需 mutagen：内置 ID3v2.3 写入器，标题、歌手、专辑、封面
- 控制台用 `WriteConsoleW` 输出，任何语言版本的 XP 都不乱码
- U 盘便携：配置与下载目录跟随 exe

## 直接使用（推荐）

去 [Releases](https://github.com/liusuwan78-jpg/114514/releases) 下载 `kugou_downloader.exe`，双击打开即可（无参数进入交互菜单）。

## 从源码运行

需要 Python 3.4+（XP 上请用 Python 3.4.4 32 位）：

```bash
pip install -r requirements.txt
python kugou_downloader.py                      # 交互菜单
python kugou_downloader.py 936BFC076EA0E42E62EA66B8377110D4   # 单曲（hash 或链接）
python kugou_downloader.py --search 青花瓷
python kugou_downloader.py --rank 8888 --limit 20
python kugou_downloader.py --list-ranks
```

## 参数

| 参数 | 说明 |
|------|------|
| `song` | 歌曲 hash（32 位）或酷狗分享链接 |
| `-o, --output` | 输出目录（默认 exe 同目录的"音乐"文件夹） |
| `--search` | 搜索关键词并批量下载 |
| `--rank` | 下载榜单（默认 8888 = TOP500） |
| `--list-ranks` | 列出所有榜单 |
| `--limit` | 数量限制 |
| `--cookie` | 酷狗 Cookie（部分音质需要登录） |
| `--version` | 显示版本 |

## 说明

- 酷狗大部分热门歌曲需要 VIP，未登录时这些歌曲会提示"无法获取下载链接"。
- 免费歌曲通常只能拿到 128k；签名接口在部分网络环境下能返回 320k / FLAC，程序会自动择高。
- XP 需要 SP3；32 位 exe 在 64 位系统上同样可运行。
- exe 同目录会生成 `.kugou_downloader.json`（配置）和 `kugou_downloader_error.log`（出错日志）。
- 杀毒软件可能对 PyInstaller 打包程序误报，添加信任即可。

## 免责声明

本工具仅供学习交流，请尊重版权，下载的音乐请勿用于商业用途。
