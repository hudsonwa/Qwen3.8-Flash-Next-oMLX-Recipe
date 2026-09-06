#!/usr/bin/env python3
"""L1 / issue #40: one 252K head + short slots. Serving profile. MTP off.

Writes results/single_head_latency.json. Does not overwrite warm_8slot_results.json.
N>=3 counted rows after one short warmup (dropped). temp 0, thinking off.
Cold rows require cached_tokens == 0. peak_gb > 96.8 fails. plan 102.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
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
OUT = ROOT / "results" / "single_head_latency.json"

UNIT = (
    "Linear attention layers process the sequence with constant memory per step, while full "
    "attention layers attend to all previous tokens every fourth layer. Multi-token prediction "
    "heads draft several tokens per verification cycle, and an adaptive controller adjusts draft "
    "depth from rolling acceptance statistics. Prefix caching stores previously computed states "
    "so repeated system prompts skip recomputation. "
)


def parse_gb(x) -> float | None:
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


def footprint() -> dict:
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return {"current": None, "peak": None, "peak_gb": None, "current_gb": None}
    pid = out.split()[0]
    res = subprocess.run(
        ["/usr/bin/footprint", pid], capture_output=True, text=True, timeout=60,
    ).stdout
    cur = peak = None
    for line in res.splitlines():
        if "phys_footprint_peak" in line:
            peak = line.split()[1]
        elif "phys_footprint:" in line:
            cur = line.split()[1]
    return {
        "current": cur,
        "peak": peak,
        "current_gb": parse_gb(cur),
        "peak_gb": parse_gb(peak),
        "pid": pid,
    }


def mk_prompt(approx_tokens: int, salt: str) -> str:
    reps = max(1, approx_tokens // 65)
    return (
        f"Read carefully. Reply with exactly: DONE-{salt}\n\n"
        + UNIT * reps
        + f"\n[variant {salt}]"
    )


def stream(model: str, prompt: str, max_tokens: int = 8) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(
        BASE.rstrip("/") + "/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    first = None
    usage: dict = {}
    text: list[str] = []
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
                delta = (ch.get("delta") or {}).get("content") or ch.get("message", {}).get("content")
                if delta:
                    text.append(delta)
                    if first is None:
                        first = time.perf_counter() - t0
    except Exception as e:
        err = str(e)[:200]
    wall = time.perf_counter() - t0
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    return {
        "ttft_s": round(first, 4) if first is not None else None,
        "wall_s": round(wall, 4),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cached_tokens": int(cached) if cached is not None else None,
        "completion": "".join(text).strip()[:200],
        "error": err,
    }


def main() -> int:
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    try:
        model = resolve()
    except Exception as e:
        print("FAIL: resolve model:", e, flush=True)
        return 2

    stamp = machine_stamp()
    rev = hf_revision()
    n_count = 3
    fails: list[str] = []

    # short warmup, dropped
    wu = stream(model, "Reply with the single word: READY\n[variant warmup]", 8)
    print("[l1] warmup dropped", wu.get("wall_s"), flush=True)

    rows = []
    peak_seen = 0.0
    for i in range(n_count):
        salt = time.strftime("%H%M%S") + f"-{i}"
        long_p = mk_prompt(252000, salt)
        short_p = f"Planner tick {salt}: reply READY only.\n[variant tick-{salt}]"
        box: dict = {}

        def long_job():
            box["head"] = stream(model, long_p, 8)

        def short_job(delay: float, key: str):
            time.sleep(delay)
            box[key] = stream(model, short_p, 16)

        t_long = threading.Thread(target=long_job)
        t_s1 = threading.Thread(target=short_job, args=(30.0, "short_1"))
        t_s2 = threading.Thread(target=short_job, args=(90.0, "short_2"))
        t_long.start()
        t_s1.start()
        t_s2.start()
        t_long.join()
        t_s1.join()
        t_s2.join()
        fp = footprint()
        pg = fp.get("peak_gb")
        if pg is not None:
            peak_seen = max(peak_seen, pg)
        head = box.get("head") or {}
        row = {
            "i": i,
            "salt": salt,
            "prompt_tokens": head.get("prompt_tokens"),
            "ttft_s": head.get("ttft_s"),
            "wall_s": head.get("wall_s"),
            "cached_tokens": head.get("cached_tokens"),
            "completion": head.get("completion"),
            "error": head.get("error"),
            "shorts": {k: box[k] for k in box if k != "head"},
            "footprint": fp,
        }
        if head.get("error"):
            fails.append("row %s error %s" % (i, head["error"]))
        if (head.get("cached_tokens") or 0) != 0:
            fails.append("row %s cached_tokens %s != 0 (cold required)" % (i, head.get("cached_tokens")))
        if not (head.get("completion") or "").startswith("DONE-"):
            fails.append("row %s completion %r" % (i, (head.get("completion") or "")[:80]))
        pt = head.get("prompt_tokens") or 0
        if not (230000 <= pt <= 250000):
            fails.append("row %s prompt_tokens %s not ~240k measured" % (i, pt))
        if pg is not None and pg > SOFT_GB:
            fails.append("row %s peak_gb %s > soft 96.8" % (i, pg))
        if pg is not None and pg > PLAN_GB:
            fails.append("row %s peak_gb %s > plan 102" % (i, pg))
        rows.append(row)
        print("[l1] row", i, "pt", pt, "wall", head.get("wall_s"), "peak", pg, flush=True)

    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": rev,
        "peak_gb": peak_seen,
        "prompt_tokens": [r["prompt_tokens"] for r in rows],
        "ttft_s": [r["ttft_s"] for r in rows],
        "wall_s": [r["wall_s"] for r in rows],
        "cached_tokens": [r["cached_tokens"] for r in rows],
        "n": n_count,
        "profile": "serving",
        "dual_head": False,
        "warmup_dropped": True,
        "soft_gb": SOFT_GB,
        "plan_gb": PLAN_GB,
        "rows": rows,
        "fails": fails,
        "pass": not fails,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, indent=1) + "\n")
    print("WROTE", OUT, "pass", receipt["pass"], "fails", fails or "none", flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
