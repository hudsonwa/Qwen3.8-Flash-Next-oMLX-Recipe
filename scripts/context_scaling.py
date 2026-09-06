#!/usr/bin/env python3
"""L3 / issue #42: context scaling. Serving. No assumed linearity."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_stamp import hf_revision, machine_stamp  # noqa: E402
from resolve_model import resolve  # noqa: E402

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8000")
SOFT_GB = 96.8
PLAN_GB = 102.0
OUT = ROOT / "results" / "context_scaling.json"
UNIT = (
    "Linear attention layers process the sequence with constant memory per step, while full "
    "attention layers attend to all previous tokens every fourth layer. Multi-token prediction "
    "heads draft several tokens per verification cycle, and an adaptive controller adjusts draft "
    "depth from rolling acceptance statistics. Prefix caching stores previously computed states "
    "so repeated system prompts skip recomputation. "
)
# target measured bands, not labels
TIERS = [
    ("~240k", 252000, 230000, 250000),
    ("~120k", 126000, 110000, 130000),
    ("~60k", 63000, 55000, 70000),
]


def parse_gb(x):
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


def footprint():
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return {"peak_gb": None}
    pid = out.split()[0]
    res = subprocess.run(["/usr/bin/footprint", pid], capture_output=True, text=True, timeout=60).stdout
    peak = None
    for line in res.splitlines():
        if "phys_footprint_peak" in line:
            peak = line.split()[1]
    return {"peak": peak, "peak_gb": parse_gb(peak)}


def mk_prompt(approx_tokens, salt):
    reps = max(1, approx_tokens // 65)
    return f"Read carefully. Reply with exactly: DONE-{salt}\n\n" + UNIT * reps + f"\n[variant {salt}]"


def stream(model, prompt, max_tokens=8):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(BASE.rstrip("/") + "/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    usage = {}
    text = []
    err = None
    try:
        with urllib.request.urlopen(req, timeout=7200) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                p = line[5:].strip()
                if p == "[DONE]":
                    break
                try:
                    o = json.loads(p)
                except Exception:
                    continue
                if o.get("usage"):
                    usage = o["usage"]
                ch = (o.get("choices") or [None])[0] or {}
                delta = (ch.get("delta") or {}).get("content")
                if delta:
                    text.append(delta)
                    if first is None:
                        first = time.perf_counter() - t0
    except Exception as e:
        err = str(e)[:200]
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    return {
        "ttft_s": round(first, 4) if first is not None else None,
        "wall_s": round(time.perf_counter() - t0, 4),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "cached_tokens": int(cached) if cached is not None else None,
        "completion": "".join(text).strip()[:200],
        "error": err,
    }


def main():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    stamp = machine_stamp()
    fails = []
    wu = stream(model, "Reply with the single word: READY\n[variant warmup-l3]", 8)
    print("[l3] warmup dropped", wu.get("wall_s"), flush=True)
    peak_seen = 0.0
    tiers_out = []
    n_count = 3
    for name, approx, lo, hi in TIERS:
        rows = []
        ok = True
        for i in range(n_count):
            salt = time.strftime("%H%M%S") + f"-{name}-{i}"
            rec = stream(model, mk_prompt(approx, salt), 8)
            fp = footprint()
            pg = fp.get("peak_gb") or 0
            peak_seen = max(peak_seen, pg)
            rec["footprint"] = fp
            rec["salt"] = salt
            pt = rec.get("prompt_tokens") or 0
            if rec.get("error"):
                fails.append("%s/%s error" % (name, i)); ok = False
            if (rec.get("cached_tokens") or 0) != 0:
                fails.append("%s/%s cached_tokens %s" % (name, i, rec.get("cached_tokens"))); ok = False
            if not (rec.get("completion") or "").startswith("DONE-"):
                fails.append("%s/%s completion %r" % (name, i, (rec.get("completion") or "")[:60])); ok = False
            if not (lo <= pt <= hi):
                fails.append("%s/%s prompt_tokens %s not in %s-%s" % (name, i, pt, lo, hi)); ok = False
            if pg > SOFT_GB:
                fails.append("%s/%s peak %s > 96.8" % (name, i, pg)); ok = False
            rows.append(rec)
            print("[l3]", name, i, "pt", pt, "wall", rec.get("wall_s"), "peak", pg, flush=True)
        walls = [r["wall_s"] for r in rows if r.get("wall_s") is not None]
        mean_wall = sum(walls) / len(walls) if walls else None
        tiers_out.append({
            "band": name,
            "approx_filler": approx,
            "prompt_tokens": [r["prompt_tokens"] for r in rows],
            "wall_s": [r["wall_s"] for r in rows],
            "ttft_s": [r["ttft_s"] for r in rows],
            "cached_tokens": [r["cached_tokens"] for r in rows],
            "mean_wall_s": round(mean_wall, 4) if mean_wall else None,
            "ok": ok,
            "rows": rows,
        })
    # smallest tier that still works = last ok in 240k,120k,60k walking small
    smallest = None
    for t in reversed(tiers_out):
        if t["ok"]:
            smallest = t["band"]
            break
    # linearity check: report ratio, do not assume
    by = {t["band"]: t["mean_wall_s"] for t in tiers_out}
    ratios = {}
    if by.get("~240k") and by.get("~120k"):
        ratios["wall_240_over_120"] = round(by["~240k"] / by["~120k"], 3)
    if by.get("~120k") and by.get("~60k"):
        ratios["wall_120_over_60"] = round(by["~120k"] / by["~60k"], 3)

    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": [pt for t in tiers_out for pt in t["prompt_tokens"]],
        "ttft_s": [x for t in tiers_out for x in t["ttft_s"]],
        "wall_s": [x for t in tiers_out for x in t["wall_s"]],
        "cached_tokens": [x for t in tiers_out for x in t["cached_tokens"]],
        "n": n_count,
        "tiers": tiers_out,
        "smallest_working_tier": smallest,
        "linearity_ratios": ratios,
        "assumed_linearity": False,
        "profile": "serving",
        "warmup_dropped": True,
        "fails": fails,
        "pass": not fails,
    }
    OUT.write_text(json.dumps(receipt, indent=1) + "\n")
    print("WROTE", OUT, "smallest", smallest, "ratios", ratios, "pass", receipt["pass"],
          "fails", fails or "none", flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
