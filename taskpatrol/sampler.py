"""Sampling of processes and system resources.

Sampler runs in its own process (see run_sampler and worker.py) and sends a
picklable Snapshot to the window once per interval.
"""

import time
from collections import namedtuple
from dataclasses import dataclass, field
from datetime import datetime

import psutil

from taskpatrol.gpu import GpuMonitor
from taskpatrol.worker import run_loop

Ram = namedtuple("Ram", "total available percent")

# Thread counts need a full system snapshot per process on Windows; refresh them less often.
THREADS_EVERY = 5


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    user: str
    cpu: float  # percent of the whole machine, like Task Manager
    mem_mb: float
    threads: int
    create_time: float
    read_bps: float = 0.0  # disk I/O bytes per second
    write_bps: float = 0.0

    @property
    def key(self):
        # (pid, create_time) survives PID reuse, unlike the bare PID.
        return (self.pid, self.create_time)


@dataclass(frozen=True)
class Event:
    time: datetime
    kind: str  # "STARTED" or "STOPPED"
    proc: ProcInfo


@dataclass
class Snapshot:
    time: datetime
    procs: dict  # pid -> ProcInfo
    events: list = field(default_factory=list)
    cpu: float = 0.0
    per_cpu: list = field(default_factory=list)
    cpu_freq: float = None
    ram: Ram = None
    gpu: dict = None
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    first: bool = False


def diff_processes(previous, current, now):
    """Return STARTED/STOPPED events between two {pid: ProcInfo} maps."""
    prev_keys = {p.key: p for p in previous.values()}
    curr_keys = {p.key: p for p in current.values()}
    events = [Event(now, "STOPPED", prev_keys[k]) for k in prev_keys.keys() - curr_keys.keys()]
    events += [Event(now, "STARTED", curr_keys[k]) for k in curr_keys.keys() - prev_keys.keys()]
    events.sort(key=lambda e: (e.kind != "STOPPED", e.proc.name.lower(), e.proc.pid))
    return events


class Sampler:
    def __init__(self):
        self._users = {}  # (pid, create_time) -> username; lookups are slow on Windows
        self._io = {}  # (pid, create_time) -> (read_bytes, write_bytes) at the previous sample
        self._threads = {}  # (pid, create_time) -> thread count
        self._previous = None
        self._disk_io = None
        self._last = None  # monotonic time of the previous sample
        self._elapsed = 0.0
        self._tick = 0
        self._ncpu = psutil.cpu_count() or 1
        self._gpu = GpuMonitor()
        psutil.cpu_percent(percpu=True)

    def close(self):
        self._gpu.close()

    def take(self):
        now = datetime.now()
        mono = time.monotonic()
        self._elapsed = max(0.1, mono - self._last) if self._last else 0.0
        self._last = mono
        self._tick += 1
        procs = {}
        for proc in psutil.process_iter():
            info = self._read(proc)
            if info is not None:
                procs[info.pid] = info
        live = {p.key for p in procs.values()}
        for cache in (self._users, self._io, self._threads):
            for key in cache.keys() - live:
                del cache[key]

        disk_read = disk_write = 0.0
        try:
            disk = psutil.disk_io_counters()
        except (OSError, RuntimeError):
            disk = None
        if disk is not None:
            if self._disk_io is not None and self._elapsed:
                disk_read = max(0, disk.read_bytes - self._disk_io[0]) / self._elapsed
                disk_write = max(0, disk.write_bytes - self._disk_io[1]) / self._elapsed
            self._disk_io = (disk.read_bytes, disk.write_bytes)

        per_cpu = psutil.cpu_percent(percpu=True)
        try:
            freq = psutil.cpu_freq()
            freq = freq.current if freq else None
        except (OSError, NotImplementedError, AttributeError):
            freq = None
        try:
            gpu = self._gpu.sample()
        except Exception:  # GPU is optional; never let it kill the sampler
            gpu = None
        vm = psutil.virtual_memory()

        previous, self._previous = self._previous, procs
        return Snapshot(
            time=now,
            procs=procs,
            events=[] if previous is None else diff_processes(previous, procs, now),
            cpu=sum(per_cpu) / len(per_cpu) if per_cpu else 0.0,
            per_cpu=per_cpu,
            cpu_freq=freq,
            ram=Ram(vm.total, vm.available, vm.percent),
            gpu=gpu,
            disk_read_bps=disk_read,
            disk_write_bps=disk_write,
            first=previous is None,
        )

    def _read(self, proc):
        try:
            with proc.oneshot():
                name = proc.name() or "?"
                try:
                    ctime = proc.create_time()
                except psutil.AccessDenied:
                    ctime = 0.0
                key = (proc.pid, ctime)
                user = self._users.get(key)
                if user is None:
                    try:
                        user = proc.username() or ""
                    except (psutil.AccessDenied, OSError):
                        user = ""
                    self._users[key] = user
                try:
                    cpu = proc.cpu_percent(None) / self._ncpu
                except psutil.AccessDenied:
                    cpu = 0.0
                try:
                    mem = proc.memory_info().rss / (1024 * 1024)
                except psutil.AccessDenied:
                    mem = 0.0
                threads = self._threads.get(key)
                if threads is None or self._tick % THREADS_EVERY == 0:
                    try:
                        threads = proc.num_threads()
                    except psutil.AccessDenied:
                        threads = 0
                    self._threads[key] = threads
                read_bps = write_bps = 0.0
                try:
                    io = proc.io_counters()
                    prev = self._io.get(key)
                    if prev is not None and self._elapsed:
                        read_bps = max(0, io.read_bytes - prev[0]) / self._elapsed
                        write_bps = max(0, io.write_bytes - prev[1]) / self._elapsed
                    self._io[key] = (io.read_bytes, io.write_bytes)
                except (psutil.AccessDenied, AttributeError, NotImplementedError):
                    pass
            return ProcInfo(proc.pid, name, user, cpu, mem, threads, ctime, read_bps, write_bps)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return None
        except psutil.AccessDenied:
            return ProcInfo(proc.pid, "?", "", 0.0, 0.0, 0, 0.0)


def run_sampler(out_q, stop, parent_pid, interval=1.0):
    """Child-process entry point."""
    sampler = Sampler()
    try:
        run_loop(out_q, stop, parent_pid, interval, sampler.take)
    finally:
        sampler.close()


def merge_snapshots(snaps):
    """Fold several snapshots into the newest one without losing any events."""
    if not snaps:
        return None
    latest = snaps[-1]
    if len(snaps) > 1:
        latest.events = [e for s in snaps for e in s.events]
        latest.first = any(s.first for s in snaps)
    return latest
