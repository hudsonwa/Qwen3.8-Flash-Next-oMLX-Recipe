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

3. **MTP on this checkpoint, this box, is slower solo — not a general law.**
   `mtp_enabled: true` measured 60.9 tok/s solo vs ~86 off. Unmeasured at 8-way
   until `results/mtp_on_off.json` exists. It stays off in every config here.

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
    one 252K head (`scripts/warm-8slot.py`). `--dual-head` is gated;
    `scripts/guard_dual_cold.py` exits 1 when `phys_footprint` current ≥ 74 GB.
    A 90 s stagger does not save a dual cold-fill (two ~10 GB transients on a
    resident stack). Historical dual-from-empty peaks: W1 98 GB / G1 102 GB.

12. **The SSD cache grows to its cap by design — that's fine, disk is not the
    problem.** `ssd_cache_max_size: "auto"` resolved to a self-managed 185.8 GB LRU;
    eviction is native. One D2 pair: 8.7 s hit vs ~229 s miss; two 252K prefixes
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


