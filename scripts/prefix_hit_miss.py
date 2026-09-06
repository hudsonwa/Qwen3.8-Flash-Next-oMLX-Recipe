#!/usr/bin/env python3
"""L2 / issue #41: frozen prefix miss vs hit. Serving. MTP off.

Same real prompt for a miss/hit pair. Salt [variant <tag>] on the TAIL only.
Prefix bytes identical within a pair. N>=3 pairs. Warmup dropped.
"""
from __future__ import annotations

import hashlib
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
OUT = ROOT / "results" / "prefix_hit_miss.json"

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
        return {"current": None, "peak": None, "peak_gb": None}
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
    return {"current": cur, "peak": peak, "current_gb": parse_gb(cur), "peak_gb": parse_gb(peak)}


def frozen_prompt(approx_tokens: int, tail_salt: str) -> tuple[str, str, str]:
    reps = max(1, approx_tokens // 65)
    prefix = "Read carefully. Reply with exactly: DONE\n\nFrozen-prefix-block.\n" + UNIT * reps
    tail = f"\n[variant {tail_salt}]"
    return prefix, tail, prefix + tail


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
    model = resolve()
    stamp = machine_stamp()
    n_count = 3
    fails = []
    wu = stream(model, "Reply with the single word: READY\n[variant warmup-l2]", 8)
    print("[l2] warmup dropped", wu.get("wall_s"), flush=True)

    salt = time.strftime("%H%M%S") + "-frozen"
    prefix, tail, prompt = frozen_prompt(252000, salt)
    prefix_sha = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    if prefix + tail != prompt:
        fails.append("prefix+tail != prompt")

    miss = stream(model, prompt, 8)
    miss["label"] = "miss"
    fp = footprint()
    peak_seen = fp.get("peak_gb") or 0.0
    print("[l2] miss", miss.get("wall_s"), "cached", miss.get("cached_tokens"),
          "pt", miss.get("prompt_tokens"), "peak", peak_seen, flush=True)
    if miss.get("error"):
        fails.append("miss error %s" % miss["error"])
    if (miss.get("cached_tokens") or 0) != 0:
        fails.append("miss cached_tokens %s != 0" % miss.get("cached_tokens"))
    mw = miss.get("wall_s") or 0
    if mw < 150:
        fails.append("miss wall %s not ~229s class" % mw)

    hits = []
    for i in range(n_count):
        hit = stream(model, prompt, 8)
        hit["label"] = "hit"
        fp = footprint()
        pg = fp.get("peak_gb") or 0
        peak_seen = max(peak_seen, pg)
        hw = hit.get("wall_s") or 0
        if hit.get("error"):
            fails.append("hit %s error" % i)
        if (hit.get("cached_tokens") or 0) <= 0:
            fails.append("hit %s cached_tokens %s" % (i, hit.get("cached_tokens")))
        if hw > 40 or hw < 1:
            fails.append("hit %s wall %s not ~8.7s class" % (i, hw))
        if pg > SOFT_GB:
            fails.append("hit %s peak_gb %s > 96.8" % (i, pg))
        if pg > PLAN_GB:
            fails.append("hit %s peak_gb %s > 102" % (i, pg))
        hits.append({"i": i, "hit": hit, "footprint": fp})
        print("[l2] hit", i, hw, "cached", hit.get("cached_tokens"), "peak", pg, flush=True)

    # tail-salt only: same prefix bytes, different tail — still hit-class
    prefix2, tail2, prompt2 = frozen_prompt(252000, salt + "-tail2")
    sha2 = hashlib.sha256(prefix2.encode("utf-8")).hexdigest()
    if sha2 != prefix_sha:
        fails.append("tail-only salt changed prefix bytes")
    tail_probe = stream(model, prompt2, 8)
    print("[l2] tail-salt probe", tail_probe.get("wall_s"), "cached",
          tail_probe.get("cached_tokens"), flush=True)
    if (tail_probe.get("wall_s") or 0) > 40:
        fails.append("tail-salt probe wall %s not hit-class (prefix should still cache)" %
                     tail_probe.get("wall_s"))

    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": [miss.get("prompt_tokens")] + [h["hit"].get("prompt_tokens") for h in hits],
        "ttft_s": [miss.get("ttft_s")] + [h["hit"].get("ttft_s") for h in hits],
        "wall_s": [miss.get("wall_s")] + [h["hit"].get("wall_s") for h in hits],
        "cached_tokens": [miss.get("cached_tokens")] + [h["hit"].get("cached_tokens") for h in hits],
        "n": n_count,
        "miss": miss,
        "hits": hits,
        "tail_salt_probe": tail_probe,
        "prefix_sha256": prefix_sha,
        "salt_on": "tail",
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
