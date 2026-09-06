#!/usr/bin/env python3
"""8-slot all-flash warm + acceptance battery.

Default (issue #40 / L1): 1x ~240k-measured head + short slots.
Dual-head is gated: pass --dual-head. Do not make dual the default.

Do not sell 252K until the harness hits it (report JSON prompt_tokens).
Server: oMLX 0.6.4 flash-next on :8000, chunked on, MTP off, enforcer 107.5GB.

Do not replace results/warm_8slot_results.json (2026-08-31 dual-head receipt)
with a failed re-run. L1 writes results/single_head_latency.json instead.

"""
import json, subprocess, time, threading, urllib.request, statistics
import sys as _sys

DUAL_HEAD = "--dual-head" in _sys.argv
if DUAL_HEAD:
    _sys.argv = [a for a in _sys.argv if a != "--dual-head"]
PHASE_ARGS = [a for a in _sys.argv[1:] if not a.startswith("-")]
if "--help" in _sys.argv or "-h" in _sys.argv:
    print("usage: warm-8slot.py [--dual-head] [W1] [W2]")
    print("default: one 252K head + short slots. --dual-head restores the old pair.")
    raise SystemExit(0)

BASE = "http://127.0.0.1:8000"
# Same resolver as scripts/verify.sh / scripts/resolve_model.py — do not
# hardcode a renamed checkpoint.
def _resolve_model():
    import os, json, urllib.request
    fallback = os.environ.get("OMLX_MODEL", "qwen38-flash-next-oq4e-mtp")
    try:
        with urllib.request.urlopen(BASE + "/v1/models", timeout=5) as r:
            ids = [m.get("id") for m in json.load(r).get("data") or [] if m.get("id")]
        for i in ids:
            if "flash" in i.lower():
                return i
        return ids[0] if ids else fallback
    except Exception:
        return fallback
MODEL = _resolve_model()
OUT = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)),
                                 "..", "results", "warm_8slot_results.json")
SALT = time.strftime("%H%M%S")

UNIT = ("Linear attention layers process the sequence with constant memory per step, while full "
        "attention layers attend to all previous tokens every fourth layer. Multi-token prediction "
        "heads draft several tokens per verification cycle, and an adaptive controller adjusts draft "
        "depth from rolling acceptance statistics. Prefix caching stores previously computed states "
        "so repeated system prompts skip recomputation. ")

R = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "salt": SALT, "phases": {}, "errors": [],
     "notes": ["8-slot all-flash default: 1x252K head + short slots, oMLX 0.6.4 chunked on, MTP off",
               "dual-head gated --dual-head" if DUAL_HEAD else "dual-head off"]}

def save():
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1)

