# Contributing

This is a **lab notebook**. Receipts welcome. Number-only PRs
(a number in README/PROFILE without a new `results/*.json`) **are closed**.

## Issues

The tracker is **public**. Use the Receipt / machine stamp template.

The next credibility move is **one other 128 GB Mac** running BOOTSTRAP.md +
`scripts/verify.sh` + `scripts/quality_canary.py`, then a gist or PR of
stamped JSON. Do not invent that receipt.

Include:

- machine stamp (chip, RAM GB, macOS)
- oMLX version
- Hugging Face revision
- hot-cache size (`0` or `12GB`)
- `scripts/verify.sh` output
- a `results/*.json` receipt (or a gist of it)

Do not open “please delete my comment” or identity-policing tickets.

## Pull requests

- Commit as `Name <numericid+login@users.noreply.github.com>`
- `bash scripts/check-scrub.sh` before push
- Do not overwrite `results/warm_8slot_results.json`, #48 hot-cache JSON,
  `decode_table.json`, `quality_canary.json`, `mtp_on_off.json`, or any
  committed stamped `results/*.json` without `--force-replace` and a
  CHANGELOG note. Default writes are timestamped.
- Do not invent `decode_table.json`
- Daily profile stays hot=0, mc=8, MTP off unless the PR is a **named** variant

A PR that only changes a number in README/PROFILE without a new receipt
will be closed.
