#!/usr/bin/env python3
"""L8 / #47: real 8 vs 4 on the live server.

LaunchAgent argv pins --max-concurrent-requests 8, so settings.json mc=4
never hits the process. This driver:

  1. Measures SHORT jobs on the current launchd server (argv mc=8).
  2. bootout com.omlx.flash8slot, starts `omlx serve --max-concurrent-requests 4`.
  3. Waits until phys_footprint current >= 60 GB (load, not first-batch-as-proof).
  4. Discards one warmup short, then N>=3 batches of 4 shorts.
  5. Always restores launchd bootstrap (daily serving mc=8, chunked, MTP off).

Stop by port only. Memory: /usr/bin/footprint only. Never iogpu.wired_limit_mb.
Public-safe JSON: no hostnames, no user paths.
"""
from __future__ import annotations

import json
import os
import re
import signal
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
PORT = 8000
LABEL = "com.omlx.flash8slot"
UID = os.getuid()
CONF = Path(os.environ.get("OMLX_HOME") or Path.home() / ".omlx")
OMLX = CONF / "bin" / "omlx"
MODEL_DIR = Path.home() / "models" / "omlx-qwen38"
CACHE_DIR = CONF / "ssd-cache"
PLIST = Path.home() / "Library" / "LaunchAgents" / "com.omlx.flash8slot.plist"
OUT = ROOT / "results" / "ab_8vs4_live.json"
SERVE_LOG = CONF / "logs" / "serve-mc4-l8.log"
N = 3


def parse_gb(x):
    """Parse a footprint quantity into GB. 7640 MB is 7.64, not 7640."""
    if x is None:
        return None
    s = str(x).strip().upper().replace(",", "")
    m = re.search(r"([0-9]*\.?[0-9]+)\s*([KMGTPE]I?B?)?", s)
    if not m:
        return None
    n = float(m.group(1))
    u = (m.group(2) or "GB").upper()
    if u in ("", "G", "GB", "GIB"):
        return n
    if u in ("M", "MB", "MIB"):
        return n / 1024.0
    if u in ("K", "KB", "KIB"):
        return n / (1024.0 ** 2)
    if u in ("T", "TB", "TIB"):
        return n * 1024.0
    if u in ("B",):
        return n / (1024.0 ** 3)
    return n


def listen_pid():
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:%s" % PORT, "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    return out.split()[0] if out else None


def footprint_pid(pid, peak=False):
    if not pid:
        return None
    res = subprocess.run(
        ["/usr/bin/footprint", pid],
        capture_output=True, text=True, timeout=60,
    ).stdout
    for line in res.splitlines():
        if peak:
            if "phys_footprint_peak" in line:
                return parse_gb(line)
        else:
            if "phys_footprint:" in line and "peak" not in line:
                return parse_gb(line)
    return None


def footprint_peak():
    return footprint_pid(listen_pid(), peak=True)


def footprint_current():
    return footprint_pid(listen_pid(), peak=False)


