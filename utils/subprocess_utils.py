from __future__ import annotations

import os
import subprocess


def no_window_creation_flags() -> int:
    """Return flags that keep command-line child processes hidden on Windows."""
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW
    return 0
