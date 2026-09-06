# results/ SCHEMA

Every committed `results/*.json` is a lab receipt. Do not mix dates, oMLX
builds, or `hot=0` with `hot=12GB`.

## Required keys (measurement receipts)

| key | meaning |
|---|---|
| `machine` | object from `scripts/machine_stamp.py` (chip, RAM, macOS, date). No hostnames, no user paths. |
| `omlx` | version string, e.g. `0.6.4` |
| `hf_revision` | 40-char Hub pin |
| `n` | repeats after warmup. Current claims need `n >= 3` unless tagged `n=1 variant`. |
| `profile` | `serving` / `daily-hot-0` / `optional-hot-12gb` / `historical` / `projection` / `snapshot` |
| `pass` / `fails` | boolean `pass` and/or list `fails` |
| `prompt_tokens` | measured (int or list). Never the 252K/64K/32K labels. |

Hot-cache receipts **also** require `hot_cache_max_size` (string, e.g. `"0"` or `"12GB"`).
`settings_hot_cache_max_size` is accepted as an alias on snapshot files.

## Classes

**Measurement (full keys):** `single_head_latency.json`, `prefix_hit_miss.json`,
`context_scaling.json`, `two_lane_latency.json`, `latency_percentiles.json`,
`ab_sweep.json`, `ab_8vs4_live.json`, `mtp_on_off.json`, `hot_cache_one_brain.json`,
`decode_table.json`, `decode_table_issue64.json`, `quality_canary.json`.

**Snapshot:** `hot_cache_current.json` — live flags, not a battery. Still needs
`machine`, `omlx`, `hot_cache_max_size`.

**Projection:** `guard_projection.json` — arithmetic only. Needs `machine` +
`kind` containing `projection`. No tok/s.

**Historical (pre-stamp, do not rewrite numbers):** `warm_8slot_results.json`,
`omlx_flash_2way_results.json`, `omlx27_4way_results.json`,
`p4_combined_results.json`. CI requires parse-only. Do not delete them to
“fix” schema.

## Decode table

`decode_table.json` is the Issue 9 measurement receipt. `#64` lives in
`decode_table_issue64.json`. Protocol: [docs/DECODE.md](../docs/DECODE.md).
Do not mix the two files.

## Append-only

Do not overwrite a committed `results/*.json` that has a `machine` stamp
unless `--force-replace` **and** a `CHANGELOG.md` note names that file.
Named protected set (always): 08-31 files, `hot_cache_*.json`,
`decode_table.json`, `decode_table_issue64.json`, `quality_canary.json`,
`mtp_on_off.json`, `warm_8slot_results.json`.

Default write is a **timestamped** filename. Optional `*_latest.json`
pointers are gitignored and not published receipts.

`python3 scripts/receipt_guard.py --self-test` must exit 0.

## CI

`python3 scripts/check-results.py` must exit 0. Wired in `.github/workflows/lint.yml`.
