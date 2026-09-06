#!/usr/bin/env python3
"""L4 / issue #43: refuse dual cold-fill while the fleet is resident.

Exit 0: dual cold-fill is not requested, or footprint is near idle.
Exit 1: --dual-head (or DUAL_HEAD=1) and phys_footprint current >= 74 GB.
"""
from __future__ import annotations

import os
import subprocess
import sys


RESIDENT_GB = 74.0  # idle ~69; a live 252K fill sits ~88


def _parse_gb(x):
    if x is None:
        return None
    s = str(x).strip().upper().replace(",", "")
    try:
        if s.endswith("GB"):
            s = s[:-2]
        elif s.endswith("G"):
            s = s[:-1]
        return float(s.strip())
    except ValueError:
        return None


def current_gb(port: str = "8000"):
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:%s" % port, "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return None
    pid = out.split()[0]
    res = subprocess.run(
        ["/usr/bin/footprint", pid], capture_output=True, text=True, timeout=60,
    ).stdout
    for line in res.splitlines():
        if "phys_footprint:" in line and "peak" not in line:
            return _parse_gb(line.split()[1])
    return None


def dual_requested(argv=None) -> bool:
    argv = argv if argv is not None else sys.argv[1:]
    if os.environ.get("DUAL_HEAD") == "1":
        return True
    return "--dual-head" in argv


def main() -> int:
    if not dual_requested():
        print("ok: dual cold-fill not requested")
        return 0
    gb = current_gb(os.environ.get("PORT", "8000"))
    if gb is None:
        print("FAIL: no server on :8000 — cannot prove fleet is empty", file=sys.stderr)
        return 1
    if gb >= RESIDENT_GB:
        print(
            "FAIL: dual cold-fill refused while fleet resident "
            "(phys_footprint %s GB >= %s). One 252K head only. "
            "Tick during a dual fill was 24.91 s (G1)."
            % (gb, RESIDENT_GB),
            file=sys.stderr,
        )
        return 1
    print("ok: dual-head allowed near idle (phys_footprint %s GB)" % gb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
