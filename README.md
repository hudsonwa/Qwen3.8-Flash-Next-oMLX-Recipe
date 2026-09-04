# Qwen3.8 Flash-Next on a 128 GB Mac — oMLX single-server recipe

## Machine contract

These numbers are from **one dedicated 128 GB Apple Silicon Mac** (M5 Max-class
MacBook Pro, macOS 26, **2026-08-31**) unless a newer file is in `results/`.

- Metal working-set cap ≈ **107.5 GB**. Planning peak = **102 GB**.
- Keep ~**100 GB free** on the SSD cache volume (`~/.omlx/ssd-cache`).
- Do **not** also run a second GPU-heavy app on this machine.
- Two 252K prefixes may not both stay in the LRU.

Re-measure on your own hardware before trusting any figure here.

## TL;DR (non-technical)

- **What it is:** a free, do-it-yourself recipe that turns a 128 GB Apple Silicon
  Mac into a private AI server running Qwen3.8 Flash-Next — no cloud, no
  subscription, nothing leaves your machine.
- **What was measured:** **one** oMLX process with `max_concurrent_requests=8`.
  The acceptance battery is **two sequential phases**: first two long prefills
  together, then six medium prefills together. That is HTTP concurrency on one
  server, not eight reserved KV “sessions” and not eight separate apps.
- **Ticks during a long fill:** observed **~1–25 s**, not “about one second”.
  The W1 pair on this box was **11.26 s** and **1.12 s** (cite both).
- **Memory:** dual-252K peaks were **98 GB (W1)** and **102 GB (G1)**. Use
  **102 GB** as the planning number against the 107.5 GB Metal cap. Steady
  state after tiering was ~73 GB.
- **You can re-run the proof:** `scripts/warm-8slot.py` plus raw JSON in
  `results/`. Nothing here is projected.

## The technical detail

**One oMLX 0.6.4 process, one Flash-Next (125B-A6B MoE) checkpoint, eight
HTTP request slots advertised:** 2 orchestrators sized toward 252K + 2 TDD
toward 32K + 2 coders toward 64K + 2 auditors toward 64K. The harness’s
*measured* `prompt_tokens` were **240,393 / 61,089 / 30,585** — not 252K /
64K / 32K. True concurrency is wall equality: simultaneous long prefills
finish with near-equal walls (spread 4.7 s on the W1 dual fill). The stack
lives under the 107.5 GB Metal working-set cap with an adaptive memory
enforcer and automatic SSD tiering.

Every number in this repo was measured on the reference machine with oMLX
0.6.4. Nothing is extrapolated.

Why a single oMLX process: see [docs/BATTERY.md](docs/BATTERY.md) for two
**separate** experiments (27B dense 4×118K FIFO vs chunked, and Flash-Next
2×252K). Do not mix those rows.

---

## Quick start

```bash
git clone <this repo>
cd Qwen3.8-Flash-Next-oMLX-Recipe
bash setup.sh                    # prerequisite checks; renders scripts/serve-flash.sh
bash scripts/serve-flash.sh      # manual launch
bash scripts/verify.sh           # ctx, footprint, live generation — fail-closed
# optional (~13 min acceptance battery + boot-warm):
python3 scripts/warm-8slot.py
```

`setup.sh` still writes a LaunchAgent plist today (`KeepAlive` + 30 s restart
on a ~69 GB Metal process). That is appliance mode and should be opt-in —
tracked as issue #3. Do not `launchctl bootstrap` it unless you want the
server restarted for you at login.

An AI agent doing this install should read [AGENT.md](AGENT.md) first.
Pinned binaries and the Hugging Face revision: [MODELS.md](MODELS.md).
All measured traps: [docs/TRAPS.md](docs/TRAPS.md).

## The one config that matters: `chunked_prefill`

oMLX's default scheduler (`prefill_priority: "context"`, chunking off)
finishes one long prefill completely before starting the next — a staircase.

That staircase was measured on a **different architecture** (27B dense,
4×118K). Do not read it as Flash-Next 2×252K:

- 27B dense, chunked **off**: per-stream walls 304 / 1225 / 1240 / 1243 s — spread **939 s**
- 27B dense, chunked **on**: walls 1241–1267 s — spread **25.6 s**, every stream TTFT ~4 s

Flash-Next 2×252K with chunked on: W1 walls 483.6 / 488.4 s, spread **4.73 s**.

In `~/.omlx/settings.json`:

```json
"memory":   { "prefill_memory_guard": true, "memory_guard_tier": "balanced",
              "soft_threshold": 0.85, "hard_threshold": 0.95 },
"scheduler":{ "max_concurrent_requests": 8, "chunked_prefill": true,
              "prefill_priority": "context", "decode_fairness": true },
"server":   { "burst_decode_mode": "balanced" }
```

Per-model (`~/.omlx/model_settings.json`): `mtp_enabled: false`,
`max_context_window: 262144`, `qwen4_ple_ssd_offload: true` for the flash
checkpoint.

`mtp_enabled: false` is **measured on this box / this checkpoint** (solo
60.9 tok/s on vs ~86 off). It is not a general law until
`results/mtp_on_off.json` exists for solo **and** load.

`setup.sh` patches both files when they exist. Missing files currently print
a NOTE and can still exit 0 — that hole is issue #3.

## Launch

**Manual (default):**

```bash
~/.omlx/bin/omlx serve --model-dir ~/models/omlx-qwen38 --host 127.0.0.1 --port 8000 \
  --max-concurrent-requests 8 --paged-ssd-cache-dir ~/.omlx/ssd-cache
```

