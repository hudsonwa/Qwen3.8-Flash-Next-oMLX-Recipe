# PROVENANCE

What this repository is, and is not.

## Runtime

- **oMLX 0.6.4** from https://github.com/jundot/omlx/releases/tag/v0.6.4
- macOS 26/27 DMG `oMLX-0.6.4-macos26-27.dmg`
  SHA256 `53f1506c2385e8920a67198b72d1fe09351c1b3538be9c6bdeb78e5277d06d93`
- `chunked_prefill`, the memory enforcer, and SSD KV tiering are **jundot / oMLX**.
  This recipe did not invent them. It pins versions and records measurements.

## Checkpoint

- Hugging Face `Jundot/Qwen3.8-Flash-Next-oQ4e-mtp`
- revision `2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8`
- Small-file SHA256s: `files/SHA256SUMS`

## What we changed vs a stock oMLX 0.6.4 install

- `scheduler.chunked_prefill: true`, `max_concurrent_requests: 8`
- memory guard thresholds as in README
- `mtp_enabled: false` on this checkpoint. **Keep both:**
  - solo anecdote **~60.9 tok/s on vs ~86 off** (not a decode table)
  - load receipt `results/mtp_on_off.json` (8-way short, n=3): off mean batch
    **6.00 s** vs on **12.83 s** (first on-batch 27.16 s), peak 73 GB
  Upstream 0.6.4 notes still claim Lightning MTP speedups on batch-one
  Flash-Next — see [TRAPS.md](TRAPS.md) #3. Do not delete either number.
- quarantine `--model-dir` with one symlink
- optional `--state` so settings are not only in `~/.omlx`
- measurement scripts and receipts in `results/`

## What we did not invent

- The Flash-Next architecture, oQ4e quant, or MTP heads (Qwen / quantizer).
- Apple Metal / 107.5 GB working-set cap.
- ANE, 6-bit, or 256 GB single-stream draft stacks. Those are a different
  memory regime. Do not port them here as a headline. If you enable MTP,
  measure peak phys_footprint against 102 / 107.5 GB first.

## Results dating

JSON in `results/` is **2026-08-31** on the reference 128 GB M5 Max unless a
file's `machine.measured_at` says otherwise. Do not add percentages across
revisions.
