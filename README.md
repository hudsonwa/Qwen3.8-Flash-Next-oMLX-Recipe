# Qwen3.8 Flash-Next on a 128 GB Mac — oMLX single-server, 8-slot recipe

**One oMLX 0.6.4 process, one Flash-Next (125B-A6B MoE) checkpoint, eight concurrent
context slots: 2 orchestrators at 252K + 2 TDD at 32K + 2 coders at 64K + 2 auditors
at 64K. True concurrency is measured, not assumed: simultaneous long prefills finish
with near-equal walls (spread 4.7 s on dual 252K), planner ticks answer in ~1 s
mid-fill, and the whole stack lives under the 107.5 GB Metal working-set cap with an
adaptive memory enforcer and automatic SSD tiering.**

Every number in this repo was measured on the reference machine (128 GB unified,
M5 Max-class, macOS 26) with oMLX 0.6.4. Nothing is extrapolated. Re-measure on your
own hardware before trusting any figure here; the acceptance battery is included
(`scripts/warm-8slot.py`).

Why a single oMLX process and not two mlx-serve servers: measured head-to-head on the
same machine, two simultaneous 252K prefills took 1,084 s wall on mlx-serve (two serial
FIFO prefills, spread 563 s) versus 542 s on oMLX with `chunked_prefill: true`
(spread 2.8 s). The full engine-comparison history is in [docs/BATTERY.md](docs/BATTERY.md).

---

## Quick start

```bash
git clone <this repo>
cd Qwen3.8-Flash-Next-27B-MLX-Serve-MBP-128GB
bash setup.sh                    # fail-closed checks; renders config + launchd plist
bash scripts/serve-flash.sh      # manual launch (or use the launchd plist)
bash scripts/verify.sh           # ctx, footprint, live generation — fail-closed
python3 scripts/warm-8slot.py    # optional: acceptance battery (~13 min) + boot-warm
```

An AI agent doing this install should read [AGENT.md](AGENT.md) first.
Model/binary sources: [MODELS.md](MODELS.md). All measured traps: [docs/TRAPS.md](docs/TRAPS.md).

## The one config that matters: `chunked_prefill`

oMLX's default scheduler (`prefill_priority: "context"`, chunking off) finishes one
long prefill completely before starting the next — a staircase. Measured, four
simultaneous 118K fills:

- chunked **off**: per-stream walls 304 / 1225 / 1240 / 1243 s — spread **939 s**
- chunked **on**: walls 1241–1267 s — spread **25.6 s**, every stream TTFT ~4 s

In `~/.omlx/settings.json`:

```json
"memory":   { "prefill_memory_guard": true, "memory_guard_tier": "balanced",
              "soft_threshold": 0.85, "hard_threshold": 0.95 },
"scheduler":{ "max_concurrent_requests": 8, "chunked_prefill": true,
              "prefill_priority": "context", "decode_fairness": true },
"server":   { "burst_decode_mode": "balanced" }
```

Per-model (`~/.omlx/model_settings.json`): `mtp_enabled: false`,
`max_context_window: 262144`, `qwen4_ple_ssd_offload: true` for the flash checkpoint.

`setup.sh` validates both files and can write them for you.

## Launch

**Manual:**

```bash
~/.omlx/bin/omlx serve --model-dir ~/models/omlx-qwen38 --host 127.0.0.1 --port 8000 \
  --max-concurrent-requests 8 --paged-ssd-cache-dir ~/.omlx/ssd-cache
```

