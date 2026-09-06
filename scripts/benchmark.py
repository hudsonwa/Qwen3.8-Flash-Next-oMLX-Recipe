#!/usr/bin/env python3
"""Decode-table protocol (issue #33).

Prefill tok/s  := prompt_tokens / TTFT_s
  (TTFT = time to first streamed token). Stated here so it is not mixed
  with generation.

Generation tok/s := (completion_tokens - 1) / (wall_s - TTFT_s)
  after the first token. Warmup discarded. N>=3. Unique salt so prefix
  cache hits are forced to 0.

Always pass --label baseline or --label recipe. compare.py refuses a
lone series. Does not toggle MTP or rewrite ~/.omlx.

--mode solo (default) and --mode short8 are separate series. Do not
average them. Do not headline 8-token dummy completions.

Exit 2 if the API is down.
"""
from __future__ import annotations

import argparse
import json
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

PROMPTS = ("code", "prose", "counting")


def stream(base: str, model: str, prompt: str, max_tokens: int) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    usage = {}
    n_chunks = 0
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
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
                    n_chunks += 1
                    if first is None:
                        first = time.perf_counter() - t0
    except Exception as e:
        return {"error": str(e)[:200]}
    wall = time.perf_counter() - t0
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    ttft = first
    prefill = (pt / ttft) if ttft and ttft > 0 else None
    remain = (wall - ttft) if ttft is not None else None
    gen = ((ct - 1) / remain) if remain and remain > 0 and ct > 1 else None
    return {
        "ttft_s": round(ttft, 4) if ttft is not None else None,
        "wall_s": round(wall, 4),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "prefill_tok_s": round(prefill, 2) if prefill else None,
        "generation_tok_s": round(gen, 2) if gen else None,
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "error": None,
    }


def load_prompt(name: str, salt: str) -> str:
    text = (ROOT / "prompts" / (name + ".txt")).read_text()
    return text.rstrip() + "\n\n[variant %s]\n" % salt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--label", required=True, choices=["baseline", "recipe"])
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--mode", choices=["solo", "short8"], default="solo")
    ap.add_argument("--out", default=str(ROOT / "results" / "decode_table.json"))
    args = ap.parse_args()
    if args.max_tokens < 32:
        print("refuse: --max-tokens < 32 is an 8-token dummy, not a decode table",
              file=sys.stderr)
        return 2
    os_env = __import__("os").environ
    os_env["OMLX_REQUIRE_LIVE"] = "1"
    os_env["OMLX_BASE"] = args.base
    try:
        model = resolve()
    except SystemExit as e:
        print("API down:", e, file=sys.stderr)
        return 2
    salt = time.strftime("%H%M%S")
    series = {"label": args.label, "model": model, "salt": salt,
              "max_tokens": args.max_tokens, "n": args.n, "mode": args.mode,
              "thinking": False, "temperature": 0, "prompts": {}}
    if args.mode == "short8":
        name = "counting"
        recs = []
        for i in range(args.warmup + args.n):
            batch = [None] * 8

            def fire(idx, i=i, batch=batch):
                prompt = load_prompt(name, "%s-%s-%d-%d" % (salt, name, i, idx))
                batch[idx] = stream(args.base, model, prompt, args.max_tokens)

            t0 = time.perf_counter()
            th = [threading.Thread(target=fire, args=(k,)) for k in range(8)]
            for t in th:
                t.start()
            for t in th:
                t.join()
            rec = {
                "warmup": i < args.warmup,
                "batch_wall_s": round(time.perf_counter() - t0, 4),
                "jobs": batch,
            }
            recs.append(rec)
            gens = [j.get("generation_tok_s") for j in batch if j and j.get("generation_tok_s")]
            print("[%s short8 i=%d] batch_wall=%s gen_mean=%s" % (
                args.label, i, rec["batch_wall_s"],
                round(statistics.mean(gens), 2) if gens else None), flush=True)
        kept = [r for r in recs if not r.get("warmup")]
        series["prompts"][name] = {"runs": recs, "n_kept": len(kept), "concurrency": 8}
    else:
        for name in PROMPTS:
            recs = []
            for i in range(args.warmup + args.n):
                prompt = load_prompt(name, "%s-%s-%d" % (salt, name, i))
                rec = stream(args.base, model, prompt, args.max_tokens)
                rec["warmup"] = i < args.warmup
                recs.append(rec)
                print("[%s %s i=%d] gen=%s prefill=%s ttft=%s" % (
                    args.label, name, i, rec.get("generation_tok_s"),
                    rec.get("prefill_tok_s"), rec.get("ttft_s")), flush=True)
            kept = [r for r in recs if not r.get("warmup") and not r.get("error")]
            gens = [r["generation_tok_s"] for r in kept if r.get("generation_tok_s")]
            prefs = [r["prefill_tok_s"] for r in kept if r.get("prefill_tok_s")]
            series["prompts"][name] = {
                "runs": recs,
                "generation_tok_s_mean": round(statistics.mean(gens), 2) if gens else None,
                "prefill_tok_s_mean": round(statistics.mean(prefs), 2) if prefs else None,
            }
    out = Path(args.out)
    data = json.loads(out.read_text()) if out.exists() else {"recipe": "decode table", "runs": {}}
    data["runs"]["%s_%s" % (args.label, args.mode)] = series
    stamp_decode_receipt(data, n=args.n)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print("wrote", out, "key", "%s_%s" % (args.label, args.mode))
    return 0


