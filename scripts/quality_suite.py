#!/usr/bin/env python3
"""Tiny quality suite (issue #35). Live API. Exit 2 if down. Exit 1 on fails.

Not a 240k proof. MTP/quant changes can alter wording — treat fails as
signals, not as a license to claim the 8-slot shape is broken.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

os.environ.setdefault("OMLX_REQUIRE_LIVE", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve_model import resolve  # noqa: E402

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8000/v1")


def chat(model: str, content: str, max_tokens: int = 64) -> str:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(BASE.rstrip("/") + "/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.load(r)
    return (d["choices"][0]["message"]["content"] or "").strip()


def main() -> int:
    try:
        model = resolve()
    except SystemExit:
        print("API down", file=sys.stderr)
        return 2
    fails = []

    def check(name, ok, detail=""):
        print(("PASS" if ok else "FAIL"), name, detail[:80])
        if not ok:
            fails.append(name)

    needle = "NEEDLE-Q1"
    t = chat(model, "Reply with exactly this token and nothing else: %s" % needle, 16)
    check("exact-needle", needle in t.replace(" ", ""), t)

    t = chat(model, "Reply with exactly OK", 8)
    check("refuse-empty", len(t) > 0, t)

    t = chat(model, 'Return only JSON: {"ok": true}', 32)
    try:
        json.loads(t[t.find("{"): t.rfind("}") + 1] if "{" in t else t)
        js_ok = True
    except Exception:
        js_ok = False
    check("json-object", js_ok, t)

    t = chat(model, "Write a Python one-liner: print(2+2) only.", 32)
    check("code-parse", "print" in t and "2" in t, t)

    t = chat(model, "Output the integer 7 as a digit only.", 8)
    check("digit-7", "7" in t, t)

    t = chat(model, "Say the word READY in uppercase, nothing else.", 8)
    check("ready", "READY" in t.upper(), t)

    t = chat(model, "Repeat: ping", 8)
    check("repeat-ping", "ping" in t.lower(), t)

    t = chat(model, "How many letters in the English word 'cat'? Digit only.", 8)
    check("count-cat", "3" in t, t)

    t = chat(model, "Complete: HTTP status for OK is", 8)
    check("http-200", "200" in t, t)

    t = chat(model, "Return a JSON array with one string 'a'.", 32)
    check("json-array", "[" in t, t)

    t = chat(model, "Do not apologize. Answer: 1+1=", 8)
    check("no-empty-math", any(ch.isdigit() for ch in t), t)

    t = chat(model, "Write `def f():\\n    return 1` in a python fence.", 64)
    check("def-f", "def" in t, t)

    print("fails", fails or "none")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
