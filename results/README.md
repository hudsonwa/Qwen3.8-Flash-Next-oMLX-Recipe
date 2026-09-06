# results/

Dated receipts. Do not mix revisions.

| File | What | Date |
|---|---|---|
| `warm_8slot_results.json` | Historical dual ~240k concurrent prefill + 6 workers (walls, not decode tok/s) | 2026-08-31 |
| `single_head_latency.json` | L1 / #40: 1×252K head + short slots, N≥3 | 2026-09-06 |
| `prefix_hit_miss.json` | L2 / #41: frozen prefix miss ~256 s vs hit ~8.3–9.0 s | 2026-09-06 |
| `kernel_status.txt` | native_kernel_status via app cpython; all five kernels available | 2026-09-06 |
| `hot_cache_current.json` | Live hot_cache_max_size `"0"` (disabled); launchd argv has no hot flag | 2026-09-06 |
| `hot_cache_one_brain.json` | One-brain A/B: hot=0 disk hits ~8.5 s vs `--hot-cache-max-size 12GB` RAM hits ~2.45–2.76 s; peak 91 GB | 2026-09-06 |
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
| `decode_table.json` | **Not published.** Pair `benchmark.py --label baseline` then `--label recipe` | — |

Every new JSON must include `machine` (chip, RAM, macOS, oMLX, date) from
`scripts/machine_stamp.py` — except a projection-only file, which must cite
receipt constants and must not invent tok/s.
