# BATTERY — how the verdicts were earned

## The standard: wall equality, not "it didn't crash"

A concurrency claim is only earned by firing N long fills **simultaneously**, recording
per-stream walls, and requiring small spread between equal-size streams
(`scripts/warm-8slot.py` implements this and writes a JSON receipt):

- spread ≤ ~5 s per equal-size pair → true concurrency
- walls forming a staircase → FIFO (serial prefill), no matter how stable the server

Cross-size spreads are expected (64K slots take roughly twice as long as 32K slots);
judge same-size pairs, plus TTFT (all streams should start ~instantly under chunked
prefill) and mid-fill tick latency (a short request poked in during the fill).

## Measured history on the reference machine (128 GB M5 Max)

| Test | oMLX 0.6.4, chunked ON | chunked OFF | mlx-serve 26.8.11-pre |
|---|---|---|---|
| 4×118K simultaneous fills (27B dense) | spread **25.6 s** | spread 939 s | spread ~843 s (FIFO) |
| 2×252K simultaneous fills (flash) | spread **2.8–4.7 s**, ~985–1050 tok/s agg | — | 2 serial 520 s prefills, spread 563 s |
| Planner tick during a 252K fill | **1.1–11.3 s** | — | **553 s** (FIFO wait) |
| Solo 252K fill | 228.7 s (~1,050 tok/s) | — | 613 s |
| 8-slot mixed (2×252K + 2×32K + 2×64K + 2×64K) | pair spreads ≤ 8.9 s, ~1,017 tok/s agg over 6 fills | — | — |

(`llama.cpp` was also evaluated for this role: no true long-prefill concurrency.
That's why the engine here is oMLX with chunking on.)

## Footprint ledger (phys_footprint, GB)

| State | Measured |
|---|---|
| Flash weights, idle | ~69 |
| Dual 252K cold-fill peak | 98 (enforcer cycles soft 96.8, never hard 102.1) |
| Steady, all 8 slots resident | 73 (orchestrator KV auto-tiered to SSD) |
| Static worst case (nothing tiered) | ~97–99 |
| Slot cache rate | ~9.25 GB / 252K slot; ~1.2 GB / 32K; ~2.3 GB / 64K |

## SSD tier receipts

- Warm 252K prefix re-promoted from SSD: **8.7 s** vs 229.8 s full re-prefill on LRU miss.
- `auto` max size resolved to a self-managed 185.8 GB LRU cap; eviction is native.

## Raw receipts

`results/warm_8slot_results.json` — the 8-slot acceptance battery (W1 dual 252K
boot-warm + ticks, W2 six workers over hot orchestrators, footprints per phase).
`results/omlx_flash_2way_results.json`, `results/omlx27_4way_results.json`,
`results/p4_combined_results.json` — the earlier engine-selection batteries.

## Method notes

- Memory: `/usr/bin/footprint <pid>` only.
- Throughput: server log completion lines, not client-side stream timing.
- Prompt sizing: repeated filler paragraph (~65 tok/rep) + unique `[variant]` salt.
- Battery runs from a cold, single-instance state; every phase writes its JSON before
  the next starts, so a crash still banks the completed phases.
