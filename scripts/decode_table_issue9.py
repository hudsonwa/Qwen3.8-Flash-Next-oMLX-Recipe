#!/usr/bin/env python3
"""Issue 9 / GitHub #86 decode table.

Warm prefix, stream, completion 128/512/2048, concurrency 1/4/8,
MTP off vs on. Discard MTP batch 1. N>=3 after warmup. temp 0,
thinking off via chat_template_kwargs.

Writes results/decode_table.json (Issue 9). Does not write
mtp_on_off.json or the #64 archive.

Soft 96.8 GB current or peak during MTP-on: abort that arm, restore
serving (hot=0, mc=8, MTP off, chunked on), verify.sh.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_stamp import hf_revision, machine_stamp  # noqa: E402
from resolve_model import resolve  # noqa: E402

BASE = os.environ.get("OMLX_BASE", "http://127.0.0.1:8000/v1")
SOFT_GB = 96.8
PLAN_GB = 102.0
LENGTHS = (128, 512, 2048)
CONCS = (1, 4, 8)
OUT = ROOT / "results" / "decode_table.json"
PARTIAL = ROOT / "results" / "decode_table_issue9.partial.json"
PROMPT_PATH = ROOT / "prompts" / "decode_fill.txt"
PROTECTED = (
    ROOT / "results" / "mtp_on_off.json",
    ROOT / "results" / "decode_table_issue64.json",
    ROOT / "results" / "warm_8slot_results.json",
    ROOT / "results" / "quality_canary.json",
)


def parse_gb_line(line: str, peak: bool):
    """Parse /usr/bin/footprint lines. Never treat MB as GB."""
    key = "phys_footprint_peak" if peak else "phys_footprint:"
    if key not in line:
        return None
    if (not peak) and "peak" in line:
        return None
    m = re.search(r"([0-9.]+)\s*([KMGTPE]i?B?)?", line.split(":", 1)[-1].strip(), re.I)
    if not m:
        return None
    n = float(m.group(1))
    u = (m.group(2) or "GB").upper()
    if u.startswith("K"):
        n = n / 1e6
    elif u.startswith("M"):
        n = n / 1e3
    elif u.startswith("T"):
        n = n * 1e3
    elif u.startswith("G") or u.endswith("B") and n < 10000:
        pass
    if n > 200:
        return None
    return n


def listen_pid():
    out = subprocess.run(
        ["lsof", "-tnP", "-iTCP:8000", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    ).stdout.strip()
    return out.split()[0] if out else None


def footprint_now():
    pid = listen_pid()
    if not pid:
        return {"pid": None, "current_gb": None, "peak_gb": None}
    res = subprocess.run(
        ["/usr/bin/footprint", pid],
        capture_output=True, text=True, timeout=60,
    ).stdout
    current = peak = None
    for line in res.splitlines():
        if "phys_footprint_peak" in line:
            peak = parse_gb_line(line, True)
        elif "phys_footprint:" in line and "peak" not in line:
            current = parse_gb_line(line, False)
    return {"pid": pid, "current_gb": current, "peak_gb": peak}


def stream(base: str, model: str, prompt: str, max_tokens: int) -> dict:
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    url = base.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    first = None
    usage = {}
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
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
        return {"error": str(e)[:240], "wall_s": round(time.perf_counter() - t0, 4)}
    wall = time.perf_counter() - t0
    pt = int(usage.get("prompt_tokens") or 0)
    ct = int(usage.get("completion_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    ttft = first
    remain = (wall - ttft) if ttft is not None else None
    gen = ((ct - 1) / remain) if remain and remain > 0 and ct > 1 else None
    blended = (ct / wall) if wall and wall > 0 and ct > 0 else None
    return {
        "ttft_s": round(ttft, 4) if ttft is not None else None,
        "wall_s": round(wall, 4),
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "generation_tok_s": round(gen, 2) if gen else None,
        "blended_tok_s": round(blended, 2) if blended else None,
        "cached_tokens": int(cached) if cached is not None else None,
        "error": None,
    }


def load_prefix() -> str:
    return PROMPT_PATH.read_text().rstrip()


def batch(base, model, prefix, conc, max_tokens, salt):
    box = [None] * conc

    def fire(i):
        prompt = prefix + "\n\n[variant %s-%d]\n" % (salt, i)
        box[i] = stream(base, model, prompt, max_tokens)

    t0 = time.perf_counter()
    th = [threading.Thread(target=fire, args=(k,)) for k in range(conc)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    return round(time.perf_counter() - t0, 4), box


def wait_up(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=3).read()
            fp = footprint_now()
            gb = fp.get("current_gb")
            if gb is not None and gb >= 60:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def restart():
    subprocess.run("kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)", shell=True)
    time.sleep(3)
    if not wait_up():
        raise SystemExit("FAIL: server did not return after port-only restart")


def apply_mode(mode: str):
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "omlx-config.py"),
         "--mode", mode, "--apply"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise SystemExit("FAIL omlx-config %s" % mode)


def verify_expect(expect: str) -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_activation.py"),
         "--expect", expect],
        cwd=str(ROOT),
    ).returncode


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def dump(receipt: dict, path: Path):
    from receipt_guard import refuse_overwrite
    force = os.environ.get("RECEIPT_FORCE_REPLACE") == "1"
    refuse_overwrite(path, force_replace=force)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, indent=2) + "\n")
    tmp.replace(path)


def stamp_receipt(data: dict, n: int) -> None:
    ms = machine_stamp()
    data["machine"] = ms
    raw = str(ms.get("omlx") or "")
    m = re.search(r"\d+\.\d+\.\d+", raw)
    data["omlx"] = m.group(0) if m else raw or None
    data["hf_revision"] = hf_revision()
    data["n"] = n
    data["temperature"] = 0
    data["thinking"] = False
    data["hot_cache_max_size"] = "0"
    data["metrics"] = {
        "ttft_s": "seconds to first streamed token",
        "generation_tok_s": "(completion_tokens - 1) / (wall_s - TTFT_s)",
        "blended_tok_s": "completion_tokens / wall_s",
        "peak_gb": "/usr/bin/footprint phys_footprint_peak",
        "cache": "warm frozen prefix; [variant salt] on the tail only",
    }


def cell_fails(cell, max_tokens):
    fails = []
    kept = [r for r in cell.get("runs") or [] if not r.get("warmup") and not r.get("discarded")]
    if len(kept) < 3:
        fails.append("mtp=%s len=%s conc=%s kept %s < 3" % (
            cell.get("mtp"), max_tokens, cell.get("concurrency"), len(kept)))
    for r in kept:
        for j in r.get("jobs") or []:
            if not j:
                fails.append("empty job")
                continue
            if j.get("error"):
                fails.append(str(j["error"])[:120])
            if not j.get("generation_tok_s"):
                fails.append("missing generation_tok_s")
            if not j.get("ttft_s"):
                fails.append("missing ttft_s")
            ct = j.get("completion_tokens") or 0
            if ct < 32:
                fails.append("completion_tokens %s < 32" % ct)
    return fails


def measure_arm(receipt, mtp_on, model, prefix, n, discard_first, abort_flag):
    label = "mtp_on" if mtp_on else "mtp_off"
    first_batch = True
    for max_tokens in LENGTHS:
        if abort_flag["abort"]:
            break
        for conc in CONCS:
            if abort_flag["abort"]:
                break
            extra = 1 if (mtp_on and discard_first and first_batch) else 0
            total = extra + 1 + n  # optional MTP batch1 + warmup + n
            runs = []
            for i in range(total):
                salt = "%s-%s-%s-%s" % (label, max_tokens, conc, i)
                wall, jobs = batch(BASE, model, prefix, conc, max_tokens, salt)
                fp = footprint_now()
                discarded = bool(mtp_on and extra and i == 0)
                warmup = (not discarded) and (i == extra)
                rec = {
                    "batch_wall_s": wall,
                    "jobs": jobs,
                    "warmup": warmup,
                    "discarded": discarded,
                    "mtp_batch1": discarded,
                    "peak_gb": fp.get("peak_gb"),
                    "current_gb": fp.get("current_gb"),
                }
                runs.append(rec)
                kind = "mtp_batch1" if discarded else ("warmup" if warmup else "kept")
                gens = [j.get("generation_tok_s") for j in jobs if j and j.get("generation_tok_s")]
                print("[%s mt=%s c=%s i=%s %s] batch_wall=%s gen_mean=%s peak=%s current=%s" % (
                    label, max_tokens, conc, i, kind, wall,
                    round(statistics.mean(gens), 2) if gens else None,
                    fp.get("peak_gb"), fp.get("current_gb")), flush=True)
                if mtp_on:
                    cur = fp.get("current_gb") or 0
                    pk = fp.get("peak_gb") or 0
                    if cur > SOFT_GB or pk > SOFT_GB:
                        abort_flag["abort"] = True
                        abort_flag["reason"] = "soft 96.8 fail current=%s peak=%s" % (cur, pk)
                        print("ABORT MTP-on:", abort_flag["reason"], flush=True)
                        break
            first_batch = False
            kept = [r for r in runs if not r.get("warmup") and not r.get("discarded")]
            jobs_kept = [j for r in kept for j in (r.get("jobs") or []) if j]
            cell = {
                "mtp": mtp_on,
                "max_tokens": max_tokens,
                "concurrency": conc,
                "warmup_discarded": 1,
                "mtp_batch1_discarded": extra,
                "n": len(kept),
                "ttft_s_mean": mean([j.get("ttft_s") for j in jobs_kept]),
                "generation_tok_s_mean": mean([j.get("generation_tok_s") for j in jobs_kept]),
                "blended_tok_s_mean": mean([j.get("blended_tok_s") for j in jobs_kept]),
                "peak_gb": max([r.get("peak_gb") or 0 for r in runs] or [0]),
                "prompt_tokens": [j.get("prompt_tokens") for j in jobs_kept],
                "completion_tokens": [j.get("completion_tokens") for j in jobs_kept],
                "runs": runs,
            }
            receipt["cells"].append(cell)
            receipt["fails"].extend(cell_fails(cell, max_tokens))
            finalize_lists(receipt)
            dump(receipt, PARTIAL)
            dump(receipt, OUT)
            if abort_flag["abort"]:
                break


def finalize_lists(receipt):
    pts = []
    peaks = []
    for cell in receipt.get("cells") or []:
        pts.extend([p for p in (cell.get("prompt_tokens") or []) if p])
        if cell.get("peak_gb"):
            peaks.append(cell["peak_gb"])
        for r in cell.get("runs") or []:
            if r.get("peak_gb"):
                peaks.append(r["peak_gb"])
    receipt["prompt_tokens"] = pts
    receipt["peak_gb"] = max(peaks) if peaks else None
    receipt["pass"] = not receipt.get("fails")


def restore_serving(fails):
    print("restore serving hot=0 mc=8 MTP off chunked on", flush=True)
    try:
        apply_mode("serving")
        restart()
    except Exception as e:
        fails.append("restore apply/restart: %s" % e)
        return
    if verify_expect("serving") != 0:
        fails.append("verify_activation serving failed after restore")
    vsh = subprocess.run(["bash", str(ROOT / "scripts" / "verify.sh")], cwd=str(ROOT))
    if vsh.returncode != 0:
        fails.append("verify.sh failed after restore")


def main() -> int:
    for p in PROTECTED:
        if not p.exists():
            print("note: protected file missing (ok if not this tree):", p, flush=True)
    os.environ["OMLX_REQUIRE_LIVE"] = "1"
    os.environ["OMLX_BASE"] = BASE
    prefix = load_prefix()
    n = 3
    receipt = {
        "recipe": "decode table issue 9",
        "protocol": "issue-9",
        "issue": 86,
        "archive_of_issue64": "results/decode_table_issue64.json",
        "cells": [],
        "fails": [],
        "mtp_on_aborted": False,
        "profile": "serving-vs-interactive",
    }
    stamp_receipt(receipt, n)
    abort_flag = {"abort": False, "reason": None}
    restored = False
    try:
        idle = footprint_now()
        receipt["idle_footprint"] = idle
        print("idle footprint", idle, flush=True)
        if (idle.get("current_gb") or 0) > SOFT_GB:
            receipt["fails"].append("idle current_gb %s > 96.8 — refuse start" % idle.get("current_gb"))
            receipt["pass"] = False
            dump(receipt, OUT)
            return 1
        cur = idle.get("current_gb") or 0
        pk = idle.get("peak_gb") or 0
        if not (60.0 <= cur <= 80.0) or pk >= SOFT_GB:
            print("reset peak via port-only restart", flush=True)
            restart()
            idle = footprint_now()
            receipt["idle_footprint_after_restart"] = idle
            print("after restart", idle, flush=True)
        else:
            print("skip idle restart (current in 60-80, peak < 96.8)", flush=True)

        model = resolve()
        receipt["model"] = model

        if verify_expect("serving") != 0:
            receipt["fails"].append("preflight verify_activation serving failed")

        measure_arm(receipt, False, model, prefix, n, False, abort_flag)

        apply_mode("interactive")
        restart()
        va = verify_expect("interactive")
        if va != 0:
            receipt["fails"].append("verify_activation interactive failed")
            abort_flag["abort"] = True
            abort_flag["reason"] = "interactive activation failed"
            receipt["mtp_on_aborted"] = True
        else:
            pg = footprint_now()
            if (pg.get("current_gb") or 0) > SOFT_GB or (pg.get("peak_gb") or 0) > SOFT_GB:
                abort_flag["abort"] = True
                abort_flag["reason"] = "soft 96.8 at MTP-on boot current=%s peak=%s" % (
                    pg.get("current_gb"), pg.get("peak_gb"))
                receipt["mtp_on_aborted"] = True
                receipt["fails"].append(abort_flag["reason"])
            else:
                measure_arm(receipt, True, model, prefix, n, True, abort_flag)
                if abort_flag["abort"]:
                    receipt["mtp_on_aborted"] = True
                    receipt["fails"].append(abort_flag["reason"] or "MTP-on aborted")

        restore_serving(receipt["fails"])
        restored = True
        receipt["restored_serving"] = True
        receipt["restore_footprint"] = footprint_now()
    except Exception:
        receipt["fails"].append("exception: %s" % traceback.format_exc()[-500:])
        if not restored:
            try:
                restore_serving(receipt["fails"])
                receipt["restored_serving"] = True
            except Exception as e:
                receipt["fails"].append("restore after exception: %s" % e)
    finalize_lists(receipt)
    receipt["pass"] = not receipt.get("fails")
    dump(receipt, OUT)
    if PARTIAL.exists():
        PARTIAL.unlink()
    print("WROTE", OUT, "pass", receipt["pass"], "fails", receipt["fails"] or "none",
          "cells", len(receipt.get("cells") or []), flush=True)
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
