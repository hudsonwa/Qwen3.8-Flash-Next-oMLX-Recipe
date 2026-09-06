#!/usr/bin/env python3
"""Require a paired decode table. Exit 1 if a twin or mode is missing.

Keys are baseline_solo / recipe_solo / baseline_short8 / recipe_short8
(benchmark.py writes label_mode). Do not average solo with short8.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = ("baseline_solo", "recipe_solo", "baseline_short8", "recipe_short8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=str(ROOT / "results" / "decode_table.json"))
    args = ap.parse_args()
    p = Path(args.src)
    if not p.exists():
        print("FAIL: %s missing — run benchmark.py --label baseline then --label recipe "
              "for --mode solo and --mode short8" % p, file=sys.stderr)
        return 1
    data = json.loads(p.read_text())
    runs = data.get("runs") or {}
    missing = [k for k in REQUIRED if k not in runs]
    if missing:
        print("FAIL: unpaired decode table, missing %s. One number with no twin is marketing."
              % ", ".join(missing), file=sys.stderr)
        return 1
    if data.get("temperature") != 0:
        print("FAIL: temperature != 0", file=sys.stderr)
        return 1
    if data.get("thinking") is not False:
        print("FAIL: thinking not off", file=sys.stderr)
        return 1
    print("machine", json.dumps(data.get("machine"), indent=2))
    print("metrics", json.dumps(data.get("metrics"), indent=2))
    print("n", data.get("n"), "omlx", data.get("omlx"), "profile", data.get("profile"))
    print("pass", data.get("pass"), "fails", data.get("fails"))
    for lab in REQUIRED:
        series = runs[lab]
        print("==", lab, "mode", series.get("mode"), "max_tokens", series.get("max_tokens"))
        for name, rec in (series.get("prompts") or {}).items():
            print("  %s  gen_mean=%s  prefill_mean=%s  n_kept=%s  concurrency=%s" % (
                name, rec.get("generation_tok_s_mean"), rec.get("prefill_tok_s_mean"),
                rec.get("n_kept"), rec.get("concurrency")))
    if data.get("fails"):
        print("FAIL: receipt fails:", data["fails"], file=sys.stderr)
        return 1
    if data.get("pass") is not True:
        print("FAIL: pass is not true", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
