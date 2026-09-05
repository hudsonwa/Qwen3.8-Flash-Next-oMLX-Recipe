# METHODOLOGY

## tok/s

| Column | Definition | Counts |
|---|---|---|
| decode tok/s | `(completion_tokens - 1) / (wall_s - TTFT_s)` after first streamed token | generation |
| prefill tok/s | `prompt_tokens / TTFT_s` | prompt ingest |
| TTFT | seconds to first streamed token | latency |
| max admitted ctx | `/v1/models` `max_model_len` | admission |
| peak GB | `/usr/bin/footprint` `phys_footprint_peak` | memory |

Do **not** headline tool-call tok/s on 8-token dummy completions. Do **not**
mix prefill walls (dual ~240k 484/488 s) into decode tok/s.

Warmup discarded. N≥3. Unique `[variant salt]` so prefix cache is 0.
`temperature` 0. Thinking off. Frozen prompts in `prompts/`.

## What does not count

- Empty completion / `prompt_tokens` 0
- Cache hits (`cached_tokens` > 0) in a “cold” row
- A run that OOMs or trips `admission_paused`
- MTP-on without `verify_activation.py --expect interactive` passing
- Raising `iogpu.wired_limit_mb` to “make it fit”

## Evidence layout

`evidence/<phase>/` is for local traces (SSE, logs). Not required in git.
Published numbers live in `results/` with a `machine` stamp.