**At boot (currently written by `setup.sh`; treat as opt-in, issue #3):**
the rendered plist is `~/Library/LaunchAgents/com.omlx.flash8slot.plist`
from `scripts/com.omlx.flash8slot.plist.in`. If you really want appliance
mode:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.omlx.flash8slot.plist
```

`KeepAlive` is on — the plist is the owner; don't also launch manually, the
port conflict kills the newcomer. Stop with
`launchctl bootout gui/$(id -u)/com.omlx.flash8slot`.

Bind to 127.0.0.1 (default). If you expose the API beyond localhost, set an
API key in `~/.omlx/settings.json` → `auth.api_key` first.

## Memory budget (phys_footprint, never `ps` RSS)

| State | Footprint | Note |
|---|---|---|
| Booted, idle (weights paged in) | ~69 GB | flash oQ4e checkpoint |
| Peak during dual 252K cold fill (W1) | **98 GB** | `results/warm_8slot_results.json` |
| Peak during dual 252K cold fill (G1) | **102 GB** | `results/p4_combined_results.json` / `omlx_flash_2way_results.json` — **planning number** |
| Steady, all 8 HTTP slots resident | **73 GB** | orchestrator KV auto-tiers to SSD |
| Static worst case (nothing tiered) | ~97–99 GB | 69 + 2×9.25 + 2×1.2 + 4×2.3 GB |

**Budget line is the 107.5 GB Metal working-set cap, not 128 GB RAM.** Plan
to the **102 GB** G1 peak. The enforcer (soft 96.8 / hard 102.1 / ceiling
107.5 GB, adapts live) throttles prefill chunks, reclaims pooled buffers,
and moves cold KV to the SSD page cache before anything OOMs.
Slot rate: ~9.25 GB per 252K slot, ~1.2 GB per 32K, ~2.3 GB per 64K.

**SSD tier:** `~/.omlx/ssd-cache` with max size `auto` resolved to a
self-managed **185.8 GB LRU** on the reference machine. One measured D2
pair: re-promoting a 252K prefix from SSD took **8.7 s** vs **~229 s**
full re-prefill on an LRU miss. That is not a guarantee both orchestrators
stay warm — two 252K prefixes may not both stay cached. Keep ~100 GB free
on the cache volume.

## Operating rules (all measured)

1. **Boot-warm both orchestrators together — that's safe from empty**
   (W1 98 GB, G1 102 GB). The rule is about *later*: **never cold-fill both
   252K orchestrators while the fleet is resident** — two fill spikes on
   top of steady state can cross the cap and cost you SSD evictions of hot
   slots.
2. **Verify the advertised context after every boot** (`scripts/verify.sh`):
   per-model `max_context_window` is not always honored. Trust `/v1/models`,
   not the settings file.
3. **Salt every repeated benchmark prompt** (`[variant <tag>]` suffix):
   identical fillers hit the prefix cache and wall-times collapse
   (12.1 s → 3.4 s measured).
4. Read memory with `/usr/bin/footprint <pid>`, never RSS — mmap'd weights lie.
5. Stop by port, not by the wrapper process:
   `kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)` — `omlx serve` spawns a
   child that survives the wrapper.

## Concurrency (measured)

- **Dual 252K cold fill (W1):** walls 483.6 / 488.4 s, spread **4.73 s**;
  measured prompt_tokens **240,393** each; planner ticks mid-fill
  **11.26 s and 1.12 s** (range across the box ~1–25 s).
- **Six workers over hot orchestrators:** measured prompt_tokens
  **30,585** (TDD) and **61,089** (coder/auditor). Pair spreads auditors
  **0.2 s**, coders **2.5 s**, TDD **8.9 s**; TTFT 0.05–0.66 s.
- 27B dense 4×118K FIFO vs chunked, and any mlx-serve comparison, live in
  [docs/BATTERY.md](docs/BATTERY.md) as **separate** experiments.

## Verify (after every boot)

1. `/v1/models` advertises `max_model_len: 262144`.
2. Boot log shows the enforcer from **this** boot:
   `Process memory enforcer started (ceiling=107.5GB)`.
3. `footprint <pid>`: ~69 GB idle.
4. One live generation, then `scripts/warm-8slot.py` if you want the full receipt.

## Traps and scaling limits

All measured traps live in [docs/TRAPS.md](docs/TRAPS.md). Measured NOs:

| Attempt | Result |
|---|---|
| MTP speculative decode on **this** checkpoint, **this** box | 60.9 tok/s solo vs ~86 with it off — leave off until `results/mtp_on_off.json` covers load too; not a general law |
| Second flash instance (2× weights) | Impossible: 2×69 GB weights alone exceed the chip |
| 27B / llama.cpp long-prefill concurrency | FIFO staircase on those engines — oMLX chunked is the measured fix **for that experiment** |

## Results

Raw measurement JSON from the reference machine: [results/](results/) —
`warm_8slot_results.json` (the 8-slot acceptance battery), plus the earlier
dual-252K and 4×118K batteries. Methodology:
[docs/BATTERY.md](docs/BATTERY.md).

## Credits

- oMLX (jundot) — the serving runtime; `chunked_prefill` is the whole ballgame.
- Qwen team — the Flash-Next checkpoint.
- Recipe format inspired by MiaAI-Lab's per-config deployment recipes and
  tonyd2wild's cookbook/setup.sh/AGENT.md pattern.

## License

MIT — see [LICENSE](LICENSE).