def launchd_print():
    r = subprocess.run(
        ["launchctl", "print", "gui/%s/%s" % (UID, LABEL)],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def launchd_mc():
    rc, text = launchd_print()
    if rc != 0:
        return None, False
    lines = text.splitlines()
    mc = None
    for i, line in enumerate(lines):
        if "--max-concurrent-requests" in line:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            digits = "".join(ch for ch in nxt if ch.isdigit())
            if digits:
                mc = int(digits)
            break
    return mc, True


def argv_mc_from_ps():
    r = subprocess.run(["ps", "-ax", "-o", "pid=,args="], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "omlx" in line and "--max-concurrent-requests" in line and "l8_mc_real" not in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "--max-concurrent-requests" and i + 1 < len(parts):
                    try:
                        return int(parts[i + 1])
                    except ValueError:
                        return None
    return None


def live_mc_proof():
    ld_mc, ld_loaded = launchd_mc()
    ps_mc = argv_mc_from_ps()
    return {
        "launchd_loaded": ld_loaded,
        "launchd_argv_mc": ld_mc,
        "ps_argv_mc": ps_mc,
        "live_argv_mc": ps_mc if ps_mc is not None else ld_mc,
    }


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
    req = urllib.request.Request(
        BASE + "/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"},
    )
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
        box[i] = stream(
            model,
            "Reply READY only. Digit %s.\n[variant %s-%s]" % (i, salt, i),
            8,
        )

    ts = [threading.Thread(target=job, args=(i,)) for i in range(n_jobs)]
    t0 = time.perf_counter()
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return time.perf_counter() - t0, [box[i] for i in range(n_jobs)]


def health():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def file_mc():
    try:
        d = json.loads((CONF / "settings.json").read_text())
        return (d.get("scheduler") or {}).get("max_concurrent_requests")
    except Exception:
        return None


def wait_up(timeout=240, min_gb=60.0, expect_file_mc=None):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(BASE + "/v1/models", timeout=2).read()
            h = health() or {}
            pool = h.get("engine_pool") or {}
            loaded = pool.get("loaded_count")
            mem = pool.get("current_model_memory") or 0
            gb = footprint_current()
            fmc = file_mc()
            print(
                "wait_up loaded", loaded, "model_mem_gb",
                round(mem / (1024 ** 3), 2) if mem else None,
                "footprint_gb", gb, "file_mc", fmc, flush=True,
            )
            ok_load = loaded == 1 and mem >= 60 * (1024 ** 3)
            ok_fp = gb is not None and min_gb <= gb <= SOFT_GB
            ok_mc = expect_file_mc is None or fmc == expect_file_mc
            if ok_load and ok_fp and ok_mc:
                print("wait_up ok elapsed", round(time.time() - t0, 1), flush=True)
                return True
        except Exception as e:
            print("wait_up", type(e).__name__, flush=True)
        time.sleep(3)
    return False


def kill_port():
    pid = listen_pid()
    if not pid:
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        pass
    for _ in range(40):
        if not listen_pid():
            return
        time.sleep(0.5)
    pid = listen_pid()
    if pid:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except OSError:
            pass
        time.sleep(1)


def bootout():
    print("bootout", LABEL, flush=True)
    subprocess.run(["launchctl", "bootout", "gui/%s/%s" % (UID, LABEL)], capture_output=True)
    subprocess.run(["launchctl", "disable", "gui/%s/%s" % (UID, LABEL)], capture_output=True)
    t0 = time.time()
    while time.time() - t0 < 45:
        rc, _ = launchd_print()
        pid = listen_pid()
        if rc != 0 and not pid:
            time.sleep(3)
            rc2, _ = launchd_print()
            if rc2 != 0 and not listen_pid():
                print("bootout settled, launchd gone, port free", flush=True)
                return
        if pid and rc != 0:
            kill_port()
        time.sleep(1)
    kill_port()
    rc, text = launchd_print()
    if rc == 0:
        raise RuntimeError("FAIL: launchd still loaded after bootout")
    if listen_pid():
        raise RuntimeError("FAIL: :8000 still listening after bootout")


def bootstrap():
    print("bootstrap", LABEL, flush=True)
    subprocess.run(["launchctl", "enable", "gui/%s/%s" % (UID, LABEL)], capture_output=True)
    r = subprocess.run(
        ["launchctl", "bootstrap", "gui/%s" % UID, str(PLIST)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("bootstrap rc", r.returncode, (r.stdout + r.stderr)[:400], flush=True)
    return r.returncode == 0 or "already bootstrapped" in (r.stdout + r.stderr).lower()


def start_serve(mc: int):
    SERVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(OMLX), "serve",
        "--model-dir", str(MODEL_DIR),
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--max-concurrent-requests", str(mc),
        "--paged-ssd-cache-dir", str(CACHE_DIR),
    ]
    print("start_serve mc", mc, "flags --max-concurrent-requests", mc, flush=True)
    logf = open(SERVE_LOG, "ab")
    proc = subprocess.Popen(
        cmd, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, ["--max-concurrent-requests", str(mc), "--port", str(PORT)]


def snapshot_settings():
    d = json.loads((CONF / "settings.json").read_text())
    sch = d.get("scheduler") or {}
    srv = d.get("server") or {}
    return {
        "chunked_prefill": sch.get("chunked_prefill"),
        "max_concurrent_requests": sch.get("max_concurrent_requests"),
        "burst_decode_mode": srv.get("burst_decode_mode"),
    }


def restore_settings_serving():
    p = CONF / "settings.json"
    d = json.loads(p.read_text())
    sch = d.setdefault("scheduler", {})
    sch["max_concurrent_requests"] = 8
    sch["chunked_prefill"] = True
    p.write_text(json.dumps(d, indent=2) + "\n")
    ms = CONF / "model_settings.json"
    if ms.is_file():
        msd = json.loads(ms.read_text())
        changed = False
        for name, m in (msd.get("models") or {}).items():
            if "flash" in name.lower():
                if m.get("mtp_enabled") is not False:
                    m["mtp_enabled"] = False
                    changed = True
                if m.get("mtp_num_draft_tokens") != 3:
                    m["mtp_num_draft_tokens"] = 3
                    changed = True
                if m.get("vlm_mtp_enabled"):
                    m["vlm_mtp_enabled"] = False
                    changed = True
        if changed:
            ms.write_text(json.dumps(msd, indent=2) + "\n")


def measure_arm(label, n_jobs, salt_prefix, n=N):
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    proof = live_mc_proof()
    print("[l8]", label, "proof", proof, flush=True)
    rows = []
    peak_seen = 0.0
    fails = []
    for i in range(n):
        wall, recs = batch(model, n_jobs, "%s-%s" % (salt_prefix, i))
        pg = footprint_peak() or 0
        peak_seen = max(peak_seen, pg)
        if pg > SOFT_GB:
            fails.append("%s peak %s > 96.8" % (label, pg))
        if pg > PLAN_GB:
            fails.append("%s peak %s > 102" % (label, pg))
        if any(r.get("error") for r in recs):
            fails.append("%s stream error" % label)
        if any(r.get("ttft_s") is None for r in recs):
            fails.append("%s missing ttft" % label)
        rows.append({"batch_wall_s": round(wall, 4), "jobs": recs, "peak_gb": pg})
        print("[l8]", label, "i", i, "batch_wall", round(wall, 3), "peak", pg, flush=True)
    snap = snapshot_settings()
    return {
        "label": label,
        "n_jobs": n_jobs,
        "n": n,
        "settings": snap,
        "live_proof": proof,
        "rows": rows,
        "prompt_tokens": [j["prompt_tokens"] for r in rows for j in r["jobs"]],
        "ttft_s": [j["ttft_s"] for r in rows for j in r["jobs"]],
        "wall_s": [j["wall_s"] for r in rows for j in r["jobs"]],
        "cached_tokens": [j["cached_tokens"] for r in rows for j in r["jobs"]],
        "peak_gb": peak_seen,
        "fails": fails,
    }


def warmup():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    model = resolve()
    rec = stream(model, "Reply READY only.\n[variant warmup-mc]", 8)
    print("warmup", rec, "current_gb", footprint_current(), flush=True)
    return rec


def restore_daily():
    restore_settings_serving()
    kill_port()
    time.sleep(1)
    ok = bootstrap()
    if not wait_up(timeout=240, min_gb=60.0, expect_file_mc=8):
        print("FAIL: launchd restore did not reach 60 GB with file_mc=8", flush=True)
        return False
    return ok


def main():
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    fails = []
    stamp = machine_stamp()
    served = None
    restored = False
    mc8 = None
    mc4 = None
    verify_rc = None
    try:
        proof0 = live_mc_proof()
        print("initial proof", proof0, "current", footprint_current(), "peak", footprint_peak(), flush=True)
        if proof0.get("live_argv_mc") != 8:
            fails.append("initial live_argv_mc is %s want 8" % proof0.get("live_argv_mc"))
        if not wait_up(timeout=30, min_gb=60.0, expect_file_mc=8):
            raise RuntimeError("FAIL: live server not loaded")

        mc8 = measure_arm("mc8_live_argv8", 8, "mc8")
        # same-cap 8-way is the 8-arm; also keep 8-job batch walls for vs mc4-with-8-jobs
        mc8_x8 = mc8

        bootout()
        served, flags = start_serve(4)
        if not wait_up(timeout=240, min_gb=60.0, expect_file_mc=4):
            raise RuntimeError("FAIL: mc=4 serve did not reach loaded 60 GB with file_mc=4")
        proof4 = live_mc_proof()
        proof4["file_mc"] = file_mc()
        print("mc4 proof", proof4, "flags", flags, flush=True)
        if proof4.get("launchd_loaded"):
            fails.append("launchd still loaded during mc=4 arm")
        if file_mc() != 4:
            fails.append("settings.json mc is %s want 4 after serve --max-concurrent-requests 4" % file_mc())
        warmup()
        mc4 = measure_arm("mc4_live_argv4", 4, "mc4")
        mc4["serve_flags"] = flags
        mc4["file_mc"] = file_mc()
        mc4["live_proof"] = live_mc_proof()
        mc4["live_proof"]["file_mc"] = file_mc()
        # 8 jobs against a 4-cap: should queue (two waves), not match the mc=8 8-way wall
        mc4_x8 = measure_arm("mc4_cap_with_8jobs", 8, "mc4x8")
        mc4["eight_job_probe"] = {
            "n_jobs": 8,
            "batch_wall_s": [r["batch_wall_s"] for r in mc4_x8["rows"]],
            "ttft_s": mc4_x8["ttft_s"],
            "wall_s": mc4_x8["wall_s"],
            "file_mc": file_mc(),
        }
    except Exception as e:
        fails.append("driver: %s" % e)
        print("ERROR", e, flush=True)
    finally:
        try:
            restored = restore_daily()
        except Exception as e:
            fails.append("restore: %s" % e)
            restored = False
        if served and served.poll() is None:
            try:
                served.terminate()
            except OSError:
                pass
        proof_r = live_mc_proof()
        print("restored proof", proof_r, "current", footprint_current(), flush=True)
        if proof_r.get("live_argv_mc") != 8:
            fails.append("restore live_argv_mc is %s want 8" % proof_r.get("live_argv_mc"))
        if not proof_r.get("launchd_loaded"):
            fails.append("launchd not loaded after restore")
        vsh = subprocess.run(["bash", str(ROOT / "scripts" / "verify.sh")], cwd=str(ROOT))
        verify_rc = vsh.returncode
        if verify_rc != 0:
            fails.append("verify.sh rc %s" % verify_rc)
        va = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
             "--expect", "serving"],
            cwd=str(ROOT),
        )
        if va.returncode != 0:
            fails.append("verify_activation serving rc %s" % va.returncode)

    peak_seen = 0.0
    for arm in (mc8, mc4):
        if arm:
            peak_seen = max(peak_seen, arm.get("peak_gb") or 0)
            fails.extend(arm.get("fails") or [])

    def flatten(arm):
        if not arm:
            return [], [], [], []
        return arm["prompt_tokens"], arm["ttft_s"], arm["wall_s"], arm["cached_tokens"]

    p8, t8, w8, c8 = flatten(mc8)
    p4, t4, w4, c4 = flatten(mc4)
    launchd_won = bool(
        mc4 is None
        or (mc4.get("file_mc") != 4)
        or ((mc4.get("live_proof") or {}).get("launchd_loaded"))
        or ((mc4.get("live_proof") or {}).get("file_mc") not in (4, None) and (mc4.get("file_mc") != 4))
    )
    gate = "closed: bootout + omlx serve --max-concurrent-requests 4; restore bootstrap argv 8"
    if launchd_won or not mc4:
        gate = "partial: launchd still winning or mc4 arm missing"

    payload = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": p8 + p4,
        "ttft_s": t8 + t4,
        "wall_s": w8 + w4,
        "cached_tokens": c8 + c4,
        "n": N,
        "burst_decode_mode": snapshot_settings().get("burst_decode_mode"),
        "concurrency_gate": gate,
        "launchd_won": launchd_won,
        "mc8": mc8,
        "mc4": mc4,
        "restored_launchd": restored,
        "restore_proof": live_mc_proof(),
        "restore_current_gb": footprint_current(),
        "restore_peak_gb": footprint_peak(),
        "verify_sh": verify_rc,
        "fails": fails,
        "pass": (not fails) and mc8 is not None and mc4 is not None and not launchd_won,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print("WROTE", "results/ab_8vs4_live.json", "fails", fails or "none", "pass", payload["pass"], flush=True)
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
