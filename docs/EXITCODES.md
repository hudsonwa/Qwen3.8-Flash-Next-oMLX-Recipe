# Exit codes

An agent reads **status from the process exit code**, not from the word
PASS/FAIL in the log. `0` means full pass. Any failed gate is **non-zero**.

`--help` / `--print-bootstrap` also exit 0 (they are not gates).

| Command | 0 | non-zero |
|---|---|---|
| `bash scripts/verify.sh` | every check green | any miss (`FAIL:` lines, then `exit 1`) |
| `python3 scripts/warm-8slot.py` | gates pass; timestamped receipt written | ctx / dual-guard / quality / spread / peak miss |
| `python3 scripts/quality_canary.py` | all checks pass | `1` miss; `2` API down |
| `bash setup.sh` | pins + patch succeeded | any named `gate=` miss |
| `bash setup.sh --bootstrap-check` | dry-run gates would succeed; **no writes** | missing pin or missing settings |
| `python3 scripts/check-results.py` | schema + no second JSON store | any schema/second-store miss |
| `python3 scripts/check-docs-drift.py` | daily pins agree | any drift miss |

Do **not** `print FAIL` and then `exit 0`. Grep the scripts above if you add a
gate: the fail path must `exit 1` / `return 1` / `raise SystemExit(1)`.