def footprint():
    out = subprocess.run(["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return None
    p = out.split()[0]
    res = subprocess.run(["/usr/bin/footprint", p], capture_output=True, text=True, timeout=60).stdout
    cur = peak = None
    for line in res.splitlines():
        if "phys_footprint_peak" in line:
            peak = line.split()[1]
        elif "phys_footprint:" in line:
            cur = line.split()[1]
    return {"current": cur, "peak": peak}

def df_free_gb():
    res = subprocess.run(["df", "-k", "/System/Volumes/Data"], capture_output=True, text=True).stdout
    return int(res.strip().splitlines()[-1].split()[3]) // 1048576

def mk_prompt(approx_tokens, salt, extra=""):
    reps = max(1, approx_tokens // 65)
    return (f"Read carefully. Reply with exactly: DONE-{salt}\n\n") + UNIT * reps + f"\n[variant {salt}]" + extra

def one(tag, prompt, out, max_tokens=8, temp=0):
    return stream_chat(tag, [{"role": "user", "content": prompt}], out, max_tokens, temp)


def follow(tag, prompt, salt, out, max_tokens=16, temp=0):
    """Second turn against the SAME long prompt (issue #18/#19).

    The assistant turn repeats the completion the first turn produced, so the
    server can reuse the full prefix (cache hit, not a re-prefill) and the
    question is a real long-context retrieval check: reply with exactly the
    needle token embedded in the prompt.
    """
    messages = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": f"DONE-{salt}"},
        {"role": "user",
         "content": "Output exactly the token you were told to remember, and nothing else."},
    ]
    return stream_chat(tag, messages, out, max_tokens, temp)


def stream_chat(tag, messages, out, max_tokens=8, temp=0):
    body = json.dumps({"model": MODEL, "messages": messages,
                       "max_tokens": max_tokens, "temperature": temp,
                       "stream": True, "stream_options": {"include_usage": True}}).encode()
    req = urllib.request.Request(f"{BASE}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = usage = err = None
    text = []
    try:
        with urllib.request.urlopen(req, timeout=7200) as r:
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
                if o.get("choices") and first is None:
                    first = time.perf_counter() - t0
    except Exception as e:
        err = str(e)[:150]
    wall = time.perf_counter() - t0
    pt = usage.get("prompt_tokens", 0) if usage else 0
    completion = "".join(text).strip()
    out[tag] = {"ttft_s": round(first, 3) if first else None, "wall_s": round(wall, 2),
                "prompt_tokens": pt,
                "completion_tokens": usage.get("completion_tokens", 0) if usage else 0,
                "completion": completion[:200],
                "error": err}
    if err:
        R["errors"].append(f"{tag}: {err}")
    return completion

RESULTS = {}

def cached_tokens():
    """Server-side prefix-cache counter (stats.json), never invented."""
    try:
        with open(__import__("os").path.expanduser("~/.omlx/stats.json")) as f:
            data = json.load(f)
        per = data.get("per_model", {}).get(MODEL, {})
        return int(per.get("cached_tokens", 0))
    except Exception:
        return None


def run_group(name, jobs, tick_schedule=None, followups=None):
    RESULTS.clear()
    threads = [threading.Thread(target=one, args=(t, p, RESULTS, mt)) for t, p, mt in jobs]
    t0 = time.perf_counter()
    # Snapshot the cache counter before the follow-ups fire (they start after
    # their delay, and the "before" value must not include their own hits).
    resid_before = cached_tokens() if followups else None
    for th in threads:
        th.start()
    tick_threads = []
    if tick_schedule:
        def fire(delay, label):
            time.sleep(delay)
            tr = {}
            one(label, f"Planner tick {label}: reply READY only.", tr, 16)
            RESULTS[label] = tr.get(label)
        for delay, label in tick_schedule:
            th = threading.Thread(target=fire, args=(delay, label))
            th.start()
            tick_threads.append(th)
    resid_threads = []
    resid = {}
    if followups:
        def fire_follow(delay, tag, prompt, salt):
            time.sleep(delay)
            follow(tag, prompt, salt, resid)
        for delay, tag, prompt, salt in followups:
            th = threading.Thread(target=fire_follow, args=(delay, tag, prompt, salt))
            th.start()
            resid_threads.append(th)
    for th in threads:
        th.join()
    wall = round(time.perf_counter() - t0, 2)
    for th in tick_threads:
        th.join(timeout=1800)
    for th in resid_threads:
        th.join(timeout=3600)
    fills = [v for k, v in RESULTS.items() if not k.startswith("tick-")]
    ticks = [v for k, v in RESULTS.items() if k.startswith("tick-")]
    rec = {"wall_s": wall, "streams": dict(RESULTS)}
    if fills:
        walls = [f["wall_s"] for f in fills if f.get("wall_s")]
        rec["fill_walls_s"] = sorted(walls)
        rec["fill_wall_spread_s"] = round(max(walls) - min(walls), 2) if walls else None
    if any(t for t in ticks):
        tw = [t["wall_s"] for t in ticks if t and t.get("wall_s")]
        rec["tick_walls_s"] = tw
        rec["tick_median_s"] = round(statistics.median(tw), 2) if tw else None
    if resid:
        rec["residency"] = {
            "followups": dict(resid),
            "cached_tokens_before": resid_before,
        }
    rec["footprint"] = footprint()
    rec["df_free_gb"] = df_free_gb()
    if "residency" in rec:
        rec["residency"]["cached_tokens_after"] = cached_tokens()
        cb = rec["residency"].get("cached_tokens_before") or 0
        ca = rec["residency"].get("cached_tokens_after") or 0
        rec["residency"]["cached_delta"] = ca - cb
    R["phases"][name] = rec
    save()
    print(f"[warm8] {name} wall={wall}s spread={rec.get('fill_wall_spread_s')}s "
          f"footprint={rec['footprint']}", flush=True)

def advertised_ctx():
    try:
        with urllib.request.urlopen(BASE + "/v1/models", timeout=5) as r:
            data = json.load(r)
        return max(int(m.get("max_model_len") or 0) for m in data.get("data") or [])
    except Exception as e:
        R["errors"].append("ctx: %s" % e)
        return 0

def _gb(x):
    if x is None:
        return None
    s = str(x).strip().upper().replace(",", "")
    try:
        if s.endswith("GB"):
            s = s[:-2]
        elif s.endswith("G"):
            s = s[:-1]
        return float(s)
    except ValueError:
        return None

def evaluate_gates():
    """Fail-closed. Limits from 2026-08-31 receipts plus a small stated slack."""
    fails = []
    ctx = advertised_ctx()
    R["advertised_ctx"] = ctx
    if ctx < 262144:
        fails.append("advertised ctx %s < 262144" % ctx)
    if R.get("errors"):
        fails.append("stream errors: %s" % R["errors"][:8])
    token_band = {
        "orch-": (240393, 0.03),
        "tdd-": (30585, 0.03),
        "coder-": (61089, 0.03),
        "audit-": (61089, 0.03),
    }
    for phase, rec in (R.get("phases") or {}).items():
        streams = rec.get("streams") or {}
        groups = {}
        for tag, st in streams.items():
            if not st or tag.startswith("tick-"):
                continue
            if st.get("error"):
                fails.append("%s/%s error" % (phase, tag))
            text = (st.get("completion") or "")
            # salt is embedded in the DONE- line of that stream's prompt via mk_prompt
            if "DONE-" not in text:
                fails.append("%s/%s completion %r missing DONE-{salt}" % (phase, tag, text[:80]))
            pt = st.get("prompt_tokens") or 0
            for prefix, (target, tol) in token_band.items():
                if tag.startswith(prefix):
                    lo, hi = target * (1 - tol), target * (1 + tol)
                    if not (lo <= pt <= hi):
                        fails.append("%s/%s prompt_tokens %s not in %.0f–%.0f (measured %s ±3%%)" %
                                     (phase, tag, pt, lo, hi, target))
                    groups.setdefault(prefix, []).append(st.get("wall_s") or 0)
                    break
        for prefix, walls in groups.items():
            if len(walls) >= 2:
                spread = max(walls) - min(walls)
                if spread > 15:
                    fails.append("%s %s same-size spread %.2fs > 15s" % (phase, prefix, spread))
        peak = _gb((rec.get("footprint") or {}).get("peak"))
        if peak is not None and peak > 102:
            fails.append("%s peak footprint %s GB > 102 GB" % (phase, peak))
        resid = rec.get("residency")
        if resid:
            needle = "NEEDLE-%s" % SALT
            for tag, fu in (resid.get("followups") or {}).items():
                if fu.get("error"):
                    fails.append("%s/%s residency error" % (phase, tag))
                got = (fu.get("completion") or "").strip()
                if got != needle:
                    fails.append("%s/%s long-context retrieval %r != %r" % (phase, tag, got[:40], needle))
            delta = resid.get("cached_delta") or 0
            need = 2 * 252000 if DUAL_HEAD else 252000
            if delta < need:
                fails.append("%s prefix cache delta %s < %s (252K head(s) must stay resident)"
                             % (phase, delta, need))
            if (resid.get("cached_tokens_before") is None or resid.get("cached_tokens_after") is None):
                fails.append("%s could not read stats.json cached_tokens" % phase)
    R["gate_fails"] = fails
    return fails

def phase_w1():
    global ORCH
    needle = f"NEEDLE-{SALT}"
    ORCH["orch-A"] = mk_prompt(252000, f"wA{SALT}",
                               extra=f"\n\n[needle] Remember this token: {needle}\n")
    tags = ["orch-A"]
    if DUAL_HEAD:
        ORCH["orch-B"] = mk_prompt(252000, f"wB{SALT}",
                                   extra=f"\n\n[needle] Remember this token: {needle}\n")
        tags = ["orch-A", "orch-B"]
    jobs = [(t, ORCH[t], 8) for t in tags]
    name = "W1_2x252k_boot_warm" if DUAL_HEAD else "W1_1x252k_boot_warm"
    run_group(name, jobs, tick_schedule=[(240, "tick-1"), (600, "tick-2")])


ORCH = {}

def phase_w2():
    jobs = [("tdd-1", mk_prompt(32000, f"t1{SALT}"), 8),
            ("tdd-2", mk_prompt(32000, f"t2{SALT}"), 8),
            ("coder-1", mk_prompt(64000, f"c1{SALT}"), 8),
            ("coder-2", mk_prompt(64000, f"c2{SALT}"), 8),
            ("audit-1", mk_prompt(64000, f"a1{SALT}"), 8),
            ("audit-2", mk_prompt(64000, f"a2{SALT}"), 8)]
    follows = [(150, "res-orch-A", ORCH["orch-A"], f"wA{SALT}")]
    if DUAL_HEAD:
        follows.append((240, "res-orch-B", ORCH["orch-B"], f"wB{SALT}"))
    run_group("W2_6workers_on_hot_orch", jobs, followups=follows)

def guard(name, fn):
    print(f"[warm8] {name} ...", flush=True)
    try:
        fn()
    except Exception as e:
        R["errors"].append(f"{name}: GUARD-CAUGHT {str(e)[:200]}")
        print(f"[warm8] {name} EXCEPTION: {e}", flush=True)
        save()

if advertised_ctx() < 262144:
    R["errors"].append("preflight advertised ctx < 262144")
    save()
    print("FAIL: advertised ctx < 262144 — not running the battery", flush=True)
    raise SystemExit(1)

for ph in PHASE_ARGS or ["W1", "W2"]:
    guard(ph, {"W1": phase_w1, "W2": phase_w2}[ph])

R["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
R["final_footprint"] = footprint()
R["final_df_free_gb"] = df_free_gb()
fails = evaluate_gates()
save()
print("WROTE", OUT, "| errors:", R["errors"] if R["errors"] else "none",
      "| gate_fails:", fails if fails else "none", flush=True)
if fails or R["errors"]:
    raise SystemExit(1)
