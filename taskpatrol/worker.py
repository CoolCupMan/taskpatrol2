"""Run the heavy sampling in child processes so it can never freeze the window.

psutil's Windows calls (and the GPU/open-file queries) can hold Python's GIL
for long stretches. In a thread that starves the Tk main loop and Windows
marks the window "Not Responding"; in a separate process it can't.
"""

import multiprocessing as mp
import os
import queue
import time

import psutil


def run_loop(out_q, stop, parent_pid, interval, step):
    """Child-side loop: call step() every `interval` s and ship its result to the parent."""
    while not stop.is_set():
        started = time.monotonic()
        result = step()
        if stop.is_set():
            break
        if result is not None:
            out_q.put(result)
        if not psutil.pid_exists(parent_pid):  # the window was killed: don't linger
            break
        stop.wait(max(0.05, interval - (time.monotonic() - started)))


class WorkerProcess:
    """Parent-side handle: start `target(out_q, stop, parent_pid, *args)` in a child process."""

    def __init__(self, target, *args, name=None):
        ctx = mp.get_context("spawn")
        self._queue = ctx.Queue()
        self._stop = ctx.Event()
        self._proc = ctx.Process(target=target, args=(self._queue, self._stop, os.getpid(), *args),
                                 name=name, daemon=True)

    def start(self):
        self._proc.start()
        return self

    @property
    def alive(self):
        return self._proc.is_alive()

    def drain(self):
        """Every result the child has sent since the last call, oldest first. Never blocks."""
        items = []
        while True:
            try:
                items.append(self._queue.get_nowait())
            except queue.Empty:
                return items
            except (EOFError, OSError):
                return items

    def stop(self, timeout=0.5):
        self._stop.set()
        self._proc.join(timeout)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(0.5)
        self._queue.close()
