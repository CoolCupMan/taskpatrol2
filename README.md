# TaskPatrol

TaskPatrol is a Windows task manager, resource monitor and process activity logger. It merges the earlier scripts (the Kivy task killers, the CPU/RAM/GPU monitor, the start/stop loggers and the file access monitor) into one app.

| Tab | What it does |
| --- | --- |
| **Processes** | Live, sortable and searchable list showing name, PID, user, CPU %, memory, disk read/write per second, threads and status. You can **End task**, **End tree** or **End all by name**, and open a process's file location. Right-click and the <kbd>Delete</kbd> key also work. Selection and scroll position survive refreshes. Before ending a process, the app checks its PID hasn't been reused, and it warns before you end Windows system processes. |
| **Performance** | CPU, memory and GPU usage with 60-second graphs, plus a bar for each logical core. GPU usage comes from the Windows "GPU Engine" counters, the same ones Task Manager uses, so it works on **AMD, Intel and NVIDIA** cards. On NVIDIA, temperature and VRAM come from `nvidia-smi`. |
| **Activity log** | Real-time STARTED/STOPPED events with filtering. Events go to a rotating `process_activity_log.txt` that uses the same line format as the old logger. Processes already running at startup become a baseline and aren't logged as "started". |
| **File activity** | Click **Start watching** to see which programs open, close, read or write files in your user folder, or in any folder you pick with **Folder…**. AppData and cache folders are skipped by default to cut noise. Events go to `file_activity_log.txt`. Read/write sizes are per process, so they're approximate when a program has several files open. Run as administrator to include other users' and system processes. |

Every list scrolls 5 rows per mouse-wheel notch (`WHEEL_LINES` in `taskpatrol/app.py`).

If ending a process fails with *access denied*, use **Restart as administrator** in the status bar.

## Side-by-side versions

Each version has its own identity, so you can install and run several versions in parallel. Every identifier comes from `taskpatrol/__init__.py`:

| | Example for 2.1.0 |
| --- | --- |
| Exe | `TaskPatrol-2.1.0.exe` (with a Windows version resource) |
| Installer | `TaskPatrol-2.1.0-Setup.exe` |
| Installer AppId | deterministic GUID, `uuid5(namespace, "TaskPatrol/<version>")` |
| Install folder | `%LOCALAPPDATA%\Programs\TaskPatrol\2.1.0` (per-user) or `Program Files\TaskPatrol\2.1.0` |
| Start menu / Apps & features | `TaskPatrol 2.1.0` |
| Taskbar AppUserModelID | `CoolCupMan.TaskPatrol.2.1.0` |
| Data / log folder | `%LOCALAPPDATA%\TaskPatrol\2.1.0` |
| Mutex (used by the uninstaller) | `TaskPatrol-2.1.0` |

To release a new version, change `__version__` in `taskpatrol/__init__.py` and rebuild. Its installer won't touch older installs. **About** in the app shows the running version's IDs.

## Getting the exe

GitHub Actions builds every push on Windows (`.github/workflows/build.yml`). It runs the tests, builds the exe and installer, smoke-tests the exe, then does a silent install and uninstall. The first build of each version also commits both files to [`downloads/`](downloads/), giving public direct links:

- [TaskPatrol-2.1.0-Setup.exe](https://github.com/CoolCupMan/taskpatrol2/raw/claude/eloquent-thompson-r90qmf/downloads/TaskPatrol-2.1.0-Setup.exe) (installer)
- [TaskPatrol-2.1.0.exe](https://github.com/CoolCupMan/taskpatrol2/raw/claude/eloquent-thompson-r90qmf/downloads/TaskPatrol-2.1.0.exe) (portable)

Every run's files are also available under its **Artifacts**. Pushing a `v*` tag also attaches them to a GitHub Release.

To build locally on Windows (Python 3.10+; [Inno Setup 6](https://jrsoftware.org/isinfo.php) is needed only for the installer):

```powershell
pip install -r requirements-build.txt
python packaging\build.py          # -> dist\TaskPatrol-2.1.0.exe and dist\TaskPatrol-2.1.0-Setup.exe
```

To run from source: `pip install -r requirements.txt`, then `python -m taskpatrol`.
