"""PyInstaller entry point (an absolute import, unlike taskpatrol/__main__.py)."""

import multiprocessing
import sys

if __name__ == "__main__":
    # Lets the frozen exe start its worker processes (sampler, file watcher).
    multiprocessing.freeze_support()
    from taskpatrol.app import main

    sys.exit(main())
