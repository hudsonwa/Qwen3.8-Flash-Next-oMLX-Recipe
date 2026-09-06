# results/

Dated receipts. Do not mix revisions.

| File | What | Date |
|---|---|---|
| `warm_8slot_results.json` | Historical dual ~240k concurrent prefill + 6 workers (walls, not decode tok/s) | 2026-08-31 |
| `single_head_latency.json` | L1 / #40: 1×252K head + short slots, N≥3 | 2026-09-06 |
| `prefix_hit_miss.json` | L2 / #41: frozen prefix miss ~256 s vs hit ~8.3–9.0 s **TTFT** (hot tier off / unset; config-specific after one-brain A/B) | 2026-09-06 |
| `kernel_status.txt` | native_kernel_status via app cpython; all five kernels available | 2026-09-06 |
| `hot_cache_current.json` | Live hot_cache_max_size `"0"` (disabled); launchd argv has no hot flag | 2026-09-06 |
| `hot_cache_one_brain_pr48.json` | #48 archive: hot=0 disk ~8.5 s vs 12GB 2.45–2.76 s after a 237.8 s miss; peak 91 GB. Pre-register: 2–6 s inconclusive, not RAM. | 2026-09-06 |
| `hot_cache_one_brain.json` | A-B-A-B n=3 pairs on the same frozen prefix (already resident). Ratio median A/B 0.982; both ~2.6 s inconclusive; settle 82 GB; peak 91 GB; **no win**. Daily restored hot=0. | 2026-09-06 |
| `context_scaling.json` | L3 / #42: ~60k mean wall ~71 s vs ~240k mean wall ~285 s | 2026-09-06 |
| `two_lane_latency.json` | L5 / #44: short during ~240k fill **4–12 s — OPEN, not solved** | 2026-09-06 |
| `latency_percentiles.json` | L7 / #46: queue/TTFT/ITL p50/p95/p99 | 2026-09-06 |
| `ab_sweep.json` | L8 / #47: short 8-way chunked on/off; settings mc=4 is not live argv | 2026-09-06 |
| `ab_8vs4_live.json` | L8 / #47: same-session 8 vs 4 (launchd gone, serve argv 4, then restore 8) | 2026-09-06 |
| `mtp_on_off.json` | **Published.** L8 / #15: MTP off vs on under 8-way short load, peak_gb. Short-load did not win — leave MTP off. | 2026-09-06 |
| `guard_projection.json` | Projection-only (no tok/s). Idle 69 / one-head 88 / steady 73 vs plan 102 / soft 96.8 | 2026-09-06 |
| `omlx_flash_2way_results.json` | Flash-Next 2-way / G1 102 GB | 2026-08-31 |
| `omlx27_4way_results.json` | 27B dense 4×118K FIFO vs chunked | 2026-08-31 |
| `p4_combined_results.json` | Dual-engine stress | 2026-08-31 |
| `decode_table_issue64.json` | **Archive of #64.** Solo + 8-way-short, n=3, temp 0, thinking off, unique salt. Not Issue 9. | 2026-09-07 |
| `decode_table.json` | **Issue 9 / #86.** Warm prefix, 128/512/2048 × concurrency 1/4/8 × MTP off vs on, discard MTP batch 1. Cite JSON. Protocol: [docs/DECODE.md](../docs/DECODE.md). | 2026-09-07 |
| `quality_canary.json` | **Published.** Fail-closed canary (needle in ~229k prefix, JSON-only, short code). **Not a full eval harness.** | 2026-09-07 |

Every new JSON must include `machine` (chip, RAM, macOS, oMLX, date) from
`scripts/machine_stamp.py` — except a projection-only file, which must cite
receipt constants and must not invent tok/s.

Current headlines need **n≥3**. #48 A/B is n=3. `hot_cache_current.json` is an
n=1 snapshot tag, not daily. 08-31 files are historical n=1 batteries.
See [SCHEMA.md](SCHEMA.md).
