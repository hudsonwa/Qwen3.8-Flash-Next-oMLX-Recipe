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

3. **MTP on this checkpoint is slower, not faster.** `mtp_enabled: true` measured
   60.9 tok/s solo vs ~86 off. It stays off in every config here; re-benchmark on
   your own build before flipping it.

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

11. **A 90 s stagger does NOT save a dual cold-fill from memory pressure** (measured
    on the previous engine; the physics is the same here). Two simultaneous ~10 GB
    fill transients on top of a resident stack can cross the cap. Boot-warm both
    orchestrators from empty — that's safe (98 GB peak, 3/3 clean) — then never
    cold-fill both while the fleet is resident.

12. **The SSD cache grows to its cap by design — that's fine, disk is not the
    problem.** `ssd_cache_max_size: "auto"` resolved to a self-managed 185.8 GB LRU;
    eviction is native. Don't hand-prune cache files while the server runs.

13. **Model discovery follows symlinks in the model dir.** That's the feature the
    quarantine dir uses (`~/models/omlx-qwen38/<one-symlink>`), but it also means a
    stray extra symlink in that dir silently adds a second loadable model.
