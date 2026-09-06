# DECODE protocol

Do **not** headline 8-token dummy completions. This file is the protocol.
The receipt `results/decode_table.json` is **not in git** until a 128 GB Mac
run writes it. File status lives in [results/README.md](../results/README.md)
only.

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

Until `decode_table.json` exists, do not invent tok/s. Short-load MTP walls
stay in `results/mtp_on_off.json` and are **not** this table.
