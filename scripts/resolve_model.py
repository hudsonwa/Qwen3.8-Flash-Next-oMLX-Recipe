#!/usr/bin/env python3
"""Print the served model id from GET /v1/models (one name for verify + warm).

Exact id only. Do not pick the first name containing 'flash'.
"""
import json, os, re, sys, urllib.request

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:%s" % os.environ.get("PORT", "8000"))
EXACT = os.environ.get("OMLX_MODEL", "qwen38-flash-next-oq4e-mtp")


def resolve(timeout=5):
    root = BASE.rstrip("/")
    url = root + "/models" if root.endswith("/v1") else root + "/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
        ids = [m.get("id") for m in data.get("data") or [] if m.get("id")]
    except Exception as e:
        if os.environ.get("OMLX_REQUIRE_LIVE") == "1":
            raise SystemExit("FAIL: could not resolve model id from %s: %s" % (url, e))
        return EXACT
    if not ids:
        if os.environ.get("OMLX_REQUIRE_LIVE") == "1":
            raise SystemExit("FAIL: /v1/models returned no ids")
        return EXACT
    glm = [i for i in ids if re.search(r"GLM-.*Flash", i, re.I)]
    if glm:
        raise SystemExit("FAIL: refuse GLM-*-Flash on this recipe: %s" % glm)
    if EXACT not in ids:
        if os.environ.get("OMLX_REQUIRE_LIVE") == "1":
            raise SystemExit("FAIL: exact model id %s not in /v1/models %s" % (EXACT, ids))
        return EXACT
    others = [i for i in ids if "flash" in i.lower() and i != EXACT]
    if others:
        raise SystemExit("FAIL: second flash id on /v1/models: %s (want only %s)" % (others, EXACT))
    return EXACT


if __name__ == "__main__":
    print(resolve())
