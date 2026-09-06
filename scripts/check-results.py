#!/usr/bin/env python3
"""Fail-closed schema check for committed results/*.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"

HISTORICAL = {
    "warm_8slot_results.json",
    "omlx_flash_2way_results.json",
    "omlx27_4way_results.json",
    "p4_combined_results.json",
}
MEASUREMENT = {
    "single_head_latency.json",
    "prefix_hit_miss.json",
    "context_scaling.json",
    "two_lane_latency.json",
    "latency_percentiles.json",
    "ab_sweep.json",
    "ab_8vs4_live.json",
    "mtp_on_off.json",
    "hot_cache_one_brain.json",
}
HOT = {
    "hot_cache_one_brain.json",
    "hot_cache_current.json",
}
PROJECTION = {"guard_projection.json"}

NEED = ("machine", "omlx", "hf_revision", "n", "profile", "prompt_tokens")


def machine_ok(m) -> bool:
    if not isinstance(m, dict) or not m:
        return False
    return any(k in m for k in ("cpu", "ram_gb", "os", "hw_model", "arch"))


def has_pass_fails(obj: dict) -> bool:
    if "pass" in obj and isinstance(obj["pass"], bool):
        return True
    if "fails" in obj and isinstance(obj["fails"], list):
        return True
    return False


def hot_size(obj: dict) -> bool:
    if obj.get("hot_cache_max_size") not in (None, ""):
        return True
    if obj.get("settings_hot_cache_max_size") not in (None, ""):
        return True
    return False


def main() -> int:
    fails: list[str] = []
    files = sorted(RES.glob("*.json"))
    if not files:
        print("FAIL: no results/*.json", file=sys.stderr)
        return 1
    names = {p.name for p in files}
    for req in HOT | MEASUREMENT | PROJECTION | HISTORICAL:
        if req not in names:
            fails.append("missing committed receipt %s" % req)

    for p in files:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            fails.append("%s parse: %s" % (p.name, e))
            continue
        if not isinstance(obj, dict):
            fails.append("%s not a JSON object" % p.name)
            continue
        if p.name in HISTORICAL:
            continue
        if not machine_ok(obj.get("machine")):
            fails.append("%s lacks machine stamp" % p.name)
        if p.name in PROJECTION:
            kind = str(obj.get("kind") or "")
            if "projection" not in kind.lower():
                fails.append("%s is not marked projection" % p.name)
            continue
        if p.name in MEASUREMENT:
            for k in NEED:
                if k not in obj:
                    fails.append("%s missing %s" % (p.name, k))
            if not has_pass_fails(obj):
                fails.append("%s missing pass/fails" % p.name)
        if p.name in HOT and not hot_size(obj):
            fails.append("%s missing hot_cache_max_size" % p.name)
        # any other non-historical JSON still needs machine (checked above)

    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print("PASS: results schema (%d json files)" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
