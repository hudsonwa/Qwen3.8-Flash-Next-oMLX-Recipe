#!/usr/bin/env python3
"""Print the served model id from GET /v1/models (one name for verify + warm)."""
import json, os, sys, urllib.request

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:%s" % os.environ.get("PORT", "8000"))
FALLBACK = os.environ.get("OMLX_MODEL", "qwen38-flash-next-oq4e-mtp")


def resolve(timeout=5):
    url = BASE.rstrip("/") + "/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
        ids = [m.get("id") for m in data.get("data") or [] if m.get("id")]
    except Exception as e:
        if os.environ.get("OMLX_REQUIRE_LIVE") == "1":
            raise SystemExit("FAIL: could not resolve model id from %s: %s" % (url, e))
        return FALLBACK
    if not ids:
        if os.environ.get("OMLX_REQUIRE_LIVE") == "1":
            raise SystemExit("FAIL: /v1/models returned no ids")
        return FALLBACK
    for i in ids:
        if "flash" in i.lower():
            return i
    return ids[0]


if __name__ == "__main__":
    print(resolve())
