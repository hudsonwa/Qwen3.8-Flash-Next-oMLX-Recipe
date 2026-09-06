# Profiles

This repo’s **default is serving**. Interactive MTP is a named second profile.
The filename `-mtp` on the checkpoint is **not** activation.

## serving (default — do not replace)

| Key | Value |
|---|---|
| oMLX | 0.6.4 |
| checkpoint | oQ4e-mtp revision pinned in MODELS.md |
| `scheduler.chunked_prefill` | true |
| `scheduler.max_concurrent_requests` | 8 |
| `mtp_enabled` | false |
| `vlm_mtp_enabled` | false |
| Metal plan | 102 GB / 107.5 GB cap |
| Receipt | [PROFILE.md](PROFILE.md) — daily 1×252K hot=0; optional 12 GB hot; historical dual 08-31 |

Tweet-sized (this profile only): cite [PROFILE.md](PROFILE.md). Dual 08-31 is
historical. Decode tok/s waits for `decode_table.json`.

## interactive (opt-in, not default)

| Key | Value |
|---|---|
| `mtp_enabled` | true |
| `mtp_num_draft_tokens` | 6 |
| `vlm_mtp_enabled` | false unless a VLM drafter is set |
| chunked / concurrent=8 | **unchanged** unless you explicitly apply `--mode baseline` |

Apply only with `python3 scripts/omlx-config.py --mode interactive --apply`.
Then `python3 scripts/verify_activation.py --expect interactive` (log line
`Qwen4-Exp Lightning MTP enabled` and checkpoint `mtp.` tensors).

**Receipt exists:** `results/mtp_on_off.json` (short-load only). Short-load did
not win. Leave MTP off. Filename `-mtp` ≠ on. `decode_table.json` unpublished.

## baseline (decode A/B only)

Stock oMLX 0.6.4 scheduler for a paired decode table (`--mode baseline`).
Not the daily 8-slot server. Restore with `--mode serving --apply`.
