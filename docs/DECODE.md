# DECODE protocol

Do **not** headline 8-token dummy completions. This file is the protocol.
Receipt: [results/decode_table.json](../results/decode_table.json) (128 GB Mac,
2026-09-07, n=3, solo and short8). Cite the JSON; do not copy tok/s into a
second headline.

## Command

```bash
python3 scripts/benchmark.py --label baseline --mode solo
python3 scripts/benchmark.py --label recipe --mode solo
python3 scripts/compare.py
```

`--mode short8` is a **separate** series (eight concurrent short jobs). Do not
average solo with short8. Do not mix MTP-on with MTP-off. Do not mix hot=0
with hot=12GB.

## Rules

- Warmup discarded (`--warmup 1` default).
- `N >= 3` kept runs (`--n 3`).
- `temperature` 0.
- Thinking **off** (`chat_template_kwargs.enable_thinking: false`).
- Unique `[variant salt]` suffix so `cached_tokens` is 0 on cold rows.
- Prefill tok/s := `prompt_tokens / TTFT_s`.
- Generation tok/s := `(completion_tokens - 1) / (wall_s - TTFT_s)`.
- Default `--max-tokens 256` (not 8).
- Pair `--label baseline` then `--label recipe`. `compare.py` refuses a lone series.
- Does not toggle MTP or rewrite `~/.omlx`.

Short-load MTP walls stay in `results/mtp_on_off.json` and are **not** this
table. Do not average solo with short8. Do not mix MTP-on with MTP-off.
