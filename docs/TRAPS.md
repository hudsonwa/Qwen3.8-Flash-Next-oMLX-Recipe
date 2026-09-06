# TRAPS — every way this stack has actually failed

Each trap below was hit and measured on the reference machine (oMLX 0.6.4 unless
stated). Not folklore.

1. **`chunked_prefill` defaults to off — silently gives you a staircase.** With
   `prefill_priority: "context"` and chunking off, simultaneous long prefills run one
   after another: measured 4×118K walls 304/1225/1240/1243 s (spread 939 s). With
   chunking on: spread 25.6 s. No error, no warning — just serial prefill at full
   price. Check `~/.omlx/settings.json` → `scheduler.chunked_prefill: true`.

2. **Per-model `max_context_window` may silently not apply.** Settings said 131072
   for a model; `/v1/models` advertised 262144 anyway. After every boot, verify the
   advertised value (`scripts/verify.sh` does). Trust the API, not the settings file.

3. **MTP on this checkpoint, this box — leave it off.**
   Keep **both** numbers; they are different experiments:
   - **Upstream oMLX 0.6.4 notes** claim Lightning MTP speedups on this family
     (batch-one Flash-Next TG; warm-prefix MTP sidecar restore; isolated MTP
     patches). Source: https://github.com/jundot/omlx/releases/tag/v0.6.4
   - **This box, 8-way short-load:** `results/mtp_on_off.json` n=3, `n_jobs=8`.
     Off batch walls 6.92 / 5.53 / 5.54 s (mean 6.00 s, peak 72 GB). On:
     27.16 / 5.65 / 5.68 s (mean 12.83 s, peak 73 GB). First MTP batch ~27 s.
     Short-load did not win.
   - **This box, solo anecdote (not that JSON):** ~60.9 tok/s MTP on vs ~86 off
     ([PROVENANCE.md](PROVENANCE.md)). Do not delete either figure.
   Likely deltas vs upstream: context length (their 4K–32K vs our 33-token
   jobs), 8-way vs batch-one, 0.6.4 MTP state isolation across engines, this
   oQ4e quant. Filename `-mtp` ≠ on. Decode table: [results/README.md](../results/README.md).

4. **Killing the `omlx serve` wrapper does not stop the server.** The wrapper spawns
   a child `omlx-server` that survives. Stop by port:
   `kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)`.

5. **Port conflict kills the NEW instance, the OLD one keeps serving.** If you
   relaunch with different flags while an old server holds the port, the newcomer
   dies and the old flags stay live. Check `lsof -nP -iTCP:<port> -sTCP:LISTEN`
   before any relaunch.

6. **The GUI binary (`oMLX.app/Contents/MacOS/oMLX`) hangs headless.** Always drive
   the server through the CLI shim (`~/.omlx/bin/omlx`), which execs the bundled
   `omlx-cli`.

7. **In-place app upgrade over `/Applications/oMLX.app` is TCC-blocked** from a
   terminal ("Operation not permitted") and can leave a broken mixed bundle. Install
   new versions into `~/Applications/oMLX.app` and repoint the shim's exec line.

8. **RSS lies about memory.** MLX mmaps weights and pools buffers: `ps` RSS read
   ~21 GB while the real `phys_footprint` was ~69 GB. Always
   `/usr/bin/footprint <pid>`.

9. **The budget line is the Metal working-set cap (107.5 GB), not 128 GB RAM.** The
   enforcer log even says it: Metal cap (107.5GB) is below oMLX's static ceiling;
   `iogpu.wired_limit_mb` unset keeps Apple's default. Host RAM and swap are red
   herrings; Metal OOM is the allocator you have to please.

10. **Unsalted repeated prompts poison benchmarks.** The prefix cache turns an
    identical 11K filler from 12.1 s cold into 3.4 s on the "hit". Append a unique
    `[variant <tag>]` to every repeated filler and discard unsalted repeat runs.

11. **Do not dual cold-fill while the fleet is resident.** Default warm path is
    one 252K head (`scripts/warm-8slot.py`). `--dual-head` is gated.
    `scripts/guard_dual_cold.py` no longer uses a static 74 GB cutoff (steady
    73 GB sat under 74 and would have admitted a second 252K). Projected peak:
    `now + pending_252k * 9.25 + one_head_fill_spike` (spike = 88 − 69 = 19 GB)
    vs plan **102 GB** / soft **96.8 GB**. Refuse dual when projected > 102, or
    now ≥ 96.8, or now ≥ 73 (fleet already holding a 252K). Must-fail: 73 GB +
    second 252K. Must-pass: idle ~69 GB + one 252K. Constants and cases:
    `results/guard_projection.json` (projection-only; no tok/s). Historical
    dual-from-empty peaks: W1 98 GB / G1 102 GB.

12. **The SSD cache grows to its cap by design — that's fine, disk is not the
    problem.** `ssd_cache_max_size: "auto"` resolved to a self-managed 185.8 GB LRU;
    eviction is native. Disk vs RAM vs miss: [PROFILE.md](PROFILE.md). Two 252K prefixes
    may not both stay cached. Keep ~100 GB free. Don't hand-prune cache files
    while the server runs.

13. **Model discovery follows symlinks in the model dir.** That's the feature the
    quarantine dir uses (`~/models/omlx-qwen38/<one-symlink>`), but it also means a
    stray extra symlink in that dir silently adds a second loadable model.

14. **Do not port ANE / 6-bit / 256 GB single-stream draft stacks onto this
    128 GB 8-slot shape.** Different memory regime. One green decode number that
    OOMs the dual-~240k layout is a regression. If you enable MTP, measure peak
    phys_footprint against 102 / 107.5 GB first.

15. **Never raise `iogpu.wired_limit_mb` as the fix.** The budget is the Metal
    107.5 GB cap this recipe already plans against. Raising the kernel limit is
    not a serving-profile success.

16. **Short ticks during a dual 252K fill are not ~1 s.** G1 `tick-1` was
    **24.91 s** (`results/omlx_flash_2way_results.json`), then 1.34 s / 1.31 s.
    Cite 24.91 s when talking about a tick on top of a dual cold fill.

17. **Daily hot cache is off (`hot_cache_max_size: "0"`).** Optional `--hot-cache-max-size 12GB`
    is one-head RAM residency, not a second orchestrator. Cite [PROFILE.md](PROFILE.md).
    `10%` is not a valid size. Launchd daily argv omits the flag (hot=0).


