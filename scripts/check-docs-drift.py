#!/usr/bin/env python3
"""Fail if README / AGENT.md / docs/PROFILE.md disagree on daily pins.

Daily pins: hot=0, MTP off, max_concurrent_requests=8, oMLX 0.6.4,
HF revision from MODELS.md. Does not run oMLX or Metal.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OMLX = "0.6.4"
HF = "2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8"


def load(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def main() -> int:
    fails: list[str] = []
    readme = load("README.md")
    agent = load("AGENT.md")
    profile = load("docs/PROFILE.md")
    models = load("MODELS.md")
    trio = [("README.md", readme), ("AGENT.md", agent), ("docs/PROFILE.md", profile)]

    if HF not in models:
        fails.append("MODELS.md missing HF pin")
    if OMLX not in models:
        fails.append("MODELS.md missing oMLX %s" % OMLX)

    for name, text in trio:
        if OMLX not in text:
            fails.append("%s missing oMLX %s" % (name, OMLX))
        hot_ok = (
            "hot=0" in text
            or "hot-cache remains **0**" in text
            or "Daily hot-cache remains **0**" in text
            or "`0` (disabled)" in text
        )
        if not hot_ok:
            fails.append("%s missing daily hot=0" % name)
        mtp_ok = (
            "MTP off" in text
            or "Leave MTP off" in text
            or "Do **not** enable MTP" in text
            or "mtp_enabled: false" in text
        )
        if not mtp_ok:
            fails.append("%s missing MTP off" % name)
        mc_ok = (
            "max_concurrent_requests=8" in text
            or "mc=8" in text
            or "max_concurrent_requests=8" in text.replace(" ", "")
        )
        if name != "docs/PROFILE.md" and not mc_ok:
            fails.append("%s missing mc=8" % name)
        if name == "docs/PROFILE.md" and "mc=8" not in text and "max_concurrent_requests=8" not in text:
            fails.append("docs/PROFILE.md missing mc=8")

    revs = set(re.findall(r"\b[0-9a-f]{40}\b", "\n".join(t for _, t in trio) + "\n" + models))
    if HF not in revs:
        fails.append("HF pin %s not found" % HF)
    extra = revs - {HF}
    if extra:
        fails.append("HF revision disagreement %s" % sorted(extra))

    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print("PASS: docs drift (hot=0, MTP off, mc=8, oMLX %s, HF %s)" % (OMLX, HF[:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
