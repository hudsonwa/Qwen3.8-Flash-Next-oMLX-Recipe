# BATTERY — how the verdicts were earned

## The standard: wall equality, not "it didn't crash"

A concurrency claim is only earned by firing N long fills **simultaneously**,
recording per-stream walls, and requiring small spread between equal-size
streams (`scripts/warm-8slot.py` implements this and writes a JSON receipt):

- spread ≤ ~5 s per equal-size pair → true concurrency
- walls forming a staircase → FIFO (serial prefill), no matter how stable the server

Cross-size spreads are expected (64K-sized slots take roughly twice as long as
32K-sized slots); judge same-size pairs, plus TTFT (all streams should start
~instantly under chunked prefill) and mid-fill tick latency (a short request
poked in during the fill).

The 8-slot recipe is **one process**, `max_concurrent_requests=8`, **two
sequential batteries** (2× long prefill, then 6× medium prefill). That is
HTTP concurrency, not eight reserved KV slots.

## Experiment 1 — 27B dense, 4×118K (FIFO vs chunked)

Architecture: Qwen3.8 **27B dense**, not Flash-Next. Same machine, oMLX 0.6.4.

| Condition | Result |
|---|---|
| chunked **off** (4×118K simultaneous) | walls 304 / 1225 / 1240 / 1243 s, spread **939 s** (staircase) |
| chunked **on** | walls 1241–1267 s, spread **25.6 s**, TTFT ~4 s |

Receipt: `results/omlx27_4way_results.json`. Measured prompt_tokens in that
file are ~112,599, not a literal 118K.

## Experiment 2 — Flash-Next, 2×252K (this recipe)

Architecture: Qwen3.8 **Flash-Next** oQ4e, oMLX 0.6.4, chunked on.

| Test | Result | Receipt |
|---|---|---|
| W1 dual fill + ticks | walls 483.62 / 488.35 s, spread **4.73 s**; ticks **11.26 s** and **1.12 s**; peak **98 GB**; prompt_tokens **240,393** | `results/warm_8slot_results.json` |
| G1 dual fill | walls 539.09 / 541.91 s, spread **2.82 s**; ticks 24.91 / 1.34 / 1.31 s; peak **102 GB** (planning number vs 107.5 GB Metal cap); prompt_tokens **240,381** | `results/omlx_flash_2way_results.json`; corroborated by `results/p4_combined_results.json` H2_flash_2x252k_fill peak 102 |
| W2 six workers on hot orch | prompt_tokens **30,585** (TDD) / **61,089** (coder, auditor); pair spreads auditors 0.21 s / coders 2.53 s / TDD 8.88 s; ~1,017 tok/s agg | `results/warm_8slot_results.json` |
| Solo 252K fill (G0) | 228.7 s (~1,050 tok/s) | `results/omlx_flash_2way_results.json` |

**mlx-serve comparison (same Flash-Next model, different engine):** the historical
measurement was 2 serial FIFO prefills, 1,084 s wall / spread 563 s, with a planner
tick waiting 553 s mid-fill. **Receipt pending re-run** — no mlx-serve JSON exists
in `results/` for these figures; treat them as historical until re-measured, and do
not delete them until a replacement receipt lands.

Tick range to quote in summaries: **~1–25 s**, with the W1 pair cited together.

## Footprint ledger (phys_footprint, GB)

| State | Measured |
|---|---|
| Flash weights, idle | ~69 |
| Dual 252K cold-fill peak (W1) | **98** |
| Dual 252K cold-fill peak (G1) | **102** — planning number |
| Steady, all 8 HTTP slots resident | 73 (orchestrator KV auto-tiered to SSD) |
| Static worst case (nothing tiered) | ~97–99 |
| Slot cache rate | ~9.25 GB / 252K slot; ~1.2 GB / 32K; ~2.3 GB / 64K |

## SSD tier receipts

- One D2 pair: warm 252K prefix re-promoted from SSD **8.7 s** vs **~229 s**
  full re-prefill on LRU miss. Not a guarantee both orchestrators stay warm.
- `auto` max size resolved to a self-managed **185.8 GB LRU** cap; eviction is
  native. Two 252K prefixes may not both stay cached. Keep ~100 GB free on
  the cache volume.

## MTP

Solo, this checkpoint, this box: 60.9 tok/s with MTP on vs ~86 off. That is
**not** a general law and is **unmeasured at 8-way** until
`results/mtp_on_off.json` exists.

## Method notes

- Memory: `/usr/bin/footprint <pid>` only.
- Throughput: server log completion lines, not client-side stream timing.
- Prompt sizing: repeated filler paragraph (~65 tok/rep) + unique `[variant]`
  salt. The filler does **not** hit 252K/64K/32K on this tokenizer; report the
  JSON `prompt_tokens`.
- Battery runs from a cold, single-instance state; every phase writes its JSON
  before the next starts, so a crash still banks the completed phases.