def stamp_decode_receipt(data: dict, n: int) -> None:
    """Top-level SCHEMA keys. Both labels hit live daily serving (no config toggle)."""
    import re
    ms = machine_stamp()
    data["machine"] = ms
    raw = str(ms.get("omlx") or "")
    m = re.search(r"\d+\.\d+\.\d+", raw)
    data["omlx"] = m.group(0) if m else raw or None
    data["hf_revision"] = hf_revision()
    data["n"] = n
    data["profile"] = "daily-hot-0"
    data["hot_cache_max_size"] = "0"
    data["temperature"] = 0
    data["thinking"] = False
    data["metrics"] = {
        "prefill_tok_s": "prompt_tokens / TTFT_s (time to first streamed token)",
        "generation_tok_s": "(completion_tokens - 1) / (wall_s - TTFT_s)",
        "cache": "unique [variant salt] suffix; cached_tokens should be 0",
        "modes": "solo and short8 are separate series; do not average",
    }
    data["pairing_note"] = (
        "baseline_* and recipe_* are labels on the live daily serving stack "
        "(hot=0, max_concurrent_requests=8, MTP off). benchmark.py does not "
        "toggle ~/.omlx. Not a stock-scheduler vs recipe engine swap."
    )
    pts = []
    fails = []
    for key, series in (data.get("runs") or {}).items():
        if series.get("thinking") is not False:
            fails.append("%s thinking not off" % key)
        if series.get("temperature") != 0:
            fails.append("%s temperature != 0" % key)
        for name, rec in (series.get("prompts") or {}).items():
            for run in rec.get("runs") or []:
                if run.get("warmup"):
                    continue
                jobs = run.get("jobs")
                rows = jobs if isinstance(jobs, list) else [run]
                for j in rows:
                    if not j:
                        fails.append("%s/%s empty job" % (key, name))
                        continue
                    if j.get("error"):
                        fails.append("%s/%s %s" % (key, name, j["error"]))
                    pt = j.get("prompt_tokens")
                    if pt:
                        pts.append(int(pt))
                    cached = j.get("cached_tokens")
                    if cached:
                        fails.append("%s/%s cached_tokens=%s (cold row must be 0)" %
                                     (key, name, cached))
                    if not j.get("generation_tok_s"):
                        fails.append("%s/%s missing generation_tok_s" % (key, name))
                    if not j.get("prefill_tok_s"):
                        fails.append("%s/%s missing prefill_tok_s" % (key, name))
    data["prompt_tokens"] = pts
    data["fails"] = fails
    data["pass"] = not fails


if __name__ == "__main__":
    raise SystemExit(main())
