#!/usr/bin/env python3
"""One-brain hot-KV A-B-A-B. Serving. MTP off. mc=8.

A = current (hot_cache_max_size 0). B = --hot-cache-max-size 12GB (one 252K).
Same frozen prefix bytes; salt on tail only. Order A-B-A-B, >=3 accepted pairs.
Soft 96.8 GB = abort B and restore launchd. Do not enable a second head.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import statistics
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
CURRENT_OUT = ROOT / "results" / "hot_cache_current.json"
SERVE_LOG = CONF / "logs" / "serve-hot12-one-brain.log"
N_PAIRS = 3
HOT_SIZE = "12GB"
EXACT_MODEL = "qwen38-flash-next-oq4e-mtp"
RAM_S = 2.0
SSD_S = 6.0

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
        if f.startswith("/") or "Users" in f:
            pub.append("<path>")
            continue
        pub.append(f)
    return pub


def ps_argv_public():
    pid = listen_pid()
    if not pid:
        return []
    out = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True).stdout
    toks = out.split()
    pub = []
    skip = False
    for f in toks:
        if skip:
            pub.append("<path>")
            skip = False
            continue
        if f in ("--model-dir", "--paged-ssd-cache-dir"):
            pub.append(f)
            skip = True
            continue
        if f.startswith("/") or "Users" in f:
            pub.append("<path>")
            continue
        pub.append(f)
    return pub


def frozen_prompt(approx_tokens: int, tail_salt: str) -> tuple:
    reps = max(1, approx_tokens // 65)
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


def start_serve(hot_size: str | None):
    SERVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(OMLX), "serve",
        "--model-dir", str(MODEL_DIR),
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--max-concurrent-requests", "8",
        "--paged-ssd-cache-dir", str(CACHE_DIR),
    ]
    flags = ["--max-concurrent-requests", "8"]
    size = "0" if not hot_size else str(hot_size)
    if size in ("0", "0GB", "0G"):
        cmd += ["--hot-cache-max-size", "0"]
        flags += ["--hot-cache-max-size", "0"]
        # Keep settings.json in lockstep so a leftover 12GB file does not leak into A.
        try:
            p = CONF / "settings.json"
            d = json.loads(p.read_text())
            d.setdefault("cache", {})["hot_cache_max_size"] = "0"
            p.write_text(json.dumps(d, indent=2) + "\n")
        except OSError:
            pass
    else:
        cmd += ["--hot-cache-max-size", size]
        flags += ["--hot-cache-max-size", size]
        try:
            p = CONF / "settings.json"
            d = json.loads(p.read_text())
            d.setdefault("cache", {})["hot_cache_max_size"] = size
            p.write_text(json.dumps(d, indent=2) + "\n")
        except OSError:
            pass
    print("start_serve hot", hot_size or "0", "mc 8", flush=True)
    logf = open(SERVE_LOG, "ab")
    proc = subprocess.Popen(
        cmd, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, flags


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
            if name == EXACT_MODEL:
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


def classify_hit(ttft):
    if ttft is None:
        return "unknown"
    if ttft < RAM_S:
        return "RAM"
    if ttft > SSD_S:
        return "still_SSD"
    return "inconclusive"


def thermal_snapshot():
    return {
        "chassis_c": None,
        "gpu_c": None,
        "note": "record only; powermetrics needs root on this box; not a fail gate",
    }


def throttle_events():
    n = 0
    for p in (SERVE_LOG, CONF / "logs" / "launchd-flash.log"):
        try:
            t = p.read_text(errors="replace")
        except OSError:
            continue
        low = t.lower()
        n += low.count("throttl")
        n += low.count("admission_paused")
    return n


def hot_is_large(val) -> bool:
    if val is None:
        return False
    s = str(val).strip().upper()
    if s in ("0", "0GB", "0G", "OFF", "FALSE", "", "NONE"):
        return False
    if s.endswith("%"):
        return False
    gb = parse_gb(s)
    return gb is not None and gb >= 8.0


def write_current(extra=None):
    stamp = machine_stamp()
    argv = serve_argv_public() or ps_argv_public()
    hot = file_hot()
    fp = footprint_now()
    payload = {
        "measured_at": stamp.get("measured_at"),
        "omlx": stamp.get("omlx"),
        "settings_hot_cache_max_size": str(hot) if hot is not None else None,
        "hot_cache_disabled": str(hot) in ("0", "0GB", "0G", None, "None"),
        "hot_cache_write_through": False,
        "serve_command": "omlx serve --model-dir <model-dir> --host <host> --port 8000 --max-concurrent-requests 8 --paged-ssd-cache-dir <ssd-cache>",
        "serve_argv_public": argv,
        "serve_argv_has_hot_cache_flag": any("hot-cache" in str(x) for x in argv),
        "launchd_label": LABEL,
        "live_mc": file_mc(),
        "chunked_prefill": True,
        "idle_phys_footprint_gb": fp.get("current_gb"),
        "peak_phys_footprint_gb": fp.get("peak_gb"),
        "notes": "Live argv redacted to public flags. hot=0 means the tiering hypothesis is still testable.",
        "machine": stamp,
        "hf_revision": hf_revision(),
        "n": 1,
        "n_note": "snapshot, not a battery; n=1 variant",
        "profile": "snapshot",
        "pass": True,
        "fails": [],
        "prompt_tokens": None,
        "hot_cache_max_size": str(hot) if hot is not None else "0",
    }
    if extra:
        payload.update(extra)
    CURRENT_OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print("WROTE", CURRENT_OUT, "hot", hot, flush=True)
    return payload


def switch_serve(hot_size, served):
    if served is not None and served.poll() is None:
        try:
            served.terminate()
        except OSError:
            pass
        time.sleep(1)
    kill_port()
    time.sleep(1)
    proc, flags = start_serve(hot_size)
    if not wait_up(timeout=240, min_gb=60.0):
        raise RuntimeError("FAIL: serve hot=%s did not reach loaded 60 GB" % hot_size)
    return proc, flags


def one_hit(model, prompt, arm, accepted_ttfts, abort_soft):
    """One accepted hit. Sample >4x hit-median is a miss contaminant; retry once.
    Do not apply 4x to ~250 s fills (miss arm)."""
    attempts = []
    median = statistics.median(accepted_ttfts) if len(accepted_ttfts) >= 2 else None
    for attempt in range(2):
        sample = stream(model, prompt, 8, abort_soft=abort_soft)
        sample["arm"] = arm
        sample["attempt"] = attempt
        sample["tier"] = classify_hit(sample.get("ttft_s"))
        sample["thermal"] = thermal_snapshot()
        sample["throttle_events"] = throttle_events()
        attempts.append(sample)
        tt = sample.get("ttft_s")
        print("[%s] hit attempt" % arm, attempt, "ttft", tt, "cached", sample.get("cached_tokens"),
              "tier", sample.get("tier"), "peak", sample.get("poll_peak_gb"), flush=True)
        if sample.get("error"):
            continue
        if median is not None and tt is not None and tt > 4.0 * median:
            sample["contaminant"] = True
            print("[%s] stall contaminant ttft %s > 4x median %s; retry=%s" % (
                arm, tt, median, attempt == 0), flush=True)
            continue
        sample["contaminant"] = False
        return sample, attempts
    last = attempts[-1]
    last["contaminant"] = last.get("contaminant", True)
    return last, attempts


HITS_PER_ARM = 3


def arm_hits(model, prompt, arm, accepted_ttfts, abort_soft):
    """n hits after this boot. First sample after a restart may be SSD promote."""
    hits = []
    attempts_all = []
    for i in range(HITS_PER_ARM):
        sample, attempts = one_hit(model, prompt, arm, accepted_ttfts, abort_soft)
        attempts_all.extend(attempts)
        hits.append(sample)
        if sample.get("ttft_s") is not None and not sample.get("contaminant"):
            accepted_ttfts.append(sample["ttft_s"])
    good = [h.get("ttft_s") for h in hits if h.get("ttft_s") is not None and not h.get("contaminant")]
    med = statistics.median(good) if good else None
    return {
        "hits": hits,
        "attempts": attempts_all,
        "median_ttft_s": med,
        "tier": classify_hit(med) if med is not None else "unknown",
        "n": len(good),
    }


def main() -> int:
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    stamp = machine_stamp()
    fails = []
    served = None
    restored = False
    verify_restore = None
    b_started = False
    original_hot = file_hot()
    prefix_sha = None
    miss = None
    pairs = []
    peak_seen = 0.0
    idle0 = footprint_now()

    current = write_current()
    if hot_is_large(current.get("hot_cache_max_size")) or hot_is_large(original_hot):
        print("STOP: hot cache already large; tiering hypothesis dead", flush=True)
        return 0

    try:
        print("idle", idle0, "file_hot", original_hot, "argv", current.get("serve_argv_public"), flush=True)

        bootout()
        b_started = True
        served, flags_a = start_serve("0")
        if not wait_up(timeout=240, min_gb=60.0):
            raise RuntimeError("FAIL: A serve did not reach loaded 60 GB")
        model = resolve()
        wu = stream(model, "Reply with the single word: READY\n[variant warmup-hot1]", 8)
        print("warmup dropped", wu.get("wall_s"), flush=True)

        salt = time.strftime("%H%M%S") + "-hot1"
        prefix, tail, prompt = frozen_prompt(252000, salt)
        prefix_sha = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
        if prefix + tail != prompt:
            fails.append("prefix+tail != prompt")

        first = stream(model, prompt, 8, abort_soft=False)
        first["thermal"] = thermal_snapshot()
        first["throttle_events"] = throttle_events()
        after_first = footprint_now()
        peak_seen = max(peak_seen, after_first.get("peak_gb") or 0, first.get("poll_peak_gb") or 0)
        print("[A] first", first.get("ttft_s"), "cached", first.get("cached_tokens"),
              "pt", first.get("prompt_tokens"), "peak", peak_seen, flush=True)
        if first.get("error"):
            fails.append("first error %s" % first["error"])
        if first.get("cached_tokens"):
            first["label"] = "prefix_already_resident"
            first["tier"] = classify_hit(first.get("ttft_s"))
            print("note: frozen prefix already on SSD; not a 240k cold miss", flush=True)
        else:
            first["label"] = "miss"
            first["tier"] = "miss"
            if (first.get("ttft_s") or 0) < 150:
                fails.append("A miss ttft %s not ~229s class" % first.get("ttft_s"))
        miss = first
        if peak_seen > SOFT_GB:
            raise RuntimeError("first already over soft 96.8 — skip B")

        accepted_a = []
        accepted_b = []
        order = []
        flags_b = ["--max-concurrent-requests", "8", "--hot-cache-max-size", HOT_SIZE]
        # A-B-A-B ... until N_PAIRS accepted pairs. Pair 0 A stays on this boot.
        for i in range(N_PAIRS):
            if i > 0:
                served, flags_a = switch_serve("0", served)
            fp_idle_a = footprint_now()
            arm_a = arm_hits(model, prompt, "A", accepted_a, abort_soft=False)
            fp_a = footprint_now()
            peak_seen = max(peak_seen, fp_a.get("peak_gb") or 0)
            peak_seen = max(peak_seen, max((h.get("poll_peak_gb") or 0) for h in arm_a["hits"]) if arm_a["hits"] else 0)
            if peak_seen > SOFT_GB:
                raise RuntimeError("A peak %s > 96.8" % peak_seen)
            order.append("A")

            served, flags_b = switch_serve(HOT_SIZE, served)
            fp_idle_b = footprint_now()
            arm_b = arm_hits(model, prompt, "B", accepted_b, abort_soft=True)
            fp_b = footprint_now()
            peak_seen = max(peak_seen, fp_b.get("peak_gb") or 0)
            peak_seen = max(peak_seen, max((h.get("poll_peak_gb") or 0) for h in arm_b["hits"]) if arm_b["hits"] else 0)
            if peak_seen > SOFT_GB:
                raise RuntimeError("B peak %s > 96.8 — abort B" % peak_seen)
            order.append("B")

            pair_ok = arm_a.get("n", 0) >= HITS_PER_ARM and arm_b.get("n", 0) >= HITS_PER_ARM
            ratio = None
            if arm_a.get("median_ttft_s") and arm_b.get("median_ttft_s"):
                ratio = round(arm_a["median_ttft_s"] / arm_b["median_ttft_s"], 4)
            pairs.append({
                "i": i,
                "accepted": pair_ok,
                "ratio_a_over_b": ratio,
                "A": {
                    "idle_gb": fp_idle_a.get("current_gb"),
                    "settle_gb": fp_a.get("current_gb"),
                    "peak_gb": fp_a.get("peak_gb"),
                    "median_ttft_s": arm_a.get("median_ttft_s"),
                    "tier": arm_a.get("tier"),
                    "hits": arm_a.get("hits"),
                },
                "B": {
                    "idle_gb": fp_idle_b.get("current_gb"),
                    "settle_gb": fp_b.get("current_gb"),
                    "peak_gb": fp_b.get("peak_gb"),
                    "median_ttft_s": arm_b.get("median_ttft_s"),
                    "tier": arm_b.get("tier"),
                    "hits": arm_b.get("hits"),
                    "serve_flags_public": flags_b,
                },
            })
            print("pair", i, "accepted", pair_ok, "ratio", ratio,
                  "A", arm_a.get("median_ttft_s"), arm_a.get("tier"),
                  "B", arm_b.get("median_ttft_s"), arm_b.get("tier"), flush=True)

        if sum(1 for p in pairs if p.get("accepted")) < N_PAIRS:
            fails.append("accepted pairs %s < %s" % (
                sum(1 for p in pairs if p.get("accepted")), N_PAIRS))
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

    a_hits = [p["A"].get("median_ttft_s") for p in pairs
              if p.get("accepted") and p["A"].get("median_ttft_s") is not None]
    b_hits = [p["B"].get("median_ttft_s") for p in pairs
              if p.get("accepted") and p["B"].get("median_ttft_s") is not None]
    med_a = statistics.median(a_hits) if a_hits else None
    med_b = statistics.median(b_hits) if b_hits else None
    ratio = round(med_a / med_b, 4) if med_a and med_b else None
    settle_b = None
    if pairs:
        settle_b = pairs[-1]["B"].get("settle_gb")
    settle_a_last = pairs[-1]["A"].get("settle_gb") if pairs else None
    tier_b = classify_hit(med_b) if med_b is not None else "unknown"
    faster = bool(med_a and med_b and med_b < med_a * 0.7)
    settle_moved = bool(settle_b is not None and settle_b >= 76.0)
    peak_ok = peak_seen <= SOFT_GB
    negative = bool(settle_b is not None and settle_b >= 76.0 and med_b is not None and med_b > SSD_S)
    win = bool(settle_moved and faster and peak_ok and not negative and len(b_hits) >= N_PAIRS)
    if negative:
        verdict = "NEGATIVE: paid RAM (~78 GB settle) but hit still SSD-class (>6 s). Not a win."
        win = False
    elif win and tier_b == "RAM":
        verdict = "win: settle moved toward ~78 GB, hit <2 s (RAM), peak<=96.8; one head"
    elif win and tier_b == "inconclusive":
        verdict = (
            "speed/settle win but tier INCONCLUSIVE (2-6 s): do not call it RAM. "
            "peak<=96.8; one head"
        )
    elif win:
        verdict = "win: settle moved and hit clearly faster; peak<=96.8; one head"
    else:
        verdict = "no win (need settle ~78, clearly faster hits, peak<=96.8, not still ~9 s)"

    payload = {
        "machine": stamp,
        "omlx": stamp.get("omlx"),
        "hf_revision": hf_revision(),
        "peak_gb": peak_seen,
        "prompt_tokens": ([miss.get("prompt_tokens")] if miss else []) + [
            h.get("prompt_tokens") for p in pairs for h in (p.get("A", {}).get("hits") or [])
        ] + [
            h.get("prompt_tokens") for p in pairs for h in (p.get("B", {}).get("hits") or [])
        ],
        "ttft_s": ([miss.get("ttft_s")] if miss else []) + [
            h.get("ttft_s") for p in pairs for h in (p.get("A", {}).get("hits") or [])
        ] + [
            h.get("ttft_s") for p in pairs for h in (p.get("B", {}).get("hits") or [])
        ],
        "cached_tokens": ([miss.get("cached_tokens")] if miss else []) + [
            h.get("cached_tokens") for p in pairs for h in (p.get("A", {}).get("hits") or [])
        ] + [
            h.get("cached_tokens") for p in pairs for h in (p.get("B", {}).get("hits") or [])
        ],
        "n": len([p for p in pairs if p.get("accepted")]),
        "n_pairs_requested": N_PAIRS,
        "order": "A-B-A-B",
        "ratio_median_A_over_B": ratio,
        "median_hit_ttft_A_s": med_a,
        "median_hit_ttft_B_s": med_b,
        "pre_register": {
            "RAM_s": RAM_S,
            "still_SSD_s": SSD_S,
            "inconclusive": "2-6 s",
            "B_tier": tier_b,
        },
        "idle_gb": idle0.get("current_gb"),
        "settle_gb_A": settle_a_last,
        "settle_gb_B": settle_b,
        "throttle_events": throttle_events(),
        "thermal": thermal_snapshot(),
        "hot_cache_size_chosen": HOT_SIZE,
        "hot_cache_size_why": (
            "12GB is the top of the 10-12GB one-brain budget. "
            "10% is not a valid parse_size (ValueError)."
        ),
        "original_hot_cache_max_size": original_hot,
        "restored_hot_cache_max_size": file_hot(),
        "restored_mc": file_mc(),
        "restored_launchd": restored,
        "verify_sh_after_restore": verify_restore,
        "heads": 1,
        "mtp": "off",
        "salt_on": "tail",
        "prefix_sha256": prefix_sha,
        "miss": miss,
        "pairs": pairs,
        "win": win,
        "negative": negative,
        "verdict": verdict,
        "profile": "serving",
        "warmup_dropped": True,
        "fails": fails,
        "pass": miss is not None and restored,
        "hot_cache_max_size": HOT_SIZE,
        "pr48_archive": "results/hot_cache_one_brain_pr48.json",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print("WROTE", OUT, "win", win, "verdict", verdict, "fails", fails or "none", flush=True)
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