**At boot (launchd, renders from `scripts/com.omlx.flash8slot.plist.in`):**
`setup.sh` writes the plist with your `$HOME` and prints the two commands:
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.omlx.flash8slot.plist`
to start now / at next login, and
`launchctl bootout gui/$(id -u)/com.omlx.flash8slot` to stop it
(`KeepAlive` is on — the plist is the owner; don't also launch manually, the port
conflict kills the newcomer).

Bind to 127.0.0.1 (default). If you expose the API beyond localhost, set an API key in
`~/.omlx/settings.json` → `auth.api_key` first.

## Memory budget (phys_footprint, never `ps` RSS)

| State | Footprint | Note |
|---|---|---|
| Booted, idle (weights paged in) | ~69 GB | flash oQ4e checkpoint |
| Peak during dual 252K cold fill | **98 GB** (measured) | enforcer cycles soft, never hard |
| Steady, all 8 slots resident | **73 GB** (measured) | orchestrator KV auto-tiers to SSD |
| Static worst case (nothing tiered) | ~97–99 GB | 69 + 2×9.25 + 2×1.2 + 4×2.3 GB |

**Budget line is the 107.5 GB Metal working-set cap, not 128 GB RAM.** The enforcer
(soft 96.8 / hard 102.1 / ceiling 107.5 GB, adapts live) throttles prefill chunks,
reclaims pooled buffers, and moves cold KV to the SSD page cache before anything OOMs.
Slot rate: ~9.25 GB per 252K slot, ~1.2 GB per 32K, ~2.3 GB per 64K.

**SSD tier:** `~/.omlx/ssd-cache` with max size `auto` resolved to a self-managed
185.8 GB LRU on the reference machine. Warm orchestrator prefixes survive restarts
there: re-promoting a 252K prefix from SSD measured **8.7 s** vs 229 s full re-prefill
on an LRU miss. Keep ~100 GB free on the cache volume.

## Operating rules (all measured)

1. **Boot-warm both orchestrators together — that's safe** (98 GB peak from empty,
   3/3 clean). The rule is about *later*: **never cold-fill both 252K orchestrators
   while the fleet is resident** — two fill spikes on top of steady state can cross
   the cap and cost you SSD evictions of hot slots.
2. **Verify the advertised context after every boot** (`scripts/verify.sh` does it):
   per-model `max_context_window` is not always honored — the engine may advertise
   262144 regardless. Trust `/v1/models`, not the settings file.
3. **Salt every repeated benchmark prompt** (`[variant <tag>]` suffix): identical
   fillers hit the prefix cache and wall-times collapse (12.1 s → 3.4 s measured).
4. Read memory with `/usr/bin/footprint <pid>`, never RSS — mmap'd weights lie.
5. Stop by port, not by the wrapper process: `kill -TERM $(lsof -tnP -iTCP:8000
   -sTCP:LISTEN)` — `omlx serve` spawns a child that survives the wrapper.

## Concurrency (measured)

- **Dual 252K cold fill**: walls 483.6 / 488.4 s, spread **4.73 s**; ~985 tok/s
  aggregate (94% of the 1,050 tok/s solo rate); planner ticks mid-fill **1.1–11.3 s**.
- **Six workers over hot orchestrators** (2×32K, 2×64K, 2×64K): pair spreads
  auditors **0.2 s**, coders **2.5 s**, TDD **8.9 s**; TTFT 0.05–0.66 s;
  ~1,017 tok/s aggregate across six simultaneous fills.
- Previous engine, same machine: dual 252K serial 1,084 s; a tick mid-fill waited
  553 s in FIFO.

## Verify (after every boot)

1. `/v1/models` advertises `max_model_len: 262144`.
2. Boot log shows the enforcer: `Process memory enforcer started (ceiling=107.5GB)`.
3. `footprint <pid>`: ~69 GB idle.
4. One live generation, then `scripts/warm-8slot.py W1` if you want the full receipt.

## Traps and scaling limits

All measured traps live in [docs/TRAPS.md](docs/TRAPS.md) — including the GUI binary
hanging headless (always use the CLI shim), the TCC-blocked in-place app upgrade, and
the port-conflict kill. Measured NOs:

| Attempt | Result |
|---|---|
| MTP speculative decode on this checkpoint | 60.9 tok/s solo vs ~86 with it off — **leave off**; unmeasured at 8-way |
| Second flash instance (2× weights) | Impossible: 2×69 GB weights alone exceed the chip |
| mlx-serve / llama.cpp for long-prefill concurrency | FIFO staircase measured on both — oMLX chunked is the fix |

## Results

Raw measurement JSON from the reference machine: [results/](results/) —
`warm_8slot_results.json` (the 8-slot acceptance battery), plus the earlier dual-252K
and 4×118K batteries. Methodology and the wall-equality verdict standard:
[docs/BATTERY.md](docs/BATTERY.md).

## Credits

- oMLX (jundot) — the serving runtime; `chunked_prefill` is the whole ballgame.
- Qwen team — the Flash-Next checkpoint.
- Recipe format inspired by MiaAI-Lab's per-config deployment recipes and
  tonyd2wild's cookbook/setup.sh/AGENT.md pattern.

## License

MIT — see [LICENSE](LICENSE).
