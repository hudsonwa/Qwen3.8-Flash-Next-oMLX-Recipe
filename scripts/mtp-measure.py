#!/usr/bin/env python3
"""Measure completion throughput for the MTP on/off receipt.

The server mode (mtp_enabled in ~/.omlx/model_settings.json) is toggled and
the server restarted by the operator around this script; this script only
measures. Run once with --label mtp-on and once with --label mtp-off; both
runs merge into one results/mtp_on_off.json receipt.

Solo run: one request at a time, N turns. Load run: C concurrent requests.
Each request uses a fixed long prompt (about 2K tokens) and asks for a short
completion, so the receipt reports *completion* tok/s plus whatever usage
fields oMLX reports (raw usage dict is kept verbatim; nothing is invented).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROMPT = (
    "Write a short technical note, exactly three sentences, about why SSD "
    "tiering helps a 100B-class MoE model fit a 128 GB Apple Silicon Mac. "
    "Do not repeat the phrase tiering more than twice."
)

TARGET = 128  # completion max_tokens


def resolve_model(base: str) -> str:
    """One model id everywhere: delegate to the canonical resolver (#23).

    OMLX_REQUIRE_LIVE=1 makes it fail closed (no silent fallback), so a
    receipt can never be labelled for a model the server did not advertise.
    """
    root = base.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]  # resolve_model.py appends /v1/models itself
    env = dict(os.environ, OMLX_BASE=root, OMLX_REQUIRE_LIVE="1")
    script = Path(__file__).resolve().parent / "resolve_model.py"
    p = subprocess.run([sys.executable, str(script)], capture_output=True,
                       text=True, timeout=15, env=env)
    if p.returncode != 0 or not p.stdout.strip():
        sys.exit("could not resolve model id from %s: %s"
                 % (base, (p.stderr or p.stdout).strip()[-200:]))
    return p.stdout.strip().splitlines()[-1]


def server_mode(model_id: str) -> dict:
    """Read-only snapshot of the actual server-side mode.

    The run label (mtp-on / mtp-off) is the operator's claim; this proves
    what the server was configured with at measurement time.
    """
    p = Path.home() / ".omlx" / "model_settings.json"
    try:
        d = json.loads(p.read_text())
        m = (d.get("models") or {}).get(model_id) or {}
        return {"file": str(p), "mtp_enabled": m.get("mtp_enabled"),
                "mtp_num_draft_tokens": m.get("mtp_num_draft_tokens"),
                "max_context_window": m.get("max_context_window")}
    except Exception as e:
        return {"file": str(p), "error": str(e)[:120]}


def one_request(base: str, model: str, max_tokens: int) -> dict:
    body = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=600) as r:
        resp = json.load(r)
    dt = time.monotonic() - t0
    usage = resp.get("usage", {}) or {}
    c_tokens = usage.get("completion_tokens", 0)
    return {
        "completion_tokens": c_tokens,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "seconds": round(dt, 3),
        "completion_tok_per_s": round(c_tokens / dt, 2) if dt > 0 else 0.0,
        "usage": usage,  # verbatim, including any MTP/speculation fields
        "finish_reason": resp.get("choices", [{}])[0].get("finish_reason"),
        "text": resp.get("choices", [{}])[0].get("message", {}).get("content", "")[:80],
    }


def measure(base: str, model: str, concurrency: int, turns: int, max_tokens: int) -> list[dict]:
    if concurrency == 1:
        return [one_request(base, model, max_tokens) for _ in range(turns)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(one_request, base, model, max_tokens) for _ in range(turns)]
        return [f.result() for f in futures]


def summarize(label: str, mode: str, recs: list[dict], model: str) -> dict:
    tps = [r["completion_tok_per_s"] for r in recs if r["completion_tok_per_s"] > 0]
    return {
        "mode": mode,
        "label": label,
        "server_mode": server_mode(model),  # actual config at measure time
        "requests": len(recs),
        "mean_tok_per_s": round(statistics.mean(tps), 2) if tps else 0.0,
        "median_tok_per_s": round(statistics.median(tps), 2) if tps else 0.0,
        "p95_tok_per_s": round(sorted(tps)[int(len(tps) * 0.95) - 1], 2) if tps else 0.0,
        "mean_completion_tokens": round(statistics.mean(r["completion_tokens"] for r in recs), 1),
        "mean_seconds": round(statistics.mean(r["seconds"] for r in recs), 3),
        "notes": "server mode snapshotted read-only from ~/.omlx/model_settings.json; "
        "completion tok/s and verbatim usage dicts; no cache-hit numbers are invented.",
        "raw": recs,
    }


def machine_info() -> dict:
    """Provenance stamp: every number in results/ is M5 Max / macOS 26 /
    2026-08-31 (the README Machine contract) unless re-run, so a re-run's
    receipt must name the machine, OS and date it was actually measured on."""
    import platform
    import subprocess
    out: dict = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for cmd, key in ((["sysctl", "-n", "hw.model"], "hw_model"),
                     (["sysctl", "-n", "machdep.cpu.brand_string"], "cpu"),
                     (["sw_vers", "-productVersion"], "os_version")):
        try:
            out[key] = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=5).stdout.strip()
        except Exception:
            out[key] = None
    out["os"] = "%s %s" % (platform.system(), platform.release())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--label", required=True, choices=["mtp-on", "mtp-off"])
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=TARGET)
    ap.add_argument("--out", default="results/mtp_on_off.json")
    args = ap.parse_args()

    model = resolve_model(args.base)
    print(f"model={model} label={args.label} concurrency={args.concurrency}", flush=True)
    recs = measure(args.base, model, args.concurrency, args.turns, args.max_tokens)
    key = f"{args.label}-conc{args.concurrency}"
    entry = summarize(args.label, f"concurrency={args.concurrency}", recs, model)
    entry["model"] = model

    out = Path(args.out)
    if out.exists():
        receipt = json.loads(out.read_text())
    else:
        receipt = {"recipe": "mtp on/off receipt", "model": model, "runs": {}}
    receipt.setdefault("machine", machine_info())  # self-tag: which box/OS/date
    receipt["runs"][key] = entry
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"wrote {out} ({key})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
