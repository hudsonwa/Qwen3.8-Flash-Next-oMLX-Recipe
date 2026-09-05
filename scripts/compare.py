#!/usr/bin/env python3
"""Require a paired baseline vs recipe decode table. Exit 1 if a twin is missing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=str(ROOT / "results" / "decode_table.json"))
    args = ap.parse_args()
    p = Path(args.src)
    if not p.exists():
        print("FAIL: %s missing — run benchmark.py --label baseline then --label recipe" % p,
              file=sys.stderr)
        return 1
    data = json.loads(p.read_text())
    runs = data.get("runs") or {}
    missing = [k for k in ("baseline", "recipe") if k not in runs]
    if missing:
        print("FAIL: unpaired decode table, missing %s. One number with no twin is marketing."
              % ", ".join(missing), file=sys.stderr)
        return 1
    print("machine", json.dumps(data.get("machine"), indent=2))
    print("metrics", json.dumps(data.get("metrics"), indent=2))
    for lab in ("baseline", "recipe"):
        print("==", lab)
        for name, rec in (runs[lab].get("prompts") or {}).items():
            print("  %s  gen_mean=%s  prefill_mean=%s" % (
                name, rec.get("generation_tok_s_mean"), rec.get("prefill_tok_s_mean")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
