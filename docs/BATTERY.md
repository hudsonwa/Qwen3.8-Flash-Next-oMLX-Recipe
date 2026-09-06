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

| Condition | Completion wall (not TTFT) | TTFT |
|---|---|---|
| chunked **off** (4×118K simultaneous) | 304 / 1225 / 1240 / 1243 s, spread **939 s** (staircase) | not the headline |
| chunked **on** | 1241–1267 s, spread **25.6 s** | ~4 s |

**L1+L5 confound:** G1 dual-fill tick ~25 s is not L5 shorts-during-fill 4–12 s.

Receipt: `results/omlx27_4way_results.json`. Measured prompt_tokens in that
file are ~112,599, not a literal 118K.

## Experiment 2 — Flash-Next (this recipe)

Architecture: Qwen3.8 **Flash-Next** oQ4e, oMLX 0.6.4. **Canonical numbers:**
[PROFILE.md](PROFILE.md). Dual-252K 08-31 is a historical row in that table,
not the daily warm path.

Competitive engine rows: [PENDING.md](PENDING.md) — no receipt, no claim.

Tick range: cite [PROFILE.md](PROFILE.md). Shorts during a single long fill
4–12 s remain OPEN (`results/two_lane_latency.json`).

Memory and miss/hit walls live in [PROFILE.md](PROFILE.md) / `results/*.json`.
Do not copy them here.

## MTP

Leave MTP **off**. Load receipt exists: `results/mtp_on_off.json` (short-load
only). Short-load did not win. Decode tok/s live in `results/decode_table.json`
(published 2026-09-07; protocol [DECODE.md](DECODE.md)). Do not mix the two.

## Method notes

- Memory: `/usr/bin/footprint <pid>` only.
- Throughput: server log completion lines, not client-side stream timing.
- Prompt sizing: repeated filler paragraph (~65 tok/rep) + unique `[variant]`
  salt. The filler does **not** hit 252K/64K/32K on this tokenizer; report the
  JSON `prompt_tokens`.
- Battery runs from a cold, single-instance state; every phase writes its JSON
  before the next starts, so a crash still banks the completed phases.
- **Prefill chunk size is not a recipe knob.** Spark/vLLM 2k–4k chunks are a
  habit, not a port. `setup.sh` / `omlx-config.py` / `serve-flash.sh` do not
  expose `prefill_step_size`. Daily serving is `chunked_prefill` on; upstream
  default step (2048) plus the runtime adaptive throttle. No A/B JSON vs 96.8
  on this recipe. Do not expect a 24% win at 256k (that +24.7% was 8k-only on
  vLLM/Spark, a different stack).
