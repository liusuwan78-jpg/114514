#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网易云音乐下载器 - 图形界面版（tkinter）

- 单页窗口：搜索框 + 歌曲勾选列表 + 下载按钮 + 进度条 + 日志
- 32 位 exe，Windows XP SP3 / Win7 / Win8 / Win10 / Win11 通用（Python 3.4 自带 tkinter）
- 歌词用界面勾选框控制，状态记忆，不弹窗打扰
- 下载文件按来源分文件夹：音乐/搜索-xxx、音乐/歌单-xxx、音乐/榜单-xxx ...
- 复用 netease_downloader 的全部下载 / ID3 / 歌词逻辑
"""

import os
import sys

# --windowed 打包后 sys.stdout 可能是 None，必须在导入下载器之前兜底
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import queue
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import netease_downloader as nd

APP_TITLE = "网易云音乐下载器 v%s 图形版" % nd.APP_VERSION

QUALITY_LEVELS = [("exhigh", "320k 极高"), ("higher", "192k 较高"),
                  ("standard", "128k 标准")]


class _QueueWriter(object):
    """把下载器里的 print 输出转发到 GUI 日志框"""

    def __init__(self, q):
        self.q = q

    def write(self, text):
        if text:
            self.q.put(("log", text))

    def flush(self):
        pass

    def isatty(self):
        return False


class App(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self)
        self.title(APP_TITLE)
        self.geometry("860x600")
        self.minsize(720, 480)

        self.cfg = nd.load_config()
        self.output_dir = self.cfg.get("output_dir") or os.path.join(
            nd.app_dir(), "音乐")
        self.quality = tk.StringVar(value=self.cfg.get("level") or "exhigh")
        self.with_lyric = tk.BooleanVar(
            value=bool(self.cfg.get("with_lyric", True)))
        self.cookie = self.cfg.get("cookie") or ""
        nd.set_cookie(self.cookie)

        self.q = queue.Queue()
        self.songs = []            # 当前列表里的歌曲
        self.checked = {}          # 列表行 id -> 是否勾选
        self.source_subdir = "搜索"  # 当前列表来源（决定分类子文件夹）
        self.downloading = False
        self.worker = None

        self._build_menu()
        self._build_body()

        sys.stdout = _QueueWriter(self.q)
        sys.stderr = _QueueWriter(self.q)
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================== 界面 ====================
    def _build_menu(self):
        bar = tk.Menu(self)

        m_func = tk.Menu(bar, tearoff=0)
        m_func.add_command(label="搜索歌曲", command=self.do_search)
        m_func.add_command(label="下载单曲（ID / 链接）", command=self.do_single)
        m_func.add_command(label="歌手热门歌曲", command=self.do_artist)
        m_func.add_command(label="歌单下载（ID / 链接）", command=self.do_playlist)
        m_func.add_command(label="官方榜单", command=self.do_toplist)
        m_func.add_command(label="每日推荐（需登录）", command=self.do_daily)
        bar.add_cascade(label="功能", menu=m_func)

        m_set = tk.Menu(bar, tearoff=0)
        m_set.add_command(label="下载目录...", command=self.set_output_dir)
        m_set.add_command(label="登录 Cookie...", command=self.set_cookie)
        m_quality = tk.Menu(m_set, tearoff=0)
        for value, label in QUALITY_LEVELS:
            m_quality.add_radiobutton(label=label, value=value,
                                      variable=self.quality,
                                      command=self.save_settings)
        m_set.add_cascade(label="音质", menu=m_quality)
        bar.add_cascade(label="设置", menu=m_set)

        m_help = tk.Menu(bar, tearoff=0)
        m_help.add_command(label="关于", command=self.show_about)
        bar.add_cascade(label="帮助", menu=m_help)

        self.config(menu=bar)

    def _build_body(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill=tk.X)
        ttk.Label(top, text="关键词:").pack(side=tk.LEFT)
        self.kw_var = tk.StringVar()
        self.kw_entry = ttk.Entry(top, textvariable=self.kw_var)
        self.kw_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.kw_entry.bind("<Return>", lambda e: self.do_search())
        self.search_btn = ttk.Button(top, text="搜索", command=self.do_search)
        self.search_btn.pack(side=tk.LEFT)
        ttk.Button(top, text="打开下载目录",
                   command=self.open_output_dir).pack(side=tk.LEFT, padx=(6, 0))

        mid = ttk.Frame(self, padding=(6, 0))
        mid.pack(fill=tk.BOTH, expand=True)
        columns = ("sel", "name", "artists", "album", "fee")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings",
                                 selectmode="browse")
        for col, text, width, anchor in (
                ("sel", "下载", 46, tk.CENTER),
                ("name", "歌名", 260, tk.W),
                ("artists", "歌手", 150, tk.W),
                ("album", "专辑", 190, tk.W),
                ("fee", "类型", 60, tk.CENTER)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=anchor, stretch=(col != "sel"))
        sb = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._on_tree_click)

        tools = ttk.Frame(self, padding=6)
        tools.pack(fill=tk.X)
        ttk.Button(tools, text="全选", command=lambda: self.check_all(True)).pack(side=tk.LEFT)
        ttk.Button(tools, text="全不选", command=lambda: self.check_all(False)).pack(side=tk.LEFT, padx=4)
        self.lyric_chk = ttk.Checkbutton(
            tools, text="同时下载歌词(.lrc)", variable=self.with_lyric,
            command=self.save_settings)
        self.lyric_chk.pack(side=tk.RIGHT)

        bottom = ttk.Frame(self, padding=(6, 0, 6, 6))
        bottom.pack(fill=tk.X)
        self.dl_btn = ttk.Button(bottom, text="开始下载", command=self.start_download)
        self.dl_btn.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.status_var = tk.StringVar(value="就绪。输入关键词搜索，或用“功能”菜单。")
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT)

        logf = ttk.LabelFrame(self, text="日志", padding=4)
        logf.pack(fill=tk.BOTH, padx=6, pady=(0, 6))
        self.log_text = tk.Text(logf, height=7, state=tk.DISABLED, wrap=tk.NONE)
        lsb = ttk.Scrollbar(logf, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lsb.pack(side=tk.LEFT, fill=tk.Y)

    # ==================== 列表操作 ====================
    def fill_songs(self, songs, source_subdir):
        self.tree.delete(*self.tree.get_children())
        self.checked.clear()
        self.songs = songs
        self.source_subdir = source_subdir
        for i, s in enumerate(songs):
            iid = str(i)
            self.checked[iid] = True
            self.tree.insert("", tk.END, iid=iid, values=(
                "√", s.get("name") or "", s.get("artists") or "",
                s.get("album") or "", s.get("fee") or ""))
        self.status_var.set("共 %d 首（点击“下载”列切换勾选）" % len(songs))

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if iid and col == "#1":
            self.checked[iid] = not self.checked.get(iid, False)
            self.tree.set(iid, "sel", "√" if self.checked[iid] else "")
            return "break"

    def check_all(self, value):
        for iid in self.tree.get_children():
            self.checked[iid] = value
            self.tree.set(iid, "sel", "√" if value else "")

    # ==================== 后台任务 ====================
    def _run_async(self, func, on_done=None):
        """后台线程跑网络任务，结果通过队列回到 UI 线程"""
        def runner():
            try:
                result = func()
                self.q.put(("task_done", (on_done, result, None)))
            except Exception as e:
                self.q.put(("task_done", (on_done, None, e)))
        t = threading.Thread(target=runner)
        t.daemon = True
        t.start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "task_done":
                    on_done, result, err = payload
                    if err is not None:
                        self._append_log("[ERROR] %s\n" % err)
                        messagebox.showerror("出错了", str(err), parent=self)
                    elif on_done:
                        on_done(result)
                elif kind == "download_done":
                    self._download_finished(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _append_log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        for line in text.splitlines():
            line = line.split("\r")[-1].rstrip()
            if not line.strip():
                continue
            self.log_text.insert(tk.END, line + "\n")
        # 防止日志无限增长
        if int(self.log_text.index("end-1c").split(".")[0]) > 600:
            self.log_text.delete("1.0", "200.0")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ==================== 功能：加载歌曲 ====================
    def do_search(self):
        kw = self.kw_var.get().strip()
        if not kw:
            self.status_var.set("请输入搜索关键词")
            return
        self.status_var.set("搜索中: %s ..." % kw)
        self._run_async(lambda: nd.search_songs(kw, limit=30),
                        lambda songs: self._on_songs_loaded(
                            songs, "搜索-" + nd.safe_filename(kw)))

    def do_single(self):
        text = simpledialog.askstring("下载单曲", "歌曲 ID 或链接:", parent=self)
        if not text:
            return
        try:
            sid = nd.extract_id(text)
        except Exception as e:
            messagebox.showerror("出错了", str(e), parent=self)
            return
        self.status_var.set("获取歌曲信息...")

        def load():
            details = nd.get_songs_detail([sid])
            out = []
            for t in details:
                out.append({"id": t["id"], "name": t.get("name", ""),
                            "artists": nd.join_artists(t),
                            "album": (t.get("al") or {}).get("name", "")})
            return out
        self._run_async(load, lambda songs: self._on_songs_loaded(songs, "单曲"))

    def do_artist(self):
        kw = simpledialog.askstring("歌手热门歌曲", "歌手名:", parent=self)
        if not kw:
            return
        self.status_var.set("搜索歌手: %s ..." % kw)

        def load():
            return nd.search_artists(kw, limit=8)

        def after(artists):
            if not artists:
                messagebox.showinfo("提示", "没有找到该歌手", parent=self)
                return
            names = ["%s（ID %s）" % (a["name"], a["id"]) for a in artists]
            idx = self._choose("选择歌手", names)
            if idx is None:
                return
            artist = artists[idx]
            self.status_var.set("获取 %s 的热门歌曲..." % artist["name"])
            self._run_async(
                lambda: nd.get_artist_hot_songs(artist["id"]),
                lambda songs: self._on_songs_loaded(
                    songs, "歌手-" + nd.safe_filename(artist["name"])))
        self._run_async(load, after)

    def do_playlist(self):
        text = simpledialog.askstring("歌单下载", "歌单 ID 或链接:", parent=self)
        if not text:
            return
        try:
            pid = nd.extract_id(text)
        except Exception as e:
            messagebox.showerror("出错了", str(e), parent=self)
            return
        self.status_var.set("获取歌单...")
        self._run_async(lambda: nd.get_playlist_detail(pid),
                        self._on_playlist_loaded)

    def _on_playlist_loaded(self, playlist):
        tracks = (playlist or {}).get("tracks") or []
        if not tracks:
            messagebox.showinfo("提示", "歌单为空或需要登录", parent=self)
            return
        name = playlist.get("name") or "未知歌单"
        self._on_songs_loaded(self._tracks_to_songs(tracks),
                              "歌单-" + nd.safe_filename(name))

    def do_toplist(self):
        self.status_var.set("获取榜单...")

        def after(lists):
            if not lists:
                return
            names = [l["name"] for l in lists]
            idx = self._choose("选择榜单", names)
            if idx is None:
                return
            item = lists[idx]
            self.status_var.set("获取榜单歌曲: %s ..." % item["name"])

            def load():
                return nd.get_playlist_detail(item["id"])

            def loaded(playlist):
                tracks = (playlist or {}).get("tracks") or []
                self._on_songs_loaded(self._tracks_to_songs(tracks),
                                      "榜单-" + nd.safe_filename(item["name"]))
            self._run_async(load, loaded)
        self._run_async(nd.get_toplist, after)

    def do_daily(self):
        if not self.cookie:
            messagebox.showinfo("提示", "每日推荐需要登录，请先在“设置”里填写 Cookie",
                                parent=self)
            return
        self.status_var.set("获取每日推荐...")
        self._run_async(nd.get_daily_recommend_songs,
                        lambda songs: self._on_songs_loaded(songs, "每日推荐"))

    def _tracks_to_songs(self, tracks):
        out = []
        for t in tracks:
            out.append({"id": t["id"], "name": t.get("name", ""),
                        "artists": nd.join_artists(t),
                        "album": (t.get("al") or {}).get("name", "")})
        return out

    def _on_songs_loaded(self, songs, source_subdir):
        if not songs:
            self.status_var.set("没有结果")
            messagebox.showinfo("提示", "没有找到歌曲", parent=self)
            return
        self.fill_songs(songs, source_subdir)
        self._append_log("已加载 %d 首，分类目录: %s\n" % (len(songs), source_subdir))

    def _choose(self, title, names):
        """简单的单选弹窗，返回索引或 None"""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.geometry("360x380")
        dlg.transient(self)
        dlg.grab_set()
        lb = tk.Listbox(dlg)
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for n in names:
            lb.insert(tk.END, n)
        lb.selection_set(0)
        result = [None]

        def ok():
            sel = lb.curselection()
            if sel:
                result[0] = sel[0]
            dlg.destroy()
        btns = ttk.Frame(dlg)
        btns.pack(pady=(0, 8))
        ttk.Button(btns, text="确定", command=ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side=tk.LEFT)
        lb.bind("<Double-Button-1>", lambda e: ok())
        self.wait_window(dlg)
        return result[0]

    # ==================== 下载 ====================
    def start_download(self):
        if self.downloading:
            return
        selected = []
        for iid in self.tree.get_children():
            if self.checked.get(iid):
                selected.append(self.songs[int(iid)])
        if not selected:
            messagebox.showinfo("提示", "请先搜索并勾选要下载的歌曲", parent=self)
            return

        subdir = self.source_subdir.rstrip(". ") or "下载"
        out_dir = os.path.join(self.output_dir, subdir)
        with_lyric = bool(self.with_lyric.get())
        level = self.quality.get()
        total = len(selected)
        self.downloading = True
        self.dl_btn.configure(state=tk.DISABLED)
        self.search_btn.configure(state=tk.DISABLED)
        self.progress["value"] = 0
        self._append_log("\n开始下载 %d 首 -> %s（歌词: %s）\n" % (
            total, out_dir, "是" if with_lyric else "否"))

        def runner():
            ok = 0
            for i, song in enumerate(selected):
                self.q.put(("status", "[%d/%d] %s" % (
                    i + 1, total, song.get("name") or "")))
                try:
                    path = nd.download_one(song["id"], out_dir, level=level,
                                           with_lyric=with_lyric)
                    if path:
                        ok += 1
                except Exception as e:
                    self.q.put(("log", "[ERROR] %s\n" % e))
                    try:
                        nd.log_traceback()
                    except Exception:
                        pass
                self.q.put(("progress", (i + 1) * 100.0 / total))
            self.q.put(("download_done", (ok, total, out_dir)))

        self.worker = threading.Thread(target=runner)
        self.worker.daemon = True
        self.worker.start()

    def _download_finished(self, payload):
        ok, total, out_dir = payload
        self.downloading = False
        self.dl_btn.configure(state=tk.NORMAL)
        self.search_btn.configure(state=tk.NORMAL)
        self.status_var.set("完成：成功 %d / %d" % (ok, total))
        self._append_log("完成：成功 %d / %d，保存在 %s\n" % (ok, total, out_dir))
        messagebox.showinfo("下载完成", "成功 %d / %d\n保存位置:\n%s" % (ok, total, out_dir),
                            parent=self)

    # ==================== 设置 ====================
    def save_settings(self):
        cfg = nd.load_config()
        cfg["output_dir"] = self.output_dir
        cfg["level"] = self.quality.get()
        cfg["with_lyric"] = bool(self.with_lyric.get())
        cfg["cookie"] = self.cookie
        nd.save_config(cfg)

    def set_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir, parent=self)
        if d:
            self.output_dir = d
            self.save_settings()
            self.status_var.set("下载目录: %s" % d)

    def set_cookie(self):
        c = simpledialog.askstring(
            "登录 Cookie", "填入 MUSIC_U=xxx（VIP / 每日推荐需要）:",
            initialvalue=self.cookie, parent=self)
        if c is not None:
            self.cookie = c.strip()
            nd.set_cookie(self.cookie)
            self.save_settings()
            self.status_var.set("Cookie 已保存")

    def open_output_dir(self):
        path = self.output_dir
        try:
            if not os.path.isdir(path):
                os.makedirs(path)
            if os.name == "nt":
                os.startfile(path)
            else:
                self.status_var.set("下载目录: %s" % path)
        except Exception as e:
            messagebox.showerror("出错了", str(e), parent=self)

    def show_about(self):
        messagebox.showinfo(
            "关于",
            "%s\n\n单页图形版：搜索 / 单曲 / 歌手 / 歌单 / 榜单 / 每日推荐\n"
            "歌词由勾选框控制；文件按来源分文件夹保存。\n"
            "当前下载目录:\n%s" % (APP_TITLE, self.output_dir),
            parent=self)

    def _on_close(self):
        if self.downloading:
            if not messagebox.askyesno("确认退出", "正在下载，确定要退出吗？", parent=self):
                return
        self.save_settings()
        self.destroy()


def main():
    try:
        app = App()
        app.mainloop()
    except Exception:
        try:
            nd.log_traceback()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
