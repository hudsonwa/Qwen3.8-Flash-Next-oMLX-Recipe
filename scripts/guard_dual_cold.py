#!/usr/bin/env python3
"""Refuse a second 252K cold-fill when the projection would miss the plan.

Exit 0: dual cold-fill is not requested, or idle + one 252K stays under plan.
Exit 1: dual 252K requested AND (projected > 102 OR now >= 96.8
        OR now >= steady 73 — fleet already holding a 252K).

Replace the old static 74 GB cutoff. 73 GB steady sat under 74 and let a
second 252K through.

Constants (receipts, not live tok/s): idle 69, one-head peak 88, steady 73,
slot 9.25 GB per 252K. Spike = 88 − 69 = 19 GB.
Projected = now + pending_252k * 9.25 + one_head_fill_spike.
"""
from __future__ import annotations

import os
import subprocess
import sys


PLAN_GB = 102.0
SOFT_GB = 96.8
CAP_GB = 107.5
IDLE_GB = 69.0
ONE_HEAD_PEAK_GB = 88.0
STEADY_GB = 73.0
SLOT_252K_GB = 9.25
ONE_HEAD_FILL_SPIKE_GB = ONE_HEAD_PEAK_GB - IDLE_GB  # 19.0


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
    override = os.environ.get("GUARD_NOW_GB")
    if override:
        return _parse_gb(override)
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


def pending_252k(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    env = os.environ.get("GUARD_PENDING_252K")
    if env:
        return int(env)
    if "--pending-252k" in argv:
        i = argv.index("--pending-252k")
        return int(argv[i + 1])
    return 1  # the extra / second 252K when dual is requested


def projected_peak(now_gb: float, pending: int) -> float:
    return now_gb + pending * SLOT_252K_GB + ONE_HEAD_FILL_SPIKE_GB


def refuse_dual(now_gb: float, pending: int) -> tuple:
    """Return (refuse: bool, reason: str). Caller already knows dual is requested."""
    proj = projected_peak(now_gb, pending)
    if now_gb >= SOFT_GB:
        return True, "now %.2f GB >= soft %.1f GB" % (now_gb, SOFT_GB)
    if proj > PLAN_GB:
        return True, "projected %.2f GB > plan %.1f GB" % (proj, PLAN_GB)
    if now_gb >= STEADY_GB:
        return True, (
            "now %.2f GB >= steady %.1f GB (fleet already holding a 252K; "
            "second 252K refused even when projected %.2f <= plan)"
            % (now_gb, STEADY_GB, proj)
        )
    return False, "projected %.2f GB" % proj


def _now_from_argv(argv):
    if "--now-gb" in argv:
        i = argv.index("--now-gb")
        return _parse_gb(argv[i + 1])
    return current_gb(os.environ.get("PORT", "8000"))


def self_test() -> int:
    fails = []

    def check(name, dual, now, pending, expect_refuse):
        if not dual:
            got = False
            why = "dual not requested"
        else:
            got, why = refuse_dual(now, pending)
        ok = got is expect_refuse
        line = "%s dual=%s now=%s pending=%s -> refuse=%s (%s)" % (
            "PASS" if ok else "FAIL", dual, now, pending, got, why,
        )
        print(line)
        if not ok:
            fails.append(name)

    # Must-fail: resident ~73 GB + second 252K.
    check("resident_second_252k", True, 73.0, 1, True)
    # Must-pass: idle ~69 GB + one 252K (dual not requested).
    check("idle_one_252k", False, 69.0, 1, False)
    # Dual from empty: pending=1, now=69 < steady, proj=97.25 <= 102 → allowed.
    check("idle_dual_from_empty", True, 69.0, 1, False)
    check("idle_dual_pending1", True, 69.0, 1, False)
    # ~78 GB + single head (dual not requested) → allow. A static 74
    # gate would fight a one-head settle near 78 GB.
    check("steady78_single_head", False, 78.0, 0, False)
    # Dual from empty with two pending heads: proj=106.5 > 102 → refused.
    check("idle_dual_pending2", True, 69.0, 2, True)
    # Soft line.
    check("soft_fail", True, 96.8, 1, True)
    # Old static 74 would have missed 73; this must not.
    check("old_74_miss", True, 73.0, 1, True)
    # Not a +31 GB addend: 69 + 31 = 100, which is not the projection.
    plus31 = 69.0 + 31.0
    p69 = projected_peak(69.0, 1)
    if abs(plus31 - p69) < 1e-9:
        fails.append("plus31_is_not_projection")
    print("plus31 69+31 = %.2f vs projected 69+1 = %.2f (must differ)" % (plus31, p69))

    # Projection arithmetic (no tok/s).
    p73 = projected_peak(73.0, 1)
    p69 = projected_peak(69.0, 1)
    print("projected 73+1 = %.2f (cite only; not a measured peak)" % p73)
    print("projected 69+1 = %.2f (cite only; not a measured peak)" % p69)
    if abs(p73 - (73.0 + 9.25 + 19.0)) > 1e-9:
        fails.append("proj_73")
    if abs(p69 - (69.0 + 9.25 + 19.0)) > 1e-9:
        fails.append("proj_69")

    if fails:
        print("FAIL: " + ", ".join(fails), file=sys.stderr)
        return 1
    print("ok: guard self-test")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--self-test" in argv:
        return self_test()
    if not dual_requested(argv):
        print("ok: dual cold-fill not requested")
        return 0
    gb = _now_from_argv(argv)
    if gb is None:
        print("FAIL: no server on :8000 — cannot prove fleet is empty", file=sys.stderr)
        return 1
    pending = pending_252k(argv)
    proj = projected_peak(gb, pending)
    no, why = refuse_dual(gb, pending)
    if no:
        print(
            "FAIL: dual cold-fill refused (%s). "
            "phys_footprint now %s GB, pending_252k %s, projected %s GB "
            "(plan %s / soft %s / cap %s). One 252K head only. "
            "Tick during a dual fill was 24.91 s (G1)."
            % (why, gb, pending, proj, PLAN_GB, SOFT_GB, CAP_GB),
            file=sys.stderr,
        )
        return 1
    print(
        "ok: dual-head allowed near idle (phys_footprint %s GB, projected %s GB)"
        % (gb, proj)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
