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

5. **Boot-warm one 252K head; never dual cold-fill once the fleet is resident.**
   Default warm path is **1×252K role + short slots**. Dual-head is gated off
   (`python3 scripts/warm-8slot.py --dual-head` only). Do not revert this.
   Plan to 102 GB against the 107.5 GB Metal cap. Soft 96.8 GB is a fail.
   Numbers: [docs/PROFILE.md](docs/PROFILE.md). Optional 12 GB hot KV is one-head
   RAM residency, not a second orchestrator. Daily hot-cache remains **0**.

6. **Process management:** `omlx serve` spawns a child server; killing the wrapper
   does nothing. Stop via port: `kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)`.
   Check the port is free before any relaunch — on conflict the NEW instance dies
   and the OLD one keeps serving with whatever flags it was started with.

7. **Do not enable MTP** (`mtp_enabled: true`) on this box / this checkpoint.
   Keep both numbers: solo anecdote ~60.9 vs ~86, and `results/mtp_on_off.json`
   8-way short-load (did not win). Upstream 0.6.4 notes claim Lightning MTP
   speedups on batch-one — see docs/TRAPS.md #3. Leave MTP off.

8. **Fail closed.** If `scripts/verify.sh` reports a miss, stop and fix — do not
   declare success with degraded settings. A stack serving 131072-ctx instead of
   262144 will pass casual checks and fail real workloads hours later.

9. **Commit identity.** If you commit to this repo, use the owning GitHub login
   and the ID-prefixed `users.noreply.github.com` address (the form with a
   numeric id, a plus sign, and the login). Never use
   `login@users.noreply.github.com` without the numeric id — GitHub will
   attribute those commits to whoever squatted that login. CI must use
   `GITHUB_TOKEN` / `github-actions[bot]`, not a personal token.

10. **Public-safe.** No personal email, no `/Users/<name>` paths, no machine
    hostnames, no API keys in `results/` or logs. Run `bash scripts/check-scrub.sh`
    before every push.

