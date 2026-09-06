#!/usr/bin/env python3
"""One-brain hot-KV A/B. Serving. MTP off. mc=8.

A = current (hot_cache_max_size 0): one frozen ~240k miss + n=3 hits.
B = --hot-cache-max-size 12GB (one 252K only). Same prefix bytes; salt on tail.
Soft 96.8 GB = abort B and restore launchd. Do not enable a second head.
"""
from __future__ import annotations

import hashlib
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

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8000")
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
OUT = ROOT / "results" / "hot_cache_one_brain.json"
SERVE_LOG = CONF / "logs" / "serve-hot12-one-brain.log"
N = 3
HOT_SIZE = "12GB"
DISK_HIT_LO = 8.3
DISK_HIT_HI = 9.0

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


def footprint_now():
    pid = listen_pid()
    return {
        "current_gb": footprint_pid(pid, peak=False),
        "peak_gb": footprint_pid(pid, peak=True),
        "pid": pid,
    }


def launchd_print():
    r = subprocess.run(
        ["launchctl", "print", "gui/%s/%s" % (UID, LABEL)],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout + r.stderr


def serve_argv_public():
    rc, text = launchd_print()
    flags = []
    if rc == 0:
        take = False
        for line in text.splitlines():
            s = line.strip()
            if s == "arguments = {":
                take = True
                continue
            if take:
                if s == "}":
                    break
                flags.append(s.strip("\t "))
    # redact user paths
    pub = []
    skip_next = False
    for f in flags:
        if skip_next:
            pub.append("<path>")
            skip_next = False
            continue
        if f in ("--model-dir", "--paged-ssd-cache-dir"):
            pub.append(f)
            skip_next = True
            continue
        pub.append(f)
    return pub


def frozen_prompt(approx_tokens: int, tail_salt: str) -> tuple[str, str, str]:
    reps = max(1, approx_tokens // 65)
    # Unique frozen block vs L2 prefix_hit_miss so arm A is a real miss.
    prefix = (
        "Read carefully. Reply with exactly: DONE\n\n"
        "Frozen-prefix-block hot-one-brain.\n" + UNIT * reps
    )
    tail = "\n[variant %s]" % tail_salt
    return prefix, tail, prefix + tail


def stream(model: str, prompt: str, max_tokens: int = 8, abort_soft=False) -> dict:
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
    stop = {"flag": False, "peak": None, "current": None}

    def poller():
        while not stop["flag"]:
            fp = footprint_now()
            stop["current"] = fp.get("current_gb")
            stop["peak"] = fp.get("peak_gb")
            cur = fp.get("current_gb") or 0
            if abort_soft and cur > SOFT_GB:
                stop["flag"] = True
                return
            time.sleep(2)

    th = threading.Thread(target=poller, daemon=True)
    th.start()
    t0 = time.perf_counter()
    first = None
    usage = {}
    text = []
    err = None
    try:
        with urllib.request.urlopen(req, timeout=7200) as r:
            for raw in r:
                if abort_soft and (stop.get("current") or 0) > SOFT_GB:
                    err = "abort: current_gb %s > 96.8" % stop.get("current")
                    break
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
    stop["flag"] = True
    wall = time.perf_counter() - t0
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    fp = footprint_now()
    return {
        "ttft_s": round(first, 4) if first is not None else None,
        "wall_s": round(wall, 4),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cached_tokens": int(cached) if cached is not None else None,
        "completion": "".join(text).strip()[:200],
        "error": err,
        "footprint": fp,
        "poll_peak_gb": stop.get("peak"),
        "poll_current_gb": stop.get("current"),
    }


def health():
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def file_hot():
    try:
        d = json.loads((CONF / "settings.json").read_text())
        return (d.get("cache") or {}).get("hot_cache_max_size")
    except Exception:
        return None


def file_mc():
    try:
        d = json.loads((CONF / "settings.json").read_text())
        return (d.get("scheduler") or {}).get("max_concurrent_requests")
    except Exception:
        return None


def wait_up(timeout=240, min_gb=60.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen(BASE + "/v1/models", timeout=2).read()
            h = health() or {}
            pool = h.get("engine_pool") or {}
            loaded = pool.get("loaded_count")
            mem = pool.get("current_model_memory") or 0
            gb = footprint_now().get("current_gb")
            print(
                "wait_up loaded", loaded, "footprint_gb", gb, "file_hot", file_hot(),
                flush=True,
            )
            ok_load = loaded == 1 and mem >= 60 * (1024 ** 3)
            ok_fp = gb is not None and min_gb <= gb <= SOFT_GB
            if ok_load and ok_fp:
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
    rc, _ = launchd_print()
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


def start_serve_hot(size: str):
    SERVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(OMLX), "serve",
        "--model-dir", str(MODEL_DIR),
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--max-concurrent-requests", "8",
        "--paged-ssd-cache-dir", str(CACHE_DIR),
        "--hot-cache-max-size", size,
    ]
    print("start_serve hot", size, "mc 8", flush=True)
    logf = open(SERVE_LOG, "ab")
    proc = subprocess.Popen(
        cmd, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, ["--max-concurrent-requests", "8", "--hot-cache-max-size", size]


def restore_settings_serving():
    p = CONF / "settings.json"
    d = json.loads(p.read_text())
    sch = d.setdefault("scheduler", {})
    sch["max_concurrent_requests"] = 8
    sch["chunked_prefill"] = True
    cache = d.setdefault("cache", {})
    cache["hot_cache_max_size"] = "0"
    cache["hot_cache_write_through"] = False
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
                if m.get("vlm_mtp_enabled"):
                    m["vlm_mtp_enabled"] = False
                    changed = True
        if changed:
            ms.write_text(json.dumps(msd, indent=2) + "\n")


def restore_daily():
    restore_settings_serving()
    kill_port()
    time.sleep(1)
    ok = bootstrap()
    if not wait_up(timeout=240, min_gb=60.0):
        print("FAIL: launchd restore did not reach 60 GB", flush=True)
        return False
    return ok


def run_verify():
    vsh = subprocess.run(["bash", str(ROOT / "scripts" / "verify.sh")], cwd=str(ROOT))
    return vsh.returncode


def measure_pair(model, prompt, n, abort_soft, label):
    fails = []
    idle = footprint_now()
    miss = stream(model, prompt, 8, abort_soft=abort_soft)
    miss["label"] = "miss"
    after_miss = footprint_now()
    print(
        "[%s] first" % label, miss.get("wall_s"), "cached", miss.get("cached_tokens"),
        "pt", miss.get("prompt_tokens"), "peak", after_miss.get("peak_gb"),
        flush=True,
    )
    if miss.get("error"):
        fails.append("%s first error %s" % (label, miss["error"]))
    peak_seen = after_miss.get("peak_gb") or miss.get("poll_peak_gb") or 0.0
    if peak_seen > SOFT_GB:
        fails.append("%s peak_gb %s > 96.8" % (label, peak_seen))
        return {
            "label": label,
            "idle_gb": idle.get("current_gb"),
            "after_first_gb": after_miss.get("current_gb"),
            "peak_gb": peak_seen,
            "miss": miss,
            "hits": [],
            "after_hit_gb": after_miss.get("current_gb"),
            "fails": fails,
            "aborted": True,
        }

    hits = []
    for i in range(n):
        hit = stream(model, prompt, 8, abort_soft=abort_soft)
        hit["label"] = "hit"
        fp = footprint_now()
        pg = fp.get("peak_gb") or 0
        peak_seen = max(peak_seen, pg, hit.get("poll_peak_gb") or 0)
        if hit.get("error"):
            fails.append("%s hit %s error %s" % (label, i, hit["error"]))
        if pg > SOFT_GB:
            fails.append("%s hit %s peak_gb %s > 96.8" % (label, i, pg))
            hits.append({"i": i, "hit": hit, "footprint": fp})
            break
        hits.append({"i": i, "hit": hit, "footprint": fp})
        print(
            "[%s] hit" % label, i, hit.get("wall_s"), "cached", hit.get("cached_tokens"),
            "peak", pg, flush=True,
        )

    after_hit = footprint_now()
    return {
        "label": label,
        "idle_gb": idle.get("current_gb"),
        "after_first_gb": after_miss.get("current_gb"),
        "after_hit_gb": after_hit.get("current_gb"),
        "peak_gb": peak_seen,
        "miss": miss,
        "hits": hits,
        "fails": fails,
        "aborted": False,
        "file_hot": file_hot(),
        "file_mc": file_mc(),
    }


def arm_success(arm):
    if not arm or arm.get("aborted") or not arm.get("hits"):
        return False
    if (arm.get("peak_gb") or 0) > SOFT_GB:
        return False
    walls = [h["hit"].get("wall_s") for h in arm["hits"] if h["hit"].get("wall_s") is not None]
    if len(walls) < N:
        return False
    mean = sum(walls) / len(walls)
    # clearly faster than measured disk-hit band 8.3–9.0 s
    return mean < DISK_HIT_LO - 1.0


def main() -> int:
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    stamp = machine_stamp()
    fails = []
    served = None
    restored = False
    verify_b = None
    verify_restore = None
    arm_a = None
    arm_b = None
    b_started = False
    original_hot = file_hot()
    prefix_sha = None
    try:
        model = resolve()
        idle0 = footprint_now()
        print("idle", idle0, "file_hot", original_hot, "argv", serve_argv_public(), flush=True)
        wu = stream(model, "Reply with the single word: READY\n[variant warmup-hot1]", 8)
        print("warmup dropped", wu.get("wall_s"), flush=True)

        salt = time.strftime("%H%M%S") + "-hot1"
        prefix, tail, prompt = frozen_prompt(252000, salt)
        prefix_sha = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
        if prefix + tail != prompt:
            fails.append("prefix+tail != prompt")

        arm_a = measure_pair(model, prompt, N, abort_soft=False, label="A_hot0")
        fails.extend(arm_a.get("fails") or [])
        if (arm_a.get("miss") or {}).get("cached_tokens"):
            fails.append("A first request cached_tokens %s want 0 (not a miss)" %
                         arm_a["miss"].get("cached_tokens"))
        aw = (arm_a.get("miss") or {}).get("wall_s") or 0
        if aw < 150:
            fails.append("A first wall %s not ~229s miss class" % aw)
        if (arm_a.get("peak_gb") or 0) > SOFT_GB:
            raise RuntimeError("A already over soft 96.8 — skip B")

        b_started = True
        bootout()
        served, flags = start_serve_hot(HOT_SIZE)
        if not wait_up(timeout=240, min_gb=60.0):
            raise RuntimeError("FAIL: hot-12GB serve did not reach loaded 60 GB")
        verify_b = run_verify()
        print("verify.sh after B boot rc", verify_b, flush=True)
        if verify_b != 0:
            raise RuntimeError("verify.sh failed after B restart rc %s" % verify_b)
        if file_mc() != 8:
            fails.append("B file_mc %s want 8" % file_mc())
        arm_b = measure_pair(model, prompt, N, abort_soft=True, label="B_hot12")
        fails.extend(arm_b.get("fails") or [])
        if arm_b.get("aborted") or (arm_b.get("peak_gb") or 0) > SOFT_GB:
            fails.append("B aborted or peak > 96.8 — revert")
            arm_b["win"] = False
        else:
            arm_b["serve_flags_public"] = flags
            arm_b["win"] = arm_success(arm_b)
            # still one head: only this single stream ran
            arm_b["heads"] = 1
    except Exception as e:
        fails.append("driver: %s" % e)
        print("ERROR", e, flush=True)
    finally:
        try:
            restore_settings_serving()
            if b_started or served is not None:
                restored = restore_daily()
            else:
                restored = True
        except Exception as e:
            fails.append("restore: %s" % e)
            restored = False
        if served and served.poll() is None:
            try:
                served.terminate()
            except OSError:
                pass
        if b_started or served is not None:
            verify_restore = run_verify()
            if verify_restore != 0:
                fails.append("verify.sh after restore rc %s" % verify_restore)

    win = bool(arm_b and arm_b.get("win") and (arm_b.get("peak_gb") or 0) <= SOFT_GB)
    if win:
        verdict = "hot 12GB kept one brain in RAM (hits faster than disk 8.3-9.0s); peak<=96.8; one head"
    elif arm_b and (arm_b.get("peak_gb") or 0) > SOFT_GB:
        verdict = "left off because peak crossed 96.8"
    else:
        verdict = "left off because hit did not improve vs disk 8.3-9.0s (or B did not run)"

    def flatten(arm):
        if not arm:
            return [], [], [], []
        miss = arm.get("miss") or {}
        hits = arm.get("hits") or []
        pt = [miss.get("prompt_tokens")] + [h["hit"].get("prompt_tokens") for h in hits]
        tt = [miss.get("ttft_s")] + [h["hit"].get("ttft_s") for h in hits]
        ww = [miss.get("wall_s")] + [h["hit"].get("wall_s") for h in hits]
        cc = [miss.get("cached_tokens")] + [h["hit"].get("cached_tokens") for h in hits]
        return pt, tt, ww, cc

    pa, ta, wa, ca = flatten(arm_a)
    pb, tb, wb, cb = flatten(arm_b)
    peak_seen = max(arm_a.get("peak_gb") or 0 if arm_a else 0,
                    arm_b.get("peak_gb") or 0 if arm_b else 0)

    payload = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": pa + pb,
        "ttft_s": ta + tb,
        "wall_s": wa + wb,
        "cached_tokens": ca + cb,
        "n": N,
        "hot_cache_size_chosen": HOT_SIZE,
        "hot_cache_size_why": (
            "12GB is the top of the 10-12GB one-brain budget. "
            "10% is not a valid parse_size (ValueError)."
        ),
        "original_hot_cache_max_size": original_hot,
        "restored_hot_cache_max_size": file_hot(),
        "restored_mc": file_mc(),
        "restored_launchd": restored,
        "verify_sh_after_b": verify_b,
        "verify_sh_after_restore": verify_restore,
        "heads": 1,
        "mtp": "off",
        "salt_on": "tail",
        "prefix_sha256": prefix_sha,
        "A": arm_a,
        "B": arm_b,
        "win": win,
        "verdict": verdict,
        "profile": "serving",
        "warmup_dropped": True,
        "fails": fails,
        "pass": arm_a is not None and restored,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print("WROTE", OUT, "win", win, "verdict", verdict, "fails", fails or "none", flush=True)
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
