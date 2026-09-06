# results/

Dated receipts. Do not mix revisions.

| File | What | Date |
|---|---|---|
| `warm_8slot_results.json` | Dual ~240k concurrent prefill + 6 workers (walls, not decode tok/s) | 2026-08-31 |
| `single_head_latency.json` | L1 / #40: 1×252K head + short slots, N≥3 | 2026-09-06 |
| `prefix_hit_miss.json` | L2 / #41: frozen prefix miss ~256 s vs hit ~8.7 s | 2026-09-06 |
| `context_scaling.json` | L3 / #42: walls at ~240k/~120k/~60k measured | 2026-09-06 |
| `two_lane_latency.json` | L5 / #44: short lane vs ~240k fill | 2026-09-06 |
| `omlx_flash_2way_results.json` | Flash-Next 2-way / G1 102 GB | 2026-08-31 |
| `omlx27_4way_results.json` | 27B dense 4×118K FIFO vs chunked | 2026-08-31 |
| `p4_combined_results.json` | Dual-engine stress | 2026-08-31 |
| `decode_table.json` | **Not published yet.** Pair `benchmark.py --label baseline` then `--label recipe` | — |
| `mtp_on_off.json` | **Not published yet.** Same decode protocol, solo and load | — |

Every new JSON must include `machine` (chip, RAM, macOS, oMLX, date) from
`scripts/machine_stamp.py`.
