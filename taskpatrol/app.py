"""TaskPatrol main window: Processes, Performance and Activity tabs."""

import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import font as tkfont, messagebox, ttk

import psutil

from taskpatrol import APP_ID, DISPLAY_NAME, INSTALLER_GUID, __version__
from taskpatrol import winutil
from taskpatrol.sampler import Sampler

LOG_NAME = "process_activity_log.txt"

# Killing any of these usually blue-screens or logs the user out.
PROTECTED = {
    "system idle process", "system", "registry", "secure system", "memcompression",
    "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "lsaiso.exe", "svchost.exe", "dwm.exe", "fontdrvhost.exe",
}

C = {
    "bg": "#1e1f22", "panel": "#2b2d31", "raised": "#383a40", "border": "#3f4147",
    "fg": "#e6e6e6", "muted": "#9aa0a6", "accent": "#4ea1ff", "select": "#2f4f7a",
    "red": "#e5534b", "green": "#57ab5a", "amber": "#d29922", "purple": "#b083f0",
}


def fmt_mem(mb):
    return f"{mb / 1024:.2f} GB" if mb >= 1024 else f"{mb:.1f} MB"


def fmt_duration(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{days}d {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"


def setup_activity_logger(path):
    logger = logging.getLogger("taskpatrol.activity")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    family = "Segoe UI" if sys.platform == "win32" else tkfont.nametofont("TkDefaultFont").actual("family")
    # Named fonts rather than option_add("*Font"), which would override per-style fonts.
    for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    root.configure(background=C["bg"])
    scale = float(root.tk.call("tk", "scaling")) / 1.333

    style.configure(".", background=C["bg"], foreground=C["fg"], fieldbackground=C["panel"],
                    bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
                    troughcolor=C["panel"], focuscolor=C["accent"], insertcolor=C["fg"],
                    selectbackground=C["select"], selectforeground=C["fg"], font=(family, 10))
    style.configure("TFrame", background=C["bg"])
    style.configure("Card.TFrame", background=C["panel"])
    style.configure("TLabel", background=C["bg"], foreground=C["fg"])
    style.configure("Muted.TLabel", foreground=C["muted"])
    style.configure("Card.TLabel", background=C["panel"])
    style.configure("CardMuted.TLabel", background=C["panel"], foreground=C["muted"])
    style.configure("CardTitle.TLabel", background=C["panel"], font=(family, 11, "bold"))
    style.configure("CardValue.TLabel", background=C["panel"], font=(family, 24, "bold"))
    style.configure("TButton", background=C["raised"], foreground=C["fg"], padding=(10, 4), borderwidth=0)
    style.map("TButton", background=[("disabled", C["panel"]), ("pressed", C["select"]), ("active", "#45474e")],
              foreground=[("disabled", C["muted"])])
    style.configure("Danger.TButton", background="#8f2d28")
    style.map("Danger.TButton", background=[("disabled", C["panel"]), ("pressed", "#6d221e"), ("active", C["red"])])
    style.configure("Link.TButton", background=C["bg"], foreground=C["accent"], padding=(6, 0))
    style.map("Link.TButton", background=[("active", C["bg"])], foreground=[("active", C["fg"])])
    style.configure("TCheckbutton", background=C["bg"], foreground=C["fg"])
    style.map("TCheckbutton", background=[("active", C["bg"])], indicatorcolor=[("selected", C["accent"])])
    style.configure("TEntry", fieldbackground=C["panel"], foreground=C["fg"], padding=4)
    style.configure("TCombobox", fieldbackground=C["panel"], foreground=C["fg"], background=C["raised"],
                    arrowcolor=C["fg"])
    style.map("TCombobox", fieldbackground=[("readonly", C["panel"])], foreground=[("readonly", C["fg"])])
    root.option_add("*TCombobox*Listbox.background", C["panel"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["select"])
    style.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(8, 6, 8, 0))
    style.configure("TNotebook.Tab", background=C["panel"], foreground=C["muted"], padding=(16, 6), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", C["raised"])], foreground=[("selected", C["fg"])])
    style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["fg"],
                    rowheight=int(24 * scale), borderwidth=0)
    style.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", C["fg"])])
    style.configure("Treeview.Heading", background=C["raised"], foreground=C["fg"], relief="flat", padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", "#45474e")])
    style.configure("Vertical.TScrollbar", background=C["raised"], troughcolor=C["bg"], arrowcolor=C["fg"],
                    bordercolor=C["bg"], lightcolor=C["raised"], darkcolor=C["raised"], gripcount=0)
    style.map("Vertical.TScrollbar", background=[("active", "#45474e")])
    style.configure("Status.TFrame", background=C["panel"])
    style.configure("Status.TLabel", background=C["panel"], foreground=C["muted"])
    style.configure("StatusLink.TButton", background=C["panel"], foreground=C["accent"], padding=(8, 0))
    style.map("StatusLink.TButton", background=[("active", C["panel"])], foreground=[("active", C["fg"])])


def themed_menu(parent):
    return tk.Menu(parent, tearoff=False, background=C["panel"], foreground=C["fg"],
                   activebackground=C["select"], activeforeground=C["fg"], borderwidth=0)


class Sparkline(tk.Canvas):
    """Scrolling 0-100 % history graph."""

    def __init__(self, parent, color, points=60, **kwargs):
        super().__init__(parent, height=115, background=C["bg"], highlightthickness=0, **kwargs)
        self.color = color
        self.values = deque([0.0] * points, maxlen=points)
        self.bind("<Configure>", lambda e: self.redraw())

    def push(self, value):
        self.values.append(max(0.0, min(100.0, value or 0.0)))
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        for frac in (0.25, 0.5, 0.75):
            y = h * frac
            self.create_line(0, y, w, y, fill=C["panel"])
        n = len(self.values)
        step = w / (n - 1)
        pts = []
        for i, v in enumerate(self.values):
            pts += [i * step, h - 1 - (h - 2) * v / 100.0]
        self.create_polygon(0, h, *pts, w, h, fill=self._dim(self.color), outline="")
        self.create_line(*pts, fill=self.color, width=2, smooth=False)

    def _dim(self, color):
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
        br, bg_, bb = (int(C["bg"][i:i + 2], 16) for i in (1, 3, 5))
        mix = lambda a, base: int(base + (a - base) * 0.25)
        return f"#{mix(r, br):02x}{mix(g, bg_):02x}{mix(b, bb):02x}"


class CoreBars(tk.Canvas):
    """One small bar per logical CPU."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, height=70, background=C["bg"], highlightthickness=0, **kwargs)
        self.values = []
        self.bind("<Configure>", lambda e: self.redraw())

    def set(self, values):
        self.values = list(values)
        self.redraw()

    def redraw(self):
        self.delete("all")
        n = len(self.values)
        w, h = self.winfo_width(), self.winfo_height()
        if not n or w < 4:
            return
        gap = 3
        bw = max(2.0, (w - gap * (n - 1)) / n)
        for i, v in enumerate(self.values):
            x0 = i * (bw + gap)
            self.create_rectangle(x0, 0, x0 + bw, h - 14, fill=C["panel"], outline="")
            top = (h - 14) * (1 - v / 100.0)
            color = C["red"] if v >= 85 else C["amber"] if v >= 50 else C["accent"]
            self.create_rectangle(x0, top, x0 + bw, h - 14, fill=color, outline="")
            if bw >= 14:
                self.create_text(x0 + bw / 2, h - 6, text=str(i), fill=C["muted"], font=("TkDefaultFont", 7))


class ProcessesTab(ttk.Frame):
    COLUMNS = (
        ("name", "Name", 240, "w"),
        ("pid", "PID", 70, "e"),
        ("user", "User", 200, "w"),
        ("cpu", "CPU %", 70, "e"),
        ("mem", "Memory", 100, "e"),
        ("threads", "Threads", 70, "e"),
        ("status", "Status", 90, "w"),
    )
    SORT_KEYS = {
        "name": lambda p: (p.name.lower(), p.pid),
        "pid": lambda p: p.pid,
        "user": lambda p: (p.user.lower(), p.name.lower()),
        "cpu": lambda p: (p.cpu, p.mem_mb),
        "mem": lambda p: p.mem_mb,
        "threads": lambda p: p.threads,
        "status": lambda p: (p.status, p.name.lower()),
    }

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.latest = {}
        self.rows = {}
        self.sort_col, self.sort_desc = "cpu", True
        self.paused = tk.BooleanVar(value=False)
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.render())

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Search").pack(side="left")
        self.search = ttk.Entry(bar, textvariable=self.query, width=32)
        self.search.pack(side="left", padx=(6, 12))
        ttk.Checkbutton(bar, text="Pause updates", variable=self.paused, command=self.render).pack(side="left")
        self.count = ttk.Label(bar, style="Muted.TLabel")
        self.count.pack(side="left", padx=12)

        ttk.Button(bar, text="Open location", command=self.open_location).pack(side="right")
        ttk.Button(bar, text="End all by name", style="Danger.TButton",
                   command=self.end_by_name).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="End tree", style="Danger.TButton",
                   command=lambda: self.end_selected(tree=True)).pack(side="right", padx=(0, 6))
        ttk.Button(bar, text="End task", style="Danger.TButton",
                   command=self.end_selected).pack(side="right", padx=(0, 6))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(body, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="extended")
        for key, title, width, anchor in self.COLUMNS:
            self.tree.heading(key, text=title, anchor=anchor, command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("name", "user"))
        self.tree.tag_configure("hot", foreground=C["amber"])
        self.tree.tag_configure("system", foreground=C["muted"])
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._update_headings()

        self.menu = themed_menu(self)
        self.menu.add_command(label="End task", command=self.end_selected)
        self.menu.add_command(label="End process tree", command=lambda: self.end_selected(tree=True))
        self.menu.add_command(label="End all with this name", command=self.end_by_name)
        self.menu.add_separator()
        self.menu.add_command(label="Open file location", command=self.open_location)
        self.menu.add_command(label="Copy name", command=lambda: self.copy("name"))
        self.menu.add_command(label="Copy PID", command=lambda: self.copy("pid"))
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Delete>", lambda e: self.end_selected())

    # --- rendering -------------------------------------------------------

    def update_snapshot(self, snap):
        self.latest = snap.procs
        if not self.paused.get():
            self.render()

    def render(self):
        q = self.query.get().strip().lower()
        visible = {
            pid: p for pid, p in self.latest.items()
            if not q or q in p.name.lower() or q in p.user.lower() or q == str(pid)
        }
        tree = self.tree
        stale = [iid for iid in tree.get_children() if int(iid) not in visible]
        if stale:
            tree.delete(*stale)
        for pid, p in visible.items():
            iid = str(pid)
            values = (p.name, pid, p.user or "—", f"{p.cpu:.1f}", fmt_mem(p.mem_mb), p.threads, p.status)
            tags = ("hot",) if p.cpu >= 20 else ("system",) if p.name.lower() in PROTECTED else ()
            if pid not in self.rows or not tree.exists(iid):
                tree.insert("", "end", iid=iid, values=values, tags=tags)
            elif self.rows[pid] != p:
                tree.item(iid, values=values, tags=tags)
        self.rows = visible

        order = [str(p.pid) for p in sorted(visible.values(), key=self.SORT_KEYS[self.sort_col],
                                              reverse=self.sort_desc)]
        if list(tree.get_children()) != order:
            for index, iid in enumerate(order):
                tree.move(iid, "", index)

        total = len(self.latest)
        shown = f"{len(visible)} of {total}" if q else f"{total}"
        self.count.configure(text=f"{shown} processes" + ("  (paused)" if self.paused.get() else ""))

    def sort_by(self, key):
        if self.sort_col == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = key
            self.sort_desc = key in ("cpu", "mem", "threads")
        self._update_headings()
        self.render()

    def _update_headings(self):
        for key, title, _, _ in self.COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if key == self.sort_col else ""
            self.tree.heading(key, text=title + arrow)

    # --- actions ---------------------------------------------------------

    def selected(self):
        return [self.rows[int(iid)] for iid in self.tree.selection() if int(iid) in self.rows]

    def _popup(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        if self.tree.selection():
            self.menu.tk_popup(event.x_root, event.y_root)

    def copy(self, field):
        procs = self.selected()
        if procs:
            self.clipboard_clear()
            self.clipboard_append("\n".join(str(getattr(p, field)) for p in procs))

    def open_location(self):
        procs = self.selected()
        if not procs:
            return
        try:
            exe = psutil.Process(procs[0].pid).exe()
        except (psutil.Error, OSError) as exc:
            messagebox.showerror(DISPLAY_NAME, f"Can't read the file location of {procs[0].name}:\n{exc}", parent=self)
            return
        if exe:
            winutil.open_folder(exe, select=True)

    def end_by_name(self):
        procs = self.selected()
        if not procs:
            return
        name = procs[0].name
        matches = [p for p in self.latest.values() if p.name == name]
        self._end(matches, tree=False, title=f"End all {len(matches)} “{name}” processes?")

    def end_selected(self, tree=False):
        procs = self.selected()
        if procs:
            what = "process tree" if tree else "task"
            self._end(procs, tree=tree, title=f"End {what} for {len(procs)} process(es)?")

    def _end(self, procs, tree, title):
        own = os.getpid()
        procs = [p for p in procs if p.pid != own]
        if not procs:
            return
        names = "\n".join(f"  {p.name}  (PID {p.pid})" for p in procs[:12])
        if len(procs) > 12:
            names += f"\n  … and {len(procs) - 12} more"
        detail = "Unsaved data in these programs will be lost."
        risky = [p for p in procs if p.name.lower() in PROTECTED or p.pid in (0, 4)]
        if risky:
            detail = ("WARNING: this includes Windows system processes. Ending them can crash "
                      "Windows or log you out.\n\n" + detail)
        if not messagebox.askyesno(DISPLAY_NAME, f"{title}\n\n{names}\n\n{detail}",
                                   icon="warning", default="no", parent=self):
            return
        threading.Thread(target=self._kill_worker, args=(procs, tree), daemon=True).start()

    def _kill_worker(self, procs, tree):
        failed, ended = [], 0
        for info in procs:
            try:
                proc = psutil.Process(info.pid)
                # Guard against the PID having been reused since the list was drawn.
                if info.create_time and abs(proc.create_time() - info.create_time) > 1:
                    continue
                targets = proc.children(recursive=True) if tree else []
                targets.append(proc)
                for t in targets:
                    try:
                        t.kill()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(targets, timeout=3)
                if alive:
                    failed.append((info, "did not exit"))
                else:
                    ended += 1
            except psutil.NoSuchProcess:
                ended += 1
            except psutil.AccessDenied:
                failed.append((info, "access denied"))
            except (psutil.Error, OSError) as exc:
                failed.append((info, str(exc)))
        self.app.call_soon(lambda: self._kill_done(ended, failed))

    def _kill_done(self, ended, failed):
        self.app.set_status(f"Ended {ended} process(es)" + (f", {len(failed)} failed" if failed else ""))
        if not failed:
            return
        lines = "\n".join(f"  {p.name} (PID {p.pid}): {why}" for p, why in failed[:12])
        denied = any(why == "access denied" for _, why in failed)
        if denied and sys.platform == "win32" and not winutil.is_admin():
            if messagebox.askyesno(DISPLAY_NAME, f"Couldn't end:\n{lines}\n\nRestart {DISPLAY_NAME} as administrator?",
                                   icon="warning", parent=self):
                self.app.restart_as_admin()
        else:
            messagebox.showwarning(DISPLAY_NAME, f"Couldn't end:\n{lines}", parent=self)


class PerformanceTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.cards = {}
        for key, title, color in (("cpu", "CPU", C["accent"]), ("ram", "Memory", C["purple"]),
                                  ("gpu", "GPU", C["green"])):
            self.cards[key] = self._card(title, color)
        cores = ttk.Frame(self, style="Card.TFrame", padding=12)
        cores.pack(fill="x", pady=(0, 8))
        ttk.Label(cores, text="Logical processors", style="CardTitle.TLabel").pack(anchor="w")
        self.core_bars = CoreBars(cores)
        self.core_bars.configure(background=C["panel"])
        self.core_bars.pack(fill="x", pady=(6, 0))
        self.sysinfo = ttk.Label(self, style="Muted.TLabel")
        self.sysinfo.pack(anchor="w", pady=(4, 0))

    def _card(self, title, color):
        frame = ttk.Frame(self, style="Card.TFrame", padding=12)
        frame.pack(fill="x", pady=(0, 8))
        info = ttk.Frame(frame, style="Card.TFrame", width=230)
        info.pack(side="left", fill="y")
        info.pack_propagate(False)
        ttk.Label(info, text=title, style="CardTitle.TLabel").pack(anchor="w")
        value = ttk.Label(info, text="--", style="CardValue.TLabel", foreground=color)
        value.pack(anchor="w")
        detail = ttk.Label(info, text="", style="CardMuted.TLabel", justify="left")
        detail.pack(anchor="w")
        spark = Sparkline(frame, color)
        spark.configure(background=C["panel"])
        spark.pack(side="left", fill="both", expand=True, padx=(12, 0))
        return value, detail, spark

    def update_snapshot(self, snap):
        value, detail, spark = self.cards["cpu"]
        value.configure(text=f"{snap.cpu:.0f}%")
        freq = f"{snap.cpu_freq / 1000:.2f} GHz · " if snap.cpu_freq else ""
        detail.configure(text=f"{freq}{len(snap.per_cpu)} logical cores")
        spark.push(snap.cpu)

        ram = snap.ram
        value, detail, spark = self.cards["ram"]
        value.configure(text=f"{ram.percent:.0f}%")
        gb = 1024 ** 3
        detail.configure(text=f"{(ram.total - ram.available) / gb:.1f} of {ram.total / gb:.1f} GB in use\n"
                              f"{ram.available / gb:.1f} GB available")
        spark.push(ram.percent)

        value, detail, spark = self.cards["gpu"]
        gpu = snap.gpu
        if gpu:
            value.configure(text=f"{gpu['usage']:.0f}%")
            lines = []
            if gpu.get("name"):
                lines.append(gpu["name"])
            if gpu.get("vram_mb") is not None:
                total = f" of {gpu['vram_total_mb'] / 1024:.1f}" if gpu.get("vram_total_mb") else ""
                lines.append(f"{gpu['vram_mb'] / 1024:.1f}{total} GB dedicated memory")
            if gpu.get("temp") is not None:
                lines.append(f"{gpu['temp']:.0f} °C")
            detail.configure(text="\n".join(lines))
            spark.push(gpu["usage"])
        else:
            value.configure(text="N/A")
            detail.configure(text="No GPU counters available")
            spark.push(0)

        self.core_bars.set(snap.per_cpu)
        uptime = time.time() - psutil.boot_time()
        self.sysinfo.configure(text=f"{len(snap.procs)} processes · up {fmt_duration(uptime)} · "
                                    f"updated {snap.time:%H:%M:%S}")


class ActivityTab(ttk.Frame):
    MAX_ROWS = 5000

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.events = deque(maxlen=50000)
        self.counts = {"STARTED": 0, "STOPPED": 0}
        self.log_path = winutil.data_dir() / LOG_NAME
        self.logger = setup_activity_logger(self.log_path)
        self.write_log = tk.BooleanVar(value=True)
        self.autoscroll = tk.BooleanVar(value=True)
        self.query = tk.StringVar()
        self.kind = tk.StringVar(value="All")
        self.query.trace_add("write", lambda *a: self.rebuild())

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Filter").pack(side="left")
        ttk.Entry(bar, textvariable=self.query, width=26).pack(side="left", padx=(6, 8))
        kind = ttk.Combobox(bar, textvariable=self.kind, values=("All", "Started", "Stopped"),
                            state="readonly", width=9)
        kind.pack(side="left", padx=(0, 12))
        kind.bind("<<ComboboxSelected>>", lambda e: self.rebuild())
        ttk.Checkbutton(bar, text="Auto-scroll", variable=self.autoscroll).pack(side="left")
        ttk.Checkbutton(bar, text="Write to log file", variable=self.write_log).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="right")
        ttk.Button(bar, text="Open log", command=self.open_log).pack(side="right", padx=(0, 6))
        self.summary = ttk.Label(self, style="Muted.TLabel")
        self.summary.pack(anchor="w", pady=(0, 6))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        cols = (("time", "Time", 150, "w"), ("event", "Event", 80, "w"), ("name", "Name", 260, "w"),
                ("pid", "PID", 70, "e"), ("user", "User", 220, "w"))
        self.tree = ttk.Treeview(body, columns=[c[0] for c in cols], show="headings")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title, anchor=anchor)
            self.tree.column(key, width=width, anchor=anchor, stretch=key in ("name", "user"))
        self.tree.tag_configure("STARTED", foreground=C["green"])
        self.tree.tag_configure("STOPPED", foreground=C["red"])
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.baseline = ""

    def update_snapshot(self, snap):
        if snap.first:
            self.baseline = f"Watching since {snap.time:%Y-%m-%d %H:%M:%S} ({len(snap.procs)} processes already running)"
            if self.write_log.get():
                self.logger.info(f"MONITOR STARTED: {DISPLAY_NAME}, {len(snap.procs)} processes running")
        new_rows = []
        for ev in snap.events:
            self.events.append(ev)
            self.counts[ev.kind] += 1
            if self.write_log.get():
                p = ev.proc
                if ev.kind == "STARTED":
                    self.logger.info(f"STARTED: {p.name} (pid={p.pid}, user={p.user or 'unknown'})")
                else:
                    self.logger.info(f"STOPPED: {p.name} (pid={p.pid})")
            if self._matches(ev):
                new_rows.append(ev)
        for ev in new_rows:
            self._insert(ev)
        self._trim()
        if new_rows and self.autoscroll.get():
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])
        self._update_summary()

    def _matches(self, ev):
        kind = self.kind.get()
        if kind != "All" and ev.kind != kind.upper():
            return False
        q = self.query.get().strip().lower()
        return not q or q in ev.proc.name.lower() or q in ev.proc.user.lower() or q == str(ev.proc.pid)

    def _insert(self, ev):
        p = ev.proc
        self.tree.insert("", "end", values=(f"{ev.time:%Y-%m-%d %H:%M:%S}", ev.kind, p.name, p.pid, p.user or "—"),
                         tags=(ev.kind,))

    def _trim(self):
        children = self.tree.get_children()
        if len(children) > self.MAX_ROWS:
            self.tree.delete(*children[:len(children) - self.MAX_ROWS])

    def rebuild(self):
        self.tree.delete(*self.tree.get_children())
        for ev in [e for e in self.events if self._matches(e)][-self.MAX_ROWS:]:
            self._insert(ev)
        children = self.tree.get_children()
        if children and self.autoscroll.get():
            self.tree.see(children[-1])

    def clear(self):
        self.events.clear()
        self.counts = {"STARTED": 0, "STOPPED": 0}
        self.tree.delete(*self.tree.get_children())
        self._update_summary()

    def open_log(self):
        for handler in self.logger.handlers:
            handler.flush()
        if not self.log_path.exists():
            self.log_path.touch()
        winutil.open_folder(self.log_path, select=True)

    def _update_summary(self):
        self.summary.configure(text=f"{self.baseline}  ·  {self.counts['STARTED']} started  ·  "
                                    f"{self.counts['STOPPED']} stopped  ·  log: {self.log_path}")


class TaskPatrolApp(tk.Tk):
    def __init__(self):
        super().__init__(className="TaskPatrol")
        admin = winutil.is_admin()
        self.title(DISPLAY_NAME + ("  (Administrator)" if admin and sys.platform == "win32" else ""))
        self.geometry("1100x720")
        self.minsize(820, 520)
        icon = winutil.resource_path("taskpatrol.ico")
        if sys.platform == "win32" and icon.exists():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        apply_theme(self)
        self._ui_calls = queue.Queue()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        self.processes = ProcessesTab(notebook, self)
        self.performance = PerformanceTab(notebook, self)
        self.activity = ActivityTab(notebook, self)
        notebook.add(self.processes, text="Processes")
        notebook.add(self.performance, text="Performance")
        notebook.add(self.activity, text="Activity log")

        status = ttk.Frame(self, style="Status.TFrame", padding=(10, 4))
        status.pack(fill="x", side="bottom")
        self.status_left = ttk.Label(status, style="Status.TLabel", text="Collecting…")
        self.status_left.pack(side="left")
        self.status_msg = ttk.Label(status, style="Status.TLabel")
        self.status_msg.pack(side="left", padx=16)
        ttk.Button(status, text="About", style="StatusLink.TButton", command=self.about).pack(side="right")
        if sys.platform == "win32" and not admin:
            ttk.Button(status, text="Restart as administrator", style="StatusLink.TButton",
                       command=self.restart_as_admin).pack(side="right")
        ttk.Label(status, style="Status.TLabel", text=f"v{__version__}").pack(side="right", padx=8)

        self.bind_all("<Control-f>", lambda e: (notebook.select(self.processes), self.processes.search.focus_set()))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.sampler = Sampler(interval=1.0)
        self.sampler.start()
        self.after(100, self._poll)

    def call_soon(self, fn):
        """Thread-safe: run fn on the Tk thread."""
        self._ui_calls.put(fn)

    def set_status(self, text):
        self.status_msg.configure(text=text)
        self.after(6000, lambda: self.status_msg.cget("text") == text and self.status_msg.configure(text=""))

    def _poll(self):
        while True:
            try:
                self._ui_calls.get_nowait()()
            except queue.Empty:
                break
        try:
            snap = self.sampler.snapshots.get_nowait()
        except queue.Empty:
            snap = None
        if snap is not None:
            self.processes.update_snapshot(snap)
            self.performance.update_snapshot(snap)
            self.activity.update_snapshot(snap)
            self.status_left.configure(text=f"Processes: {len(snap.procs)}   CPU: {snap.cpu:.0f}%   "
                                            f"Memory: {snap.ram.percent:.0f}%"
                                            + (f"   GPU: {snap.gpu['usage']:.0f}%" if snap.gpu else ""))
        self.after(150, self._poll)

    def about(self):
        messagebox.showinfo(
            f"About {DISPLAY_NAME}",
            f"{DISPLAY_NAME}\n\n"
            "Process killer, CPU / RAM / GPU monitor and process start/stop logger.\n\n"
            f"Version: {__version__}\n"
            f"App ID: {APP_ID}\n"
            f"Installer GUID: {{{INSTALLER_GUID}}}\n"
            f"Data folder: {winutil.data_dir()}\n"
            f"Administrator: {'yes' if winutil.is_admin() else 'no'}",
            parent=self,
        )

    def restart_as_admin(self):
        if winutil.relaunch_as_admin():
            self.on_close()

    def on_close(self):
        self.sampler.stop()
        if self.activity.write_log.get():
            self.activity.logger.info(f"MONITOR STOPPED: {DISPLAY_NAME}")
        logging.shutdown()
        self.destroy()


def main():
    winutil.init_process()
    app = TaskPatrolApp()
    if "--smoke-test" in sys.argv:
        # Used by CI: open the window, process a few snapshots, then exit cleanly.
        app.after(4000, app.on_close)
    app.mainloop()
    return 0
