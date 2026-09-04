# AGENT.md — for AI agents performing this install

You are installing an 8-slot oMLX serving stack on a 128 GB Apple Silicon Mac.
Read this top to bottom before touching anything.

1. **Trust only measured state.** After every config change, re-verify: `/v1/models`
   advertised `max_model_len`, the boot log's enforcer line, `footprint <pid>` for
   memory. Per-model settings are not always honored (a `max_context_window` cap can
   silently fail to apply); the advertised value is ground truth.

2. **The concurrency verdict standard is wall equality.** "The server didn't crash"
   is not true concurrency. Fire N long fills simultaneously, record per-stream
   walls, and require small spread (≤ ~5 s per equal-size pair). `scripts/warm-8slot.py`
   implements this and writes a JSON receipt. Never report a pass without the receipt.

3. **Salt every repeated prompt.** Append a unique `[variant <tag>]` to fillers.
   oMLX's prefix cache turns identical repeats into cache hits and collapses your
   wall-times (12.1 s → 3.4 s measured on an 11K filler). Unsalted repeat
   measurements are contaminated — discard them.

4. **Memory: use `/usr/bin/footprint <pid>`.** RSS reads ~21 GB while the real
   footprint is ~69 GB (mmap'd weights, pooled buffers). Budget against the 107.5 GB
   Metal working-set cap — `sysctl iogpu.wired_limit_mb` unset means Apple's default
   cap is active; host RAM and swap are red herrings.

5. **Boot-warm both 252K orchestrators together; never cold-fill both once the fleet
   is resident.** From empty, dual fill peaked at 98 GB (W1) and 102 GB (G1) —
   plan to 102 GB. On top of a
   resident stack, two fill transients can cross the cap and trigger SSD evictions
   of hot slots. Stagger big refills. One D2 pair: 8.7 s SSD hit vs ~229 s miss;
   two 252K prefixes may not both stay in the LRU.

6. **Process management:** `omlx serve` spawns a child server; killing the wrapper
   does nothing. Stop via port: `kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)`.
   Check the port is free before any relaunch — on conflict the NEW instance dies
   and the OLD one keeps serving with whatever flags it was started with.

7. **Do not enable MTP** (`mtp_enabled: true`) without re-benchmarking **this
   box / this checkpoint**: measured 60.9 tok/s solo with it on vs ~86 off.
   Unmeasured under load until `results/mtp_on_off.json`. It is off in every
   config file in this repo on purpose.

8. **Fail closed.** If `scripts/verify.sh` reports a miss, stop and fix — do not
   declare success with degraded settings. A stack serving 131072-ctx instead of
   262144 will pass casual checks and fail real workloads hours later.
