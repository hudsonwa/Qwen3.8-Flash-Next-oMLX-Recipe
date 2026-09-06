# DECODE protocol

Do **not** headline 8-token dummy completions. This file is the protocol.
Cite the JSON; do not copy tok/s into a second headline.

Two contracts — do not mix them.

## Issue 9 (current `results/decode_table.json`)

Named GO on GitHub #86. Warm frozen prefix (`prompts/decode_fill.txt`), stream,
completion **128 / 512 / 2048**, concurrency **1 / 4 / 8**, MTP **off vs on**,
discard MTP batch 1. N≥3 after warmup. temp 0. Thinking off
(`chat_template_kwargs.enable_thinking: false`). Soft **96.8 GB** aborts the
MTP-on arm and restores serving.

```bash
python3 scripts/decode_table_issue9.py
```

Reports TTFT, `(completion_tokens-1)/(wall_s-TTFT_s)`, peak GB, blended
`completion_tokens/wall_s`. Restores daily hot=0, mc=8, MTP off, chunked on,
then `verify.sh`. Does **not** overwrite `mtp_on_off.json`.

## Issue 64 archive (`results/decode_table_issue64.json`)

Solo + short8, n=3, 2026-09-07, unique salt (cold rows). Not 128/512/2048.
Not MTP-on.

```bash
python3 scripts/benchmark.py --label baseline --mode solo
python3 scripts/benchmark.py --label recipe --mode solo
python3 scripts/compare.py
```

`--mode short8` is a **separate** series. Do not average solo with short8.
`compare.py` reads the #64 archive.

## Shared rules

- Warmup discarded.
- `N >= 3` kept runs.
- `temperature` 0.
- Thinking **off** (`chat_template_kwargs.enable_thinking: false`).
- Prefill tok/s := `prompt_tokens / TTFT_s`.
- Generation tok/s := `(completion_tokens - 1) / (wall_s - TTFT_s)`.
- Do not mix MTP-on with MTP-off. Do not mix hot=0 with hot=12GB.

Short-load MTP walls stay in `results/mtp_on_off.json` and are **not** either
table.
