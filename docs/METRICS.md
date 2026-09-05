# Metrics

Two different numbers. Do not mix them.

| Column | Definition |
|---|---|
| decode tok/s | `(completion_tokens - 1) / (wall_s - TTFT_s)` after first streamed token |
| prefill tok/s | `prompt_tokens / TTFT_s` |
| TTFT | seconds to first streamed token |
| max admitted ctx | `/v1/models` `max_model_len` |
| peak GB | `phys_footprint_peak` |

See [docs/METHODOLOGY.md](METHODOLOGY.md). Two profiles: [docs/PROFILES.md](PROFILES.md).

Protocol (`scripts/benchmark.py`):

- Frozen prompts in `prompts/{code,prose,counting}.txt`
- 256 `max_tokens`, warmup discarded, N≥3
- Unique `[variant salt]` suffix so prefix-cache hits are 0
- Always pair `--label baseline` (stock oMLX 0.6.4 settings) and `--label recipe`
- `scripts/compare.py` exits 1 if a twin is missing

8-token dummy walls from `warm-8slot.py` are **not** decode tok/s.

The dual-~240k concurrent prefill walls (483.6 / 488.4 s, 2026-08-31) are a
**prefill concurrency** result, not a generation-speed claim.
