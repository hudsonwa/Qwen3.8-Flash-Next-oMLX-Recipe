#!/usr/bin/env python3
"""Fail-closed MTP activation check.

--expect serving: mtp_enabled must be false.
--expect interactive: settings mtp_enabled true, vlm_mtp_enabled false,
checkpoint has mtp. tensors, and a recent server log contains
'Qwen4-Exp Lightning MTP enabled' (or 'Lightning MTP enabled').
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def flash_model(conf: Path) -> tuple[str, dict]:
    d = json.loads((conf / "model_settings.json").read_text())
    for name, m in (d.get("models") or {}).items():
        if "flash" in name.lower():
            return name, m
    raise SystemExit("FAIL: no flash model entry")


def log_has_mtp(conf: Path) -> bool:
    logdir = conf / "logs"
    needles = ("Qwen4-Exp Lightning MTP enabled", "Lightning MTP enabled")
    paths = sorted(logdir.glob("server.log*"), key=lambda p: p.stat().st_mtime, reverse=True)[:4]
    for p in paths:
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if any(n in text for n in needles):
            print("==> MTP log line in", p)
            return True
    return False


def checkpoint_has_mtp(model_src: Path) -> bool:
    names = [n for n in os.listdir(model_src) if os.path.isfile(os.path.join(model_src, n))]
    hits = [n for n in names if n.lower().startswith("mtp.") or "mtp.safetensors" in n.lower()]
    if hits:
        print("==> mtp files:", hits)
        return True
    idx = model_src / "model.safetensors.index.json"
    if idx.is_file():
        try:
            wm = (json.loads(idx.read_text()).get("weight_map") or {})
        except Exception:
            wm = {}
        keys = [k for k in wm if "mtp." in k.lower() or k.lower().startswith("mtp")]
        print("==> mtp index keys:", len(keys))
        return len(keys) > 0
    print("==> mtp files: none")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", required=True, choices=["serving", "interactive"])
    ap.add_argument("--conf", default=os.environ.get("OMLX_HOME") or os.path.expanduser("~/.omlx"))
    ap.add_argument("--model-src", default=os.path.expanduser("~/models/qwen38-flash-next-oq4e-mtp"))
    args = ap.parse_args()
    conf = Path(args.conf)
    name, m = flash_model(conf)
    mtp = m.get("mtp_enabled") is True
    vlm = m.get("vlm_mtp_enabled") is True
    print("model", name, "mtp_enabled", m.get("mtp_enabled"), "vlm_mtp_enabled", m.get("vlm_mtp_enabled"))
    fails = []
    if args.expect == "serving":
        if mtp:
            fails.append("serving profile must have mtp_enabled false")
    else:
        if not mtp:
            fails.append("interactive claim but mtp_enabled is not true")
        if vlm:
            fails.append("vlm_mtp_enabled on without a documented VLM drafter")
        if not checkpoint_has_mtp(Path(args.model_src)):
            fails.append("checkpoint has no mtp.* tensors (filename -mtp is not activation)")
        if not log_has_mtp(conf):
            fails.append("no Lightning MTP enabled line in this-boot logs")
    if fails:
        print("FAIL:", "; ".join(fails), file=sys.stderr)
        return 1
    print("PASS activation matches", args.expect)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
