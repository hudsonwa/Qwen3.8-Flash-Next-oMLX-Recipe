#!/usr/bin/env python3
"""Atomic oMLX config patcher. Default is dry-run.

Does not silently replace the 8-slot serving profile.
Modes: serving (default recipe), interactive (MTP on, documented),
baseline (stock scheduler for A/B only).

Backup, patch only listed keys, write, read-back.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

SERVING = {
    "settings": {
        ("scheduler", "chunked_prefill"): True,
        ("scheduler", "max_concurrent_requests"): 8,
        ("scheduler", "prefill_priority"): "context",
        ("scheduler", "decode_fairness"): True,
        ("memory", "prefill_memory_guard"): True,
        ("memory", "memory_guard_tier"): "balanced",
        ("memory", "soft_threshold"): 0.85,
        ("memory", "hard_threshold"): 0.95,
    },
    "model": {
        "mtp_enabled": False,
        "mtp_num_draft_tokens": 3,
        "vlm_mtp_enabled": False,
        "max_context_window": 262144,
        "qwen4_ple_ssd_offload": True,
    },
}

INTERACTIVE = {
    "settings": dict(SERVING["settings"]),
    "model": {
        "mtp_enabled": True,
        "mtp_num_draft_tokens": 6,
        "vlm_mtp_enabled": False,
        "max_context_window": 262144,
        "qwen4_ple_ssd_offload": True,
    },
}

BASELINE = {
    "settings": {
        ("scheduler", "chunked_prefill"): False,
        ("scheduler", "max_concurrent_requests"): 1,
    },
    "model": {
        "mtp_enabled": False,
        "vlm_mtp_enabled": False,
    },
}

MODES = {"serving": SERVING, "interactive": INTERACTIVE, "baseline": BASELINE}


def nest_set(d: dict, path: tuple, value):
    cur = d
    for k in path[:-1]:
        cur = cur.setdefault(k, {})
    cur[path[-1]] = value


def nest_get(d: dict, path: tuple):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def flash_entry(models: dict) -> tuple[str, dict]:
    for name, m in models.items():
        if "flash" in name.lower():
            return name, m
    raise SystemExit("FAIL: no flash-next model entry")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=sorted(MODES))
    ap.add_argument("--conf", default=os.environ.get("OMLX_HOME") or os.path.expanduser("~/.omlx"))
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    args = ap.parse_args()
    conf = Path(args.conf)
    settings_p = conf / "settings.json"
    models_p = conf / "model_settings.json"
    if not settings_p.is_file() or not models_p.is_file():
        print("FAIL: missing settings under", conf, file=sys.stderr)
        return 1
    spec = MODES[args.mode]
    settings = json.loads(settings_p.read_text())
    models = json.loads(models_p.read_text())
    name, ment = flash_entry(models.setdefault("models", {}))
    print("mode=%s apply=%s conf=%s model=%s" % (args.mode, args.apply, conf, name))
    for path, val in spec["settings"].items():
        old = nest_get(settings, path)
        print("  settings.%s: %r -> %r" % (".".join(path), old, val))
        nest_set(settings, path, val)
    for k, val in spec["model"].items():
        print("  model.%s: %r -> %r" % (k, ment.get(k), val))
        ment[k] = val
    if not args.apply:
        print("dry-run (pass --apply to write + read-back)")
        return 0
    stamp = time.strftime("%Y%m%dT%H%M%S")
    bak = conf / "backups"
    bak.mkdir(parents=True, exist_ok=True)
    shutil.copy2(settings_p, bak / ("settings.json." + stamp))
    shutil.copy2(models_p, bak / ("model_settings.json." + stamp))
    settings_p.write_text(json.dumps(settings, indent=2) + "\n")
    models_p.write_text(json.dumps(models, indent=2) + "\n")
    s2 = json.loads(settings_p.read_text())
    m2 = json.loads(models_p.read_text())
    _, ment2 = flash_entry(m2.get("models") or {})
    bad = 0
    for path, val in spec["settings"].items():
        if nest_get(s2, path) != val:
            print("FAIL read-back settings", path, file=sys.stderr)
            bad += 1
    for k, val in spec["model"].items():
        if ment2.get(k) != val:
            print("FAIL read-back model", k, file=sys.stderr)
            bad += 1
    if bad:
        return 1
    print("PASS wrote + read-back backups in", bak)
    if args.mode != "serving":
        print("NOTE: serving profile is no longer live until --mode serving --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
