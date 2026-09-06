#!/usr/bin/env python3
"""L8 MTP arm only. Restore serving. Does not redo the short A/B sweep."""
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

BASE = "http://127.0.0.1:8000"
SOFT_GB = 96.8
PLAN_GB = 102.0
OUT = ROOT / "results" / "mtp_on_off.json"


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


def stream(model, prompt, max_tokens=16):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(BASE + "/v1/chat/completions",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    usage = {}
    err = None
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
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
                if delta and first is None:
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
        "error": err,
    }


def batch(model, n_jobs, salt):
    box = {}

    def job(i):
        box[i] = stream(model, "Reply READY only. Digit %s.\n[variant %s-%s]" % (i, salt, i), 8)

    ts = [threading.Thread(target=job, args=(i,)) for i in range(n_jobs)]
    t0 = time.perf_counter()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return time.perf_counter() - t0, [box[i] for i in range(n_jobs)]


def wait_up(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(BASE + "/v1/models", timeout=2).read()
            pid = subprocess.run(
                ["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
                capture_output=True, text=True,
            ).stdout.strip().split()
            if not pid:
                time.sleep(2)
                continue
            fp = subprocess.run(["/usr/bin/footprint", pid[0]],
                                capture_output=True, text=True, timeout=60).stdout
            gb = None
            for line in fp.splitlines():
                if "phys_footprint:" in line and "peak" not in line:
                    gb = parse_gb(line.split()[1])
            if gb is not None and gb >= 60:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def restart():
    subprocess.run("kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)", shell=True)
    time.sleep(2)
    if not wait_up():
        raise SystemExit("FAIL: server did not return after restart")


def apply_mode(mode: str):
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "omlx-config.py"),
         "--mode", mode, "--apply"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise SystemExit("FAIL omlx-config %s" % mode)


def measure_arm(label, n_jobs, n=3):
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    rows = []
    peak_seen = 0.0
    fails = []
    for i in range(n):
        wall, recs = batch(model, n_jobs, "%s-%s" % (label, i))
        pg = footprint_peak() or 0
        peak_seen = max(peak_seen, pg)
        if pg > SOFT_GB:
            fails.append("%s peak %s > 96.8" % (label, pg))
        if any(r.get("error") for r in recs):
            fails.append("%s stream error" % label)
        rows.append({"batch_wall_s": round(wall, 4), "jobs": recs, "peak_gb": pg})
        print("[mtp]", label, i, "batch_wall", round(wall, 3), "peak", pg, flush=True)
    return {
        "label": label,
        "n_jobs": n_jobs,
        "peak_gb": peak_seen,
        "rows": rows,
        "prompt_tokens": [j["prompt_tokens"] for r in rows for j in r["jobs"]],
        "ttft_s": [j["ttft_s"] for r in rows for j in r["jobs"]],
        "wall_s": [j["wall_s"] for r in rows for j in r["jobs"]],
        "cached_tokens": [j["cached_tokens"] for r in rows for j in r["jobs"]],
        "fails": fails,
    }


def main():
    fails = []
    stamp = machine_stamp()
    os.environ["OMLX_REQUIRE_LIVE"] = "1"

    off = measure_arm("mtp_off_load8", 8)

    apply_mode("interactive")
    restart()
    va = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
         "--expect", "interactive"],
        cwd=str(ROOT),
    )
    on = None
    if va.returncode != 0:
        fails.append("verify_activation interactive failed")
        print("FAIL interactive", flush=True)
    else:
        on = measure_arm("mtp_on_load8", 8)
        fails.extend(on.get("fails") or [])
        pg = footprint_peak() or 0
        if pg > PLAN_GB:
            fails.append("MTP-on peak_gb %s > 102" % pg)

    apply_mode("serving")
    restart()
    vs = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
         "--expect", "serving"],
        cwd=str(ROOT),
    )
    if vs.returncode != 0:
        fails.append("failed to restore serving")
    vsh = subprocess.run(["bash", str(ROOT / "scripts" / "verify.sh")], cwd=str(ROOT))
    if vsh.returncode != 0:
        fails.append("verify.sh failed after restore")

    peak = max(off.get("peak_gb") or 0, (on or {}).get("peak_gb") or 0)
    receipt = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak,
        "prompt_tokens": off["prompt_tokens"] + ((on or {}).get("prompt_tokens") or []),
        "ttft_s": off["ttft_s"] + ((on or {}).get("ttft_s") or []),
        "wall_s": off["wall_s"] + ((on or {}).get("wall_s") or []),
        "cached_tokens": off["cached_tokens"] + ((on or {}).get("cached_tokens") or []),
        "n": 3,
        "mtp_off": off,
        "mtp_on": on,
        "fails": fails + (off.get("fails") or []),
        "pass": not fails and on is not None,
    }
    OUT.write_text(json.dumps(receipt, indent=1) + "\n")
    print("WROTE", OUT, "pass", receipt["pass"], "fails", receipt["fails"] or "none", flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
