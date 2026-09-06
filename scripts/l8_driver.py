#!/usr/bin/env python3
"""L8 / issue #47: A/B last. SHORT jobs for chunked/concurrency. Restore serving."""
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
CONF = Path(os.environ.get("OMLX_HOME") or Path.home() / ".omlx")
AB_OUT = ROOT / "results" / "ab_sweep.json"
MTP_OUT = ROOT / "results" / "mtp_on_off.json"


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


def patch_settings(pairs: dict):
    p = CONF / "settings.json"
    d = json.loads(p.read_text())
    for path, val in pairs.items():
        cur = d
        keys = path.split(".")
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = val
        print("patch", path, "->", val, flush=True)
    p.write_text(json.dumps(d, indent=2) + "\n")


def apply_mode(mode: str):
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "omlx-config.py"),
         "--mode", mode, "--apply"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise SystemExit("FAIL omlx-config %s" % mode)


def snapshot_settings():
    d = json.loads((CONF / "settings.json").read_text())
    sch = d.get("scheduler") or {}
    srv = d.get("server") or {}
    return {
        "chunked_prefill": sch.get("chunked_prefill"),
        "max_concurrent_requests": sch.get("max_concurrent_requests"),
        "burst_decode_mode": srv.get("burst_decode_mode"),
    }


def main():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    fails = []
    stamp = machine_stamp()
    arms = []
    peak_seen = 0.0

    def measure_arm(label, n_jobs, n=3):
        nonlocal peak_seen
        os.environ["OMLX_REQUIRE_LIVE"] = "1"
        model = resolve()
        rows = []
        for i in range(n):
            wall, recs = batch(model, n_jobs, "%s-%s" % (label, i))
            pg = footprint_peak() or 0
            peak_seen = max(peak_seen, pg)
            if pg > SOFT_GB:
                fails.append("%s peak %s > 96.8" % (label, pg))
            if any(r.get("error") for r in recs):
                fails.append("%s stream error" % label)
            rows.append({"batch_wall_s": round(wall, 4), "jobs": recs, "peak_gb": pg})
            print("[l8]", label, "i", i, "batch_wall", round(wall, 3), "peak", pg, flush=True)
        snap = snapshot_settings()
        return {
            "label": label,
            "n_jobs": n_jobs,
            "settings": snap,
            "rows": rows,
            "prompt_tokens": [j["prompt_tokens"] for r in rows for j in r["jobs"]],
            "ttft_s": [j["ttft_s"] for r in rows for j in r["jobs"]],
            "wall_s": [j["wall_s"] for r in rows for j in r["jobs"]],
            "cached_tokens": [j["cached_tokens"] for r in rows for j in r["jobs"]],
        }

    # 1. serving mc=8 chunked on (live)
    arms.append(measure_arm("mc8_chunked_on", 8))
    mtp_off = measure_arm("mtp_off_load8", 8)

    # 2. mc=4 short
    patch_settings({"scheduler.max_concurrent_requests": 4})
    restart()
    arms.append(measure_arm("mc4_chunked_on", 4))

    # 3. chunked off, mc=8, SHORT only
    patch_settings({
        "scheduler.max_concurrent_requests": 8,
        "scheduler.chunked_prefill": False,
    })
    restart()
    arms.append(measure_arm("mc8_chunked_off", 8))

    # restore serving scheduler before MTP
    apply_mode("serving")
    restart()

    # 4. MTP on under load
    apply_mode("interactive")
    restart()
    va = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
         "--expect", "interactive"],
        cwd=str(ROOT),
    )
    mtp_on = None
    if va.returncode != 0:
        fails.append("verify_activation interactive failed")
        print("FAIL interactive activation — skipping MTP-on numbers", flush=True)
    else:
        mtp_on = measure_arm("mtp_on_load8", 8)
        pg = footprint_peak() or 0
        if pg > PLAN_GB:
            fails.append("MTP-on peak_gb %s > 102" % pg)

    # 5. always restore serving
    apply_mode("serving")
    restart()
    vs = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
         "--expect", "serving"],
        cwd=str(ROOT),
    )
    if vs.returncode != 0:
        fails.append("failed to restore serving mtp_enabled false")
    vsh = subprocess.run(["bash", str(ROOT / "scripts" / "verify.sh")], cwd=str(ROOT))
    if vsh.returncode != 0:
        fails.append("verify.sh failed after restore")

    def flatten(arm_list):
        pt, tt, wa, ca = [], [], [], []
        for a in arm_list:
            pt += a["prompt_tokens"]
            tt += a["ttft_s"]
            wa += a["wall_s"]
            ca += a["cached_tokens"]
        return pt, tt, wa, ca

    pt, tt, wa, ca = flatten(arms)
    ab = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": pt,
        "ttft_s": tt,
        "wall_s": wa,
        "cached_tokens": ca,
        "n": 3,
        "burst_decode_mode": snapshot_settings().get("burst_decode_mode"),
        "arms": arms,
        "profile_restored": "serving",
        "fails": fails,
        "pass": not fails,
    }
    AB_OUT.write_text(json.dumps(ab, indent=1) + "\n")

    mtp = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": (mtp_off["prompt_tokens"] if mtp_off else []) + (mtp_on["prompt_tokens"] if mtp_on else []),
        "ttft_s": (mtp_off["ttft_s"] if mtp_off else []) + (mtp_on["ttft_s"] if mtp_on else []),
        "wall_s": (mtp_off["wall_s"] if mtp_off else []) + (mtp_on["wall_s"] if mtp_on else []),
        "cached_tokens": (mtp_off["cached_tokens"] if mtp_off else []) + (mtp_on["cached_tokens"] if mtp_on else []),
        "n": 3,
        "mtp_off": mtp_off,
        "mtp_on": mtp_on,
        "fails": fails,
        "pass": not fails and mtp_on is not None,
    }
    MTP_OUT.write_text(json.dumps(mtp, indent=1) + "\n")
    print("WROTE", AB_OUT, MTP_OUT, "fails", fails or "none", flush=True)
    return 0 if ab["pass"] and mtp["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
