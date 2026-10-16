"""PyInstaller entry point (an absolute import, unlike taskpatrol/__main__.py)."""

import sys

from taskpatrol.app import main

sys.exit(main())
