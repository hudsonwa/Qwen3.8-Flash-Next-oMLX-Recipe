#!/usr/bin/env python3
"""Append-only published receipts under results/.

Refuse overwrite of a committed results/*.json that has a machine stamp
unless --force-replace and CHANGELOG.md names the file. Named protected
set always refuses without that pair (even historical files without a
stamp). Default write = timestamped file; optional *_latest.json pointer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
CHANGELOG = ROOT / "CHANGELOG.md"

PROTECTED = {
    "warm_8slot_results.json",
    "omlx_flash_2way_results.json",
    "omlx27_4way_results.json",
    "p4_combined_results.json",
    "hot_cache_one_brain.json",
    "hot_cache_current.json",
    "hot_cache_one_brain_pr48.json",
    "decode_table.json",
    "decode_table_issue64.json",
    "quality_canary.json",
    "mtp_on_off.json",
}


def is_committed(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return False
    p = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(rel)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return p.returncode == 0


def has_machine_stamp(path: Path) -> bool:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    m = obj.get("machine")
    if not isinstance(m, dict) or not m:
        return False
    return any(k in m for k in ("cpu", "ram_gb", "os", "hw_model", "arch", "measured_at"))


def changelog_names(filename: str) -> bool:
    if not CHANGELOG.is_file():
        return False
    return filename in CHANGELOG.read_text(encoding="utf-8")


def is_protected(path: Path) -> bool:
    name = path.name
    if name in PROTECTED:
        return True
    if name.startswith("hot_cache_") and name.endswith(".json"):
        return True
    if path.exists() and is_committed(path) and has_machine_stamp(path):
        return True
    return False


def refuse_overwrite(path: Path, force_replace: bool = False) -> None:
    path = Path(path)
    if not path.exists():
        return
    if not is_protected(path):
        return
    if force_replace and changelog_names(path.name):
        print("WARN: --force-replace overwriting", path, file=sys.stderr)
        return
    extra = ""
    if force_replace and not changelog_names(path.name):
        extra = " (--force-replace needs a CHANGELOG.md note naming %s)" % path.name
    raise SystemExit(
        "refuse: would overwrite committed/stamped receipt %s%s" % (path, extra)
    )


def timestamped(stem: str) -> Path:
    utc = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return RES / ("%s_%s.json" % (stem, utc))


def write_json(path: Path, obj: dict, force_replace: bool = False, latest: Path | None = None) -> Path:
    path = Path(path)
    refuse_overwrite(path, force_replace=force_replace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.%s" % os.getpid())
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    if latest is not None:
        latest = Path(latest)
        if latest.name.endswith("_latest.json") or latest.name.endswith(".latest.json"):
            latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            raise SystemExit("latest pointer must be named *_latest.json")
    return path


def self_test() -> int:
    dt = RES / "decode_table.json"
    if not dt.is_file():
        print("FAIL: decode_table.json missing", file=sys.stderr)
        return 1
    try:
        refuse_overwrite(dt, force_replace=False)
    except SystemExit as e:
        if "refuse" not in str(e):
            print("FAIL: unexpected", e, file=sys.stderr)
            return 1
    else:
        print("FAIL: should refuse decode_table.json", file=sys.stderr)
        return 1
    try:
        refuse_overwrite(dt, force_replace=True)
    except SystemExit as e:
        msg = str(e)
        if "CHANGELOG" not in msg and "refuse" not in msg:
            print("FAIL: force without matching changelog handling", e, file=sys.stderr)
            return 1
    # force_replace may succeed because CHANGELOG already names decode_table.json
    ghost = RES / "does_not_exist_receipt.json"
    refuse_overwrite(ghost)
    p = timestamped("selftest")
    if "selftest_" not in p.name or not p.name.endswith(".json"):
        print("FAIL: timestamped name", p, file=sys.stderr)
        return 1
    print("PASS: receipt_guard self-test")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    print("usage: python3 scripts/receipt_guard.py --self-test", file=sys.stderr)
    raise SystemExit(2)
