#!/usr/bin/env python3
"""Machine / software stamp for results JSON. No hostnames, no user paths."""
from __future__ import annotations

import os
import platform
import subprocess
import time


def _cmd(args: list[str]) -> str | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def hf_revision() -> str | None:
    """Pinned Hub revision from MODELS.md (no local paths)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "MODELS.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    import re
    m = re.search(r"`([0-9a-f]{40})`", text)
    return m.group(1) if m else None


def machine_stamp() -> dict:
    mem = _cmd(["sysctl", "-n", "hw.memsize"])
    ram_gb = int(mem) // (1024 ** 3) if mem and mem.isdigit() else None
    omlx = os.path.expanduser("~/.omlx/bin/omlx")
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "os": "%s %s" % (platform.system(), platform.release()),
        "os_version": _cmd(["sw_vers", "-productVersion"]),
        "hw_model": _cmd(["sysctl", "-n", "hw.model"]),
        "cpu": _cmd(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "ram_gb": ram_gb,
        "arch": platform.machine(),
        "omlx": _cmd([omlx, "--version"]) if os.path.isfile(omlx) else None,
    }
