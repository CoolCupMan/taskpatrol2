"""GPU usage that works for NVIDIA, AMD and Intel.

On Windows the "GPU Engine" performance counters (the ones Task Manager
uses) give vendor-neutral utilization. nvidia-smi, when present, adds the
temperature. The original script only used nvidia-smi, which reports
nothing on AMD cards.
"""

import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict

from taskpatrol.winutil import NO_WINDOW

_ENGINE_RE = re.compile(r"luid_(0x[0-9a-fA-F]+_0x[0-9a-fA-F]+)_phys_(\d+)_eng_(\d+)")


def aggregate_engine_usage(samples):
    """Turn per-process engine counters into a single GPU percentage.

    `samples` maps PDH instance names such as
    "pid_1234_luid_0x0_0xD1C2_phys_0_eng_0_engtype_3D" to a percentage.
    Like Task Manager: sum each engine over all processes, report the busiest.
    """
    per_engine = defaultdict(float)
    for name, value in samples.items():
        match = _ENGINE_RE.search(name)
        if match:
            per_engine[match.groups()] += value
    if not per_engine:
        return 0.0
    return min(100.0, max(per_engine.values()))


class _PdhCounters:
    """Minimal ctypes wrapper for wildcard PDH counters."""

    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_NOCAP100 = 0x00008000
    PDH_MORE_DATA = 0x800007D2

    def __init__(self, paths):
        import ctypes
        from ctypes import wintypes

        class FmtValue(ctypes.Structure):
            _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

        class FmtItem(ctypes.Structure):
            _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", FmtValue)]

        self._ct = ctypes
        self._FmtItem = FmtItem
        self._pdh = ctypes.WinDLL("pdh")
        self._query = wintypes.HANDLE()
        self._check(self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)))
        self._counters = {}
        for key, path in paths.items():
            handle = wintypes.HANDLE()
            self._check(self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(handle)))
            self._counters[key] = handle
        self._pdh.PdhCollectQueryData(self._query)

    @staticmethod
    def _check(status):
        if status & 0xFFFFFFFF:
            raise OSError(f"PDH error 0x{status & 0xFFFFFFFF:08X}")

    def collect(self):
        """Return {key: {instance: value}} since the previous collect."""
        ct = self._ct
        self._check(self._pdh.PdhCollectQueryData(self._query))
        result = {}
        fmt = self.PDH_FMT_DOUBLE | self.PDH_FMT_NOCAP100
        for key, handle in self._counters.items():
            size = ct.c_ulong(0)
            count = ct.c_ulong(0)
            status = self._pdh.PdhGetFormattedCounterArrayW(handle, fmt, ct.byref(size), ct.byref(count), None)
            values = {}
            if status & 0xFFFFFFFF == self.PDH_MORE_DATA and size.value:
                buf = (ct.c_byte * size.value)()
                status = self._pdh.PdhGetFormattedCounterArrayW(handle, fmt, ct.byref(size), ct.byref(count), buf)
                if status & 0xFFFFFFFF == 0:
                    items = ct.cast(buf, ct.POINTER(self._FmtItem))
                    for i in range(count.value):
                        item = items[i]
                        if item.FmtValue.CStatus in (0, 1):  # valid / new data
                            values[item.szName] = item.FmtValue.doubleValue
            result[key] = values
        return result

    def close(self):
        self._pdh.PdhCloseQuery(self._query)


class GpuMonitor:
    """Call sample() roughly once a second from a worker thread."""

    NVSMI_EVERY = 3.0  # seconds between nvidia-smi calls

    def __init__(self):
        self._pdh = None
        if sys.platform == "win32":
            try:
                self._pdh = _PdhCounters({
                    "engine": r"\GPU Engine(*)\Utilization Percentage",
                    "memory": r"\GPU Adapter Memory(*)\Dedicated Usage",
                })
            except (OSError, AttributeError):
                self._pdh = None
        self._nvsmi = shutil.which("nvidia-smi")
        self._nv_last = 0.0
        self._nv_cache = None

    @property
    def available(self):
        return self._pdh is not None or self._nvsmi is not None

    def sample(self):
        """Return dict(usage=%, vram_mb=MB or None, temp=°C or None, name=str or None) or None."""
        usage = vram = None
        if self._pdh is not None:
            try:
                data = self._pdh.collect()
                usage = aggregate_engine_usage(data["engine"])
                if data["memory"]:
                    vram = max(data["memory"].values()) / (1024 * 1024)
            except OSError:
                usage = None
        nv = self._nvidia()
        if nv:
            if usage is None:
                usage = nv["usage"]
            if vram is None:
                vram = nv["vram_mb"]
        if usage is None:
            return None
        return {
            "usage": usage,
            "vram_mb": vram,
            "vram_total_mb": nv["vram_total_mb"] if nv else None,
            "temp": nv["temp"] if nv else None,
            "name": nv["name"] if nv else None,
        }

    def _nvidia(self):
        if not self._nvsmi:
            return None
        now = time.monotonic()
        if now - self._nv_last < self.NVSMI_EVERY:
            return self._nv_cache
        self._nv_last = now
        try:
            out = subprocess.check_output(
                [self._nvsmi,
                 "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total,name",
                 "--format=csv,noheader,nounits"],
                encoding="utf-8", timeout=2, creationflags=NO_WINDOW, stderr=subprocess.DEVNULL,
            )
            first = out.strip().splitlines()[0]
            usage, temp, used, total, name = [part.strip() for part in first.split(",", 4)]
            self._nv_cache = {
                "usage": float(usage), "temp": float(temp),
                "vram_mb": float(used), "vram_total_mb": float(total), "name": name,
            }
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            self._nv_cache = None
            self._nvsmi = None  # stop retrying a broken nvidia-smi
        return self._nv_cache

    def close(self):
        if self._pdh is not None:
            self._pdh.close()
