# MODELS.md — where every artifact comes from

## 1. Server runtime

oMLX **0.6.4** (the measured build for every number in this repo; 0.6.4 fixes the
multi-stream batch-join bug that broke concurrent prefills in 0.6.3).

- Releases: `https://github.com/jundot/omlx/releases` — DMG variants per macOS
  version (macos15-sequoia vs macos26-27); pick the one matching your OS.
- Confirm after install: `~/.omlx/bin/omlx --version`.
- **Install location:** put `oMLX.app` in `~/Applications`. An in-place upgrade over
  `/Applications/oMLX.app` is TCC-blocked from a terminal and leaves a broken mixed
  bundle (see docs/TRAPS.md). The CLI shim at `~/.omlx/bin/omlx` execs the bundled
  `omlx-cli`; the GUI binary hangs when run headless — always use the shim.
- Check release notes for newer versions, but re-verify the README memory tables on
  any newer build before trusting them.

## 2. Model checkpoint

| Role | Model | Size on disk | Weights footprint |
|---|---|---|---|
| All 8 slots | Qwen3.8-Flash-Next 125B-A6B, oQ4e quant | ~104 GB | ~69 GB |

- Source: search `Qwen3.8-Flash-Next oQ4e` on huggingface.co — use the official Qwen
  oQ4e (oMLX-quantized) release. Do NOT substitute third-party quantizations without
  re-measuring; MTP/PLE layouts differ between quantizers (docs/TRAPS.md).
- Default local dir: `~/models/qwen38-flash-next-oq4e-mtp`, downloaded with
  `hf download <repo-id> --local-dir <dir>` (count shards against the HF API's
  sibling list before serving).
- **Quarantine dir (required by the launch commands):** oMLX scans subdirectories of
  `--model-dir` and follows symlinks. Serve exactly one checkpoint through a
  one-symlink dir:

  ```bash
  mkdir -p ~/models/omlx-qwen38
  ln -sfn ~/models/qwen38-flash-next-oq4e-mtp \
          ~/models/omlx-qwen38/qwen38-flash-next-oq4e-mtp
  ```
