#!/usr/bin/env python3
"""L5 / issue #44: two lanes — short path not queued behind a ~240k fill."""
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
OUT = ROOT / "results" / "two_lane_latency.json"
UNIT = (
    "Linear attention layers process the sequence with constant memory per step, while full "
    "attention layers attend to all previous tokens every fourth layer. Multi-token prediction "
    "heads draft several tokens per verification cycle, and an adaptive controller adjusts draft "
    "depth from rolling acceptance statistics. Prefix caching stores previously computed states "
    "so repeated system prompts skip recomputation. "
)


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


def historical_dual_solo():
    """Cite 08-31 JSON. Do not re-run dual-head."""
    g0 = json.loads((ROOT / "results" / "omlx_flash_2way_results.json").read_text())
    w1 = json.loads((ROOT / "results" / "warm_8slot_results.json").read_text())
    solo = g0["phases"]["G0_solo_252k_fill"]["streams"]["solo"]["wall_s"]
    dual = w1["phases"]["W1_2x252k_boot_warm"]["streams"]["orch-A"]["wall_s"]
    ratio = dual / solo
    over = dual / (2 * solo) - 1
    return {
        "solo_wall_s": solo,
        "dual_wall_s": dual,
        "dual_over_solo": round(ratio, 3),
        "pct_over_2x_solo": round(over * 100, 1),
        "source": ["results/omlx_flash_2way_results.json G0", "results/warm_8slot_results.json W1 orch-A"],
    }


def main():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    stamp = machine_stamp()
    fails = []
    hist = historical_dual_solo()
    # 2.11x and ~6% over 2xsolo — allow small slack on the cited historical pair
    if abs(hist["dual_over_solo"] - 2.11) > 0.05:
        fails.append("historical dual/solo %s not 2.11x" % hist["dual_over_solo"])
    if abs(hist["pct_over_2x_solo"] - 6) > 2:
        fails.append("historical %% over 2xsolo %s not ~6" % hist["pct_over_2x_solo"])

    wu = stream(model, "Reply with the single word: READY\n[variant warmup-l5]", 8)
    print("[l5] warmup dropped", wu.get("wall_s"), "hist", hist, flush=True)

    n_count = 3
    rows = []
    peak_seen = 0.0
    for i in range(n_count):
        salt = time.strftime("%H%M%S") + f"-{i}"
        box = {}

        def long_job():
            box["long"] = stream(model, mk_prompt(252000, salt), 8)

        def short_job():
            time.sleep(5)
            box["short"] = stream(model, f"Planner tick {salt}: reply READY only.\n[variant tick-{salt}]", 16)

        t1 = threading.Thread(target=long_job)
        t2 = threading.Thread(target=short_job)
        t1.start(); t2.start()
        t1.join(); t2.join()
        fp = footprint()
        pg = fp.get("peak_gb") or 0
        peak_seen = max(peak_seen, pg)
        lng, sh = box.get("long") or {}, box.get("short") or {}
        if sh.get("error") or lng.get("error"):
            fails.append("row %s stream error" % i)
        if (lng.get("cached_tokens") or 0) != 0:
            fails.append("row %s long cached %s" % (i, lng.get("cached_tokens")))
        sw = sh.get("wall_s") or 999
        lw = lng.get("wall_s") or 0
        if sw >= 0.5 * lw:
            fails.append("row %s short wall %s queued behind long %s" % (i, sw, lw))
        if sw > 40:
            fails.append("row %s short wall %s > 40s" % (i, sw))
        if pg > SOFT_GB:
            fails.append("row %s peak %s > 96.8" % (i, pg))
        rows.append({"i": i, "long": lng, "short": sh, "footprint": fp})
        print("[l5] row", i, "long", lw, "short", sw, "peak", pg, flush=True)

    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": [r["long"].get("prompt_tokens") for r in rows],
        "ttft_s": [r["long"].get("ttft_s") for r in rows],
        "wall_s": [r["long"].get("wall_s") for r in rows],
        "cached_tokens": [r["long"].get("cached_tokens") for r in rows],
        "n": n_count,
        "short_wall_s": [r["short"].get("wall_s") for r in rows],
        "historical_dual_solo": hist,
        "rows": rows,
        "profile": "serving",
        "warmup_dropped": True,
        "fails": fails,
        "pass": not fails,
    }
    OUT.write_text(json.dumps(receipt, indent=1) + "\n")
    print("WROTE", OUT, "pass", receipt["pass"], "fails", fails or "none", flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
