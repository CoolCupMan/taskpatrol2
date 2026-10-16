"""File access watcher: which processes open, close and read/write files in a folder.

Built on the idea of the old fs_access_monitor script. psutil can't see
individual reads and writes, so ACTIVITY events pair a process's I/O byte
counters with the watched files it holds open. That's an approximation:
the bytes may belong to other files the process has open.
"""

import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psutil

from taskpatrol.worker import run_loop


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def default_ignores(root):
    """Folders under the home directory that are mostly app caches and pure noise."""
    root = Path(root)
    return [root / "AppData", root / ".cache"]


@dataclass(frozen=True)
class FileEvent:
    time: datetime
    kind: str  # OPENED, CLOSED or ACTIVITY
    path: str
    pid: int
    name: str
    detail: str = ""


@dataclass
class ScanStats:
    time: datetime
    files: int
    procs: int
    denied: int
    scan_ms: float
    first: bool = False
    events: list = field(default_factory=list)


class PathFilter:
    """Case-insensitive on Windows: is a path inside root and outside every ignored folder?"""

    def __init__(self, root, ignores=()):
        self.root = self._norm(root)
        self.ignores = [self._norm(p) for p in ignores]

    @staticmethod
    def _norm(path):
        return os.path.normcase(os.path.normpath(str(path)))

    @staticmethod
    def _inside(path, folder):
        return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)

    def __call__(self, path):
        path = self._norm(path)
        return self._inside(path, self.root) and not any(self._inside(path, i) for i in self.ignores)


def diff_open_files(previous, current, now, first=False):
    """previous/current: {path: {(pid, name)}}. Returns OPENED and CLOSED events."""
    events = []
    for path in sorted(previous.keys() | current.keys()):
        old, new = previous.get(path, set()), current.get(path, set())
        for pid, name in sorted(old - new):
            events.append(FileEvent(now, "CLOSED", path, pid, name))
        for pid, name in sorted(new - old):
            events.append(FileEvent(now, "OPENED", path, pid, name, "already open" if first else ""))
    return events


def io_activity(open_files, previous_io, current_io, now):
    """ACTIVITY events for processes whose I/O counters grew while holding watched files."""
    held = defaultdict(list)
    for path, holders in open_files.items():
        for pid, name in holders:
            held[pid].append((path, name))
    events = []
    for pid, (read, write) in sorted(current_io.items()):
        prev = previous_io.get(pid)
        if prev is None:
            continue
        dr, dw = read - prev[0], write - prev[1]
        if dr <= 0 and dw <= 0:
            continue
        parts = ([f"read +{fmt_bytes(dr)}"] if dr > 0 else []) + ([f"write +{fmt_bytes(dw)}"] if dw > 0 else [])
        for path, name in sorted(held.get(pid, [])):
            events.append(FileEvent(now, "ACTIVITY", path, pid, name, ", ".join(parts)))
    return events


class FileScanner:
    """Each scan() lists watched files held open and diffs against the previous scan."""

    def __init__(self, root, ignores=()):
        self.root = str(root)
        self.wanted = PathFilter(root, ignores)
        self._previous, self._previous_io = {}, {}
        self._first = True

    def scan(self):
        started = time.monotonic()
        files, io, procs, denied = self._collect()
        now = datetime.now()
        events = (diff_open_files(self._previous, files, now, self._first)
                  + io_activity(files, self._previous_io, io, now))
        stats = ScanStats(now, len(files), procs, denied, (time.monotonic() - started) * 1000, self._first, events)
        self._previous, self._previous_io, self._first = files, io, False
        return stats

    def _collect(self):
        own = os.getppid(), os.getpid()  # skip TaskPatrol itself (window and this worker)
        files = defaultdict(set)
        io = {}
        holders = set()
        denied = 0
        for proc in psutil.process_iter(["name"]):
            if proc.pid in (0, 4) or proc.pid in own:
                continue
            try:
                opened = proc.open_files()
            except psutil.AccessDenied:
                denied += 1
                continue
            except (psutil.Error, OSError):
                continue
            name = proc.info.get("name") or "?"
            for f in opened:
                path = os.path.normpath(f.path)
                if self.wanted(path):
                    files[path].add((proc.pid, name))
                    holders.add(proc.pid)
            if proc.pid in holders:
                try:
                    c = proc.io_counters()
                    io[proc.pid] = (c.read_bytes, c.write_bytes)
                except (psutil.Error, OSError, AttributeError, NotImplementedError):
                    pass
        return dict(files), io, len(holders), denied


def run_filewatch(out_q, stop, parent_pid, root, ignores=(), interval=2.0):
    """Child-process entry point."""
    run_loop(out_q, stop, parent_pid, interval, FileScanner(root, ignores).scan)
