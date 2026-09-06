#!/usr/bin/env python3
"""L7 / issue #46: client-side latency percentiles. Serving. Thinking off."""
from __future__ import annotations

import json
import os
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_stamp import hf_revision, machine_stamp  # noqa: E402
from resolve_model import resolve  # noqa: E402
import subprocess

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8000")
OUT = ROOT / "results" / "latency_percentiles.json"
SOFT_GB = 96.8


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


def footprint_peak():
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not out:
        return None
    res = subprocess.run(["/usr/bin/footprint", out.split()[0]],
                         capture_output=True, text=True, timeout=60).stdout
    for line in res.splitlines():
        if "phys_footprint_peak" in line:
            return parse_gb(line.split()[1])
    return None


def pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def stream(model, prompt, max_tokens=32):
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
    queued = t0
    first = None
    token_t = []
    usage = {}
    err = None
    ntok = 0
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            for raw in r:
                now = time.perf_counter()
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
                    ntok += 1
                    token_t.append(now - t0)
                    if first is None:
                        first = now - t0
    except Exception as e:
        err = str(e)[:200]
    wall = time.perf_counter() - t0
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    itls = []
    for i in range(1, len(token_t)):
        itls.append(token_t[i] - token_t[i - 1])
    ttft = first
    pt = int(usage.get("prompt_tokens") or 0)
    return {
        "ttft_s": round(ttft, 4) if ttft is not None else None,
        "wall_s": round(wall, 4),
        "prompt_tokens": pt,
        "cached_tokens": int(cached) if cached is not None else None,
        "itl_s": [round(x, 4) for x in itls],
        "prefill_tok_s": round(pt / ttft, 2) if ttft else None,
        "error": err,
        "queue_s": round(ttft, 4) if ttft is not None else None,
    }


def main():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    stamp = machine_stamp()
    fails = []
    wu = stream(model, "Reply READY only.\n[variant warmup-l7]", 8)
    print("[l7] warmup dropped", wu.get("wall_s"), flush=True)

    # concurrent shorts = queue sample
    n_q = 8
    box = {}

    def job(i):
        box[i] = stream(model, "Count from 1 to 12, digits only.\n[variant q-%s]" % i, 32)

    threads = [threading.Thread(target=job, args=(i,)) for i in range(n_q)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    qwall = time.perf_counter() - t0
    qrows = [box[i] for i in range(n_q)]
    print("[l7] queue batch wall", round(qwall, 3), flush=True)

    # miss then hit of a medium prompt (n=3 pairs)
    med = "Write a 40-word paragraph about prefix caches.\n" + ("alpha bravo charlie. " * 80)
    miss_rows, hit_rows = [], []
    for i in range(3):
        prompt = med + "\n[variant med-%s]" % i
        miss = stream(model, prompt, 32)
        miss["label"] = "miss"
        hit = stream(model, prompt, 32)
        hit["label"] = "hit"
        miss_rows.append(miss)
        hit_rows.append(hit)
        print("[l7] med", i, "miss", miss.get("ttft_s"), "hit", hit.get("ttft_s"),
              "cached", miss.get("cached_tokens"), hit.get("cached_tokens"), flush=True)

    itls = []
    ttfts = []
    walls = []
    pts = []
    cached = []
    for r in qrows + miss_rows + hit_rows:
        if r.get("error"):
            fails.append("stream error")
        itls.extend(r.get("itl_s") or [])
        if r.get("ttft_s") is not None:
            ttfts.append(r["ttft_s"])
        if r.get("wall_s") is not None:
            walls.append(r["wall_s"])
        pts.append(r.get("prompt_tokens"))
        cached.append(r.get("cached_tokens"))

    peak = footprint_peak()
    if peak and peak > SOFT_GB:
        fails.append("peak_gb %s > 96.8" % peak)

    def pack(xs):
        xs = [x for x in xs if x is not None]
        if not xs:
            return None
        return {"p50": round(pct(xs, 50), 4), "p95": round(pct(xs, 95), 4),
                "p99": round(pct(xs, 99), 4), "n": len(xs)}

    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak,
        "prompt_tokens": pts,
        "ttft_s": ttfts,
        "wall_s": walls,
        "cached_tokens": cached,
        "n": 3,
        "percentiles": {
            "queue_or_ttft": pack([r.get("queue_s") for r in qrows]),
            "ttft": pack(ttfts),
            "prefill_tok_s": pack([r.get("prefill_tok_s") for r in miss_rows]),
            "itl_s": pack(itls),
            "wall_s": pack(walls),
            "miss_ttft_s": pack([r.get("ttft_s") for r in miss_rows]),
            "hit_ttft_s": pack([r.get("ttft_s") for r in hit_rows]),
        },
        "queue_batch": qrows,
        "miss": miss_rows,
        "hit": hit_rows,
        "profile": "serving",
        "warmup_dropped": True,
        "fails": fails,
        "pass": not fails,
    }
    OUT.write_text(json.dumps(receipt, indent=1) + "\n")
    print("WROTE", OUT, receipt["percentiles"], "pass", receipt["pass"], flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
