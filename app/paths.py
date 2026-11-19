from __future__ import annotations

import sys
from pathlib import Path


def bundle_root() -> Path:
    """Templates and static files. Inside the exe they live in the unpacked bundle."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Ideas, dictionary and counters. Next to the exe, so they survive a restart."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
