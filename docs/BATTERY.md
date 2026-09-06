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

The 8-slot recipe is **one process**, `max_concurrent_requests=8`.
Default warm path is **one 252K head + short slots**. Dual-head is historical.
Numbers: [PROFILE.md](PROFILE.md) (locked to `results/*.json`).

## Experiment 1 — 27B dense, 4×118K (FIFO vs chunked)

Architecture: Qwen3.8 **27B dense**, not Flash-Next. Same machine, oMLX 0.6.4.

| Condition | Result |
|---|---|
| chunked **off** (4×118K simultaneous) | walls 304 / 1225 / 1240 / 1243 s, spread **939 s** (staircase) |
| chunked **on** | walls 1241–1267 s, spread **25.6 s**, TTFT ~4 s |

Receipt: `results/omlx27_4way_results.json`. Measured prompt_tokens in that
file are ~112,599, not a literal 118K.

## Experiment 2 — Flash-Next (this recipe)

Architecture: Qwen3.8 **Flash-Next** oQ4e, oMLX 0.6.4. **Canonical numbers:**
[PROFILE.md](PROFILE.md). Dual-252K 08-31 is a historical row in that table,
not the daily warm path.

Competitive engine rows with no JSON: [PENDING.md](PENDING.md).

Tick range to quote: G1 **24.91 s** and W1 **11.26 s** / **1.12 s** (cite
PROFILE.md). Shorts during a single long fill 4–12 s remain OPEN.

## Footprint ledger (phys_footprint, GB)

| State | Measured |
|---|---|
| Flash weights, idle | ~69 |
| Dual 252K cold-fill peak (W1) | **98** |
| Dual 252K cold-fill peak (G1) | **102** — planning number |
| Steady, all 8 HTTP slots resident | 73 (orchestrator KV auto-tiered to SSD) |
| Static worst case (nothing tiered) | ~97–99 |
| Slot cache rate | ~9.25 GB / 252K slot; ~1.2 GB / 32K; ~2.3 GB / 64K |

## SSD tier

See [PROFILE.md](PROFILE.md): disk hit vs RAM hit vs miss. Two 252K prefixes
may not both stay in the LRU. Keep ~100 GB free on the cache volume.

## MTP

Leave MTP **off**. Load receipt exists: `results/mtp_on_off.json` (short-load
only). Short-load did not win. Not a decode table (`decode_table.json`
unpublished).

## Method notes

- Memory: `/usr/bin/footprint <pid>` only.
- Throughput: server log completion lines, not client-side stream timing.
- Prompt sizing: repeated filler paragraph (~65 tok/rep) + unique `[variant]`
  salt. The filler does **not** hit 252K/64K/32K on this tokenizer; report the
  JSON `prompt_tokens`.
- Battery runs from a cold, single-instance state; every phase writes its JSON
  before the next starts, so a crash still banks the completed phases.
