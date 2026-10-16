import uuid
from datetime import datetime

import taskpatrol
from taskpatrol.gpu import aggregate_engine_usage
from taskpatrol.sampler import ProcInfo, Sampler, diff_processes


def proc(pid, name, ctime=100.0):
    return ProcInfo(pid, name, "user", 0.0, 1.0, "running", 1, ctime)


def test_diff_detects_started_and_stopped():
    now = datetime.now()
    prev = {1: proc(1, "a.exe"), 2: proc(2, "b.exe")}
    curr = {2: proc(2, "b.exe"), 3: proc(3, "c.exe")}
    events = diff_processes(prev, curr, now)
    assert [(e.kind, e.proc.name) for e in events] == [("STOPPED", "a.exe"), ("STARTED", "c.exe")]


def test_diff_detects_pid_reuse():
    events = diff_processes({7: proc(7, "old.exe", 1.0)}, {7: proc(7, "new.exe", 2.0)}, datetime.now())
    assert [(e.kind, e.proc.name) for e in events] == [("STOPPED", "old.exe"), ("STARTED", "new.exe")]


def test_diff_ignores_metric_changes():
    a = proc(5, "x.exe")
    b = ProcInfo(5, "x.exe", "user", 50.0, 99.0, "running", 4, a.create_time)
    assert diff_processes({5: a}, {5: b}, datetime.now()) == []


def test_gpu_engine_aggregation_sums_per_engine_and_takes_max():
    samples = {
        "pid_1_luid_0x0_0xABC_phys_0_eng_0_engtype_3D": 20.0,
        "pid_2_luid_0x0_0xABC_phys_0_eng_0_engtype_3D": 15.0,
        "pid_2_luid_0x0_0xABC_phys_0_eng_3_engtype_VideoDecode": 30.0,
        "garbage": 99.0,
    }
    assert aggregate_engine_usage(samples) == 35.0
    assert aggregate_engine_usage({}) == 0.0
    assert aggregate_engine_usage({"pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D": 250.0}) == 100.0


def test_identity_is_unique_per_version():
    assert taskpatrol.__version__ in taskpatrol.APP_ID
    assert taskpatrol.__version__ in taskpatrol.MUTEX_NAME
    uuid.UUID(taskpatrol.INSTALLER_GUID)
    other = uuid.uuid5(taskpatrol._GUID_NAMESPACE, f"{taskpatrol.APP_NAME}/9.9.9")
    assert str(other).upper() != taskpatrol.INSTALLER_GUID


def test_sampler_produces_snapshots():
    sampler = Sampler(interval=0.2)
    sampler.start()
    try:
        first = sampler.snapshots.get(timeout=10)
        assert first.first and first.procs and first.ram is not None
    finally:
        sampler.stop()
        sampler.join(timeout=5)


def test_file_diff_and_activity(tmp_path):
    from taskpatrol.filewatch import diff_open_files, io_activity

    now = datetime.now()
    a, b = str(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    prev = {a: {(10, "word.exe")}}
    curr = {a: {(10, "word.exe"), (11, "backup.exe")}, b: {(10, "word.exe")}}
    events = diff_open_files(prev, curr, now)
    assert {(e.kind, e.path, e.pid) for e in events} == {("OPENED", a, 11), ("OPENED", b, 10)}
    assert [(e.kind, e.pid) for e in diff_open_files(curr, {}, now)].count(("CLOSED", 10)) == 2

    acts = io_activity(curr, {10: (100, 0), 11: (0, 0)}, {10: (100, 2048), 11: (0, 0)}, now)
    assert sorted((e.path, e.detail) for e in acts) == [(a, "write +2.0 KB"), (b, "write +2.0 KB")]


def test_path_filter(tmp_path):
    from taskpatrol.filewatch import PathFilter

    wanted = PathFilter(tmp_path, ignores=[tmp_path / "AppData"])
    assert wanted(tmp_path / "docs" / "x.txt")
    assert not wanted(tmp_path / "AppData" / "Local" / "x.db")
    assert not wanted(str(tmp_path) + "-other/x.txt")


def test_file_watcher_sees_open_file(tmp_path):
    import subprocess
    import sys
    import time

    from taskpatrol.filewatch import FileWatcher

    target = tmp_path / "held.txt"
    target.write_text("x")
    holder = subprocess.Popen([sys.executable, "-c",
                               f"f=open({str(target)!r}); import time; time.sleep(30)"])
    try:
        time.sleep(1.0)
        watcher = FileWatcher(tmp_path, interval=0.3)
        watcher.start()
        stats = watcher.results.get(timeout=20)
        watcher.stop()
        assert any(e.kind == "OPENED" and e.pid == holder.pid for e in stats.events)
    finally:
        holder.kill()
