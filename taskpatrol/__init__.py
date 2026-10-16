"""TaskPatrol - process killer, resource monitor and process activity logger.

This module is the single source of truth for the app's identity. Every
version gets its own installer AppId, install folder, Start-menu entry,
Windows AppUserModelID, data folder and mutex, so several versions can be
installed and run side by side.
"""

import uuid

__version__ = "2.1.1"

APP_NAME = "TaskPatrol"
PUBLISHER = "CoolCupMan"

# Fixed namespace: never change it, or every version's installer GUID changes.
_GUID_NAMESPACE = uuid.UUID("6f0b6c1e-3b8f-4f9a-9d1c-5a7e2c4b8d10")

# Unique, deterministic per-version identifiers.
APP_ID = f"{PUBLISHER}.{APP_NAME}.{__version__}"
INSTALLER_GUID = str(uuid.uuid5(_GUID_NAMESPACE, f"{APP_NAME}/{__version__}")).upper()
MUTEX_NAME = f"Local\\{APP_NAME}-{__version__}"
DISPLAY_NAME = f"{APP_NAME} {__version__}"
