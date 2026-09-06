#!/usr/bin/env python3
"""Fail-closed quality canary. Not a full eval harness.

Three frozen checks: needle in a ~240k prefix, JSON-only, short code emit.
Exit 2 if the API is down. Exit 1 on any miss. Writes results/quality_canary.json.

This is a serving-stack canary (needle / JSON parse / short emit). It is not
MMLU, GPQA, or any benchmark suite.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_stamp import hf_revision, machine_stamp  # noqa: E402
from resolve_model import resolve  # noqa: E402

NEEDLE = "CANARY-NEEDLE-240K"
TARGET_PROMPT_TOKENS = 240000
UNIT_PATH = ROOT / "prompts" / "canary_needle_seed.txt"
JSON_PATH = ROOT / "prompts" / "canary_json.txt"
CODE_PATH = ROOT / "prompts" / "canary_code.txt"


def chat(base: str, model: str, content: str, max_tokens: int, timeout: int) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
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
    text = []
    err = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
    return {
        "ttft_s": round(first, 3) if first is not None else None,
        "wall_s": round(wall, 2),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        "completion": "".join(text).strip(),
        "error": err,
    }


def build_240k(needle: str, salt: str) -> str:
    unit = UNIT_PATH.read_text(encoding="utf-8").strip() + " "
    reps = max(1, TARGET_PROMPT_TOKENS // 65)
    return (
        "Read carefully. A token is hidden in this document.\n\n"
        + unit * reps
        + "\n[needle] Remember this token: %s\n" % needle
        + "\n[variant %s]\n" % salt
        + "After the document, output exactly the hidden token and nothing else.\n"
    )


def extract_json(text: str):
    if "{" not in text:
        raise ValueError("no JSON object")
    return json.loads(text[text.find("{"): text.rfind("}") + 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--out", default=str(ROOT / "results" / "quality_canary.json"))
    ap.add_argument("--prefix-file", help="Use this 240k prompt instead of generating one")
    ap.add_argument("--needle", default=NEEDLE)
    ap.add_argument("--skip-240k", action="store_true")
    args = ap.parse_args()
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    os.environ["OMLX_BASE"] = args.base
    try:
        model = resolve()
    except SystemExit as e:
        print("API down:", e, file=sys.stderr)
        return 2

    salt = time.strftime("%H%M%S")
    fails = []
    checks = {}
    prompt_tokens = []

    def record(name, rec, ok, detail=""):
        rec = dict(rec)
        rec["ok"] = bool(ok)
        rec["detail"] = detail[:200]
        checks[name] = rec
        print(("PASS" if ok else "FAIL"), name, detail[:80], flush=True)
        if not ok:
            fails.append(name)

    if not args.skip_240k:
        if args.prefix_file:
            prefix = Path(args.prefix_file).read_text(encoding="utf-8")
        else:
            prefix = build_240k(args.needle, salt)
        rec = chat(args.base, model, prefix, 32, timeout=7200)
        prompt_tokens.append(rec.get("prompt_tokens") or 0)
        got = (rec.get("completion") or "").replace(" ", "")
        ok = (not rec.get("error")) and args.needle.replace(" ", "") in got
        if rec.get("prompt_tokens") and rec["prompt_tokens"] < 200000:
            ok = False
            rec["error"] = (rec.get("error") or "") + " prompt_tokens %s < 200000" % rec["prompt_tokens"]
        record("needle-240k", rec, ok, rec.get("completion") or rec.get("error") or "")

    rec = chat(args.base, model, JSON_PATH.read_text(encoding="utf-8"), 64, timeout=120)
    prompt_tokens.append(rec.get("prompt_tokens") or 0)
    js_ok = False
    parsed = None
    try:
        parsed = extract_json(rec.get("completion") or "")
        js_ok = parsed.get("canary") is True and parsed.get("n") == 1
    except Exception as e:
        rec["parse_error"] = str(e)[:80]
    record("json-only", rec, (not rec.get("error")) and js_ok, rec.get("completion") or "")

    rec = chat(args.base, model, CODE_PATH.read_text(encoding="utf-8"), 64, timeout=120)
    prompt_tokens.append(rec.get("prompt_tokens") or 0)
    text = rec.get("completion") or ""
    code_ok = "def ping" in text and "42" in text
    record("short-code-emit", rec, (not rec.get("error")) and code_ok, text)

    import re
    ms = machine_stamp()
    raw = str(ms.get("omlx") or "")
    m = re.search(r"\d+\.\d+\.\d+", raw)
    out = {
        "recipe": "quality canary — not a full eval harness",
        "not_a_full_eval_harness": True,
        "machine": ms,
        "omlx": m.group(0) if m else raw or None,
        "hf_revision": hf_revision(),
        "n": 1,
        "profile": "daily-hot-0",
        "hot_cache_max_size": "0",
        "temperature": 0,
        "thinking": False,
        "needle": args.needle,
        "prompt_tokens": prompt_tokens,
        "checks": checks,
        "fails": fails,
        "pass": not fails,
    }
    path = Path(args.out)
    protect = {
        "warm_8slot_results.json",
        "hot_cache_one_brain.json",
        "hot_cache_current.json",
        "hot_cache_one_brain_pr48.json",
    }
    if path.name in protect:
        print("refuse: would overwrite protected receipt", path, file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print("wrote", path, "pass", out["pass"], "fails", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
