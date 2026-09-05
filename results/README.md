# results/

Dated receipts. Do not mix revisions.

| File | What | Date |
|---|---|---|
| `warm_8slot_results.json` | Dual ~240k concurrent prefill + 6 workers (walls, not decode tok/s) | 2026-08-31 |
| `omlx_flash_2way_results.json` | Flash-Next 2-way / G1 102 GB | 2026-08-31 |
| `omlx27_4way_results.json` | 27B dense 4×118K FIFO vs chunked | 2026-08-31 |
| `p4_combined_results.json` | Dual-engine stress | 2026-08-31 |
| `decode_table.json` | **Not published yet.** Pair `benchmark.py --label baseline` then `--label recipe` | — |
| `mtp_on_off.json` | **Not published yet.** Same decode protocol, solo and load | — |

Every new JSON must include `machine` (chip, RAM, macOS, oMLX, date) from
`scripts/machine_stamp.py`.
