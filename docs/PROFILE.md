# PROFILE — canonical numbers (locked to `results/*.json`)

Do not restate these figures elsewhere. Cite this file or the JSON path.
27B-dense FIFO vs chunked is a **separate** experiment in [BATTERY.md](BATTERY.md).

Machine stamp (daily / optional rows): Darwin 25.6.0, macOS 26.6.2, Apple M5 Max, 128 GB, arm64, oMLX 0.6.4 — from `results/single_head_latency.json` `machine`.

| profile | date | measured prompt_tokens | miss / hit **TTFT** (not completion tok/s) | peak GB | n | hot-cache size | receipt |
|---|---|---|---|---|---|---|---|
| daily: 1×252K + short, MTP off | 2026-09-06 | 240355 | miss 237.8 s; **disk** hits ~8.5 s after that miss (`hot_cache_one_brain_pr48.json` A) / prefix_hit_miss disk hits 8.30–8.96 s | 88 | 3 | `0` (disabled) | `results/single_head_latency.json`, `results/hot_cache_one_brain_pr48.json` A, `results/hot_cache_current.json` |
| optional: 12 GB hot, one brain (#48) | 2026-09-06 | 240355 | 2.45–2.76 s after a cold miss — pre-register **INCONCLUSIVE** (2–6 s), not RAM; not a second head | 91 | 3 | `12GB` | `results/hot_cache_one_brain_pr48.json` B |
| A-B-A-B one-brain (resident prefix) | 2026-09-06 | 240355 | ratio median A/B **0.982**; both arms ~2.6 s inconclusive; settle 82 GB; **no win** | 91 | 3 pairs | `0` vs `12GB` | `results/hot_cache_one_brain.json` |
| historical dual-252K | 2026-08-31 | 240393 (W1) | dual fill 483.62 / 488.35 s; not a prefix hit/miss pair | 98 W1 / 102 G1 | 1 battery | n/a (pre-hot-tier row) | `results/warm_8slot_results.json`, `results/omlx_flash_2way_results.json` |

Notes locked to those files:

- Default warm path is **one** 252K head + short slots, **hot=0**. Dual only `--dual-head`.
- Old ~8.5 s / ~8.7 s “hit” numbers are **SSD**, not RAM. The 8.7 s / 229 s and
  8.3–9.0 s / 256 s cites were measured with the hot tier **off / unset**; they
  are config-specific (this table).
- Pre-register for one-brain hits: <2 s RAM, >6 s still SSD, 2–6 s inconclusive.
  Do not call 2.45–2.76 s RAM.
- A-B-A-B on the resident prefix did **not** win (`hot_cache_one_brain.json`).
- Miss class ~238 s (A 237.8 s) / ~256 s (`prefix_hit_miss.json`).
- **L1+L5 confound:** G1 dual-fill tick ~25 s is not L5 shorts-during-fill 4–12 s.
- `results/mtp_on_off.json` exists (short-load only; off mean 6.00 s vs on 12.83 s). Leave MTP off. Solo anecdote ~60.9 vs ~86 stays in [PROVENANCE.md](PROVENANCE.md). Upstream conflict: [TRAPS.md](TRAPS.md) #3.
- Decode tok/s protocol: [DECODE.md](DECODE.md). File status: [results/README.md](../results/README.md).
- Ticks: G1 `tick-1` **24.91 s**; W1 **11.26 s** and **1.12 s**. Shorts during a single long fill **4–12 s** (`results/two_lane_latency.json`) — OPEN.
- Soft 96.8 GB = fail. Plan 102 GB. Metal cap 107.5 GB.
- **n:** current rows above are n=3. Historical dual is **n=1 battery** (not current). `hot_cache_current.json` is an **n=1 snapshot**, not a daily headline. Do not average mixed dates, mixed oMLX builds, or hot=0 with hot=12GB.
