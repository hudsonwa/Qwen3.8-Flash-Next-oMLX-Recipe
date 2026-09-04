# MODELS.md — pinned artifacts (do not search)

Every number in this repo was measured against **these** bits. Newer
builds need a new receipt in `results/` before you trust the tables.

## 1. Server runtime — oMLX 0.6.4

Confirm after install: `~/.omlx/bin/omlx --version` must print `0.6.4`.
0.6.4 is the build that fixed the multi-stream batch-join bug in 0.6.3.

Release: https://github.com/jundot/omlx/releases/tag/v0.6.4

| macOS | File | Size (bytes) | SHA256 |
|---|---|---|---|
| 26 / 27 (this recipe) | `oMLX-0.6.4-macos26-27.dmg` | 805799490 | `53f1506c2385e8920a67198b72d1fe09351c1b3538be9c6bdeb78e5277d06d93` |
| 15 Sequoia | `oMLX-0.6.4-macos15-sequoia.dmg` | 782180533 | `5a90c7ae4a3f4ca8bf10dcc83d7f7395281e2ffb2a85d630c95e9720848e47cd` |

- **Install location:** put `oMLX.app` in `~/Applications`. An in-place
  upgrade over `/Applications/oMLX.app` is TCC-blocked from a terminal and
  leaves a broken mixed bundle (see docs/TRAPS.md).
- The CLI shim at `~/.omlx/bin/omlx` execs the bundled `omlx-cli`. The GUI
  binary hangs when run headless — always use the shim.
- Re-verify the README memory tables on any newer build before trusting them.

## 2. Model checkpoint

| Role | Hugging Face id | Revision | Local directory | Weights footprint |
|---|---|---|---|---|
| All 8 HTTP slots | `Jundot/Qwen3.8-Flash-Next-oQ4e-mtp` | `2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8` | `~/models/qwen38-flash-next-oq4e-mtp` | ~69 GB (idle phys_footprint) |

Served model id (what `/v1/models` returns on the reference box):
`qwen38-flash-next-oq4e-mtp`.

Download (pin the revision; do not take whatever `main` is tomorrow):

```bash
hf download Jundot/Qwen3.8-Flash-Next-oQ4e-mtp \
  --revision 2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8 \
  --local-dir ~/models/qwen38-flash-next-oq4e-mtp
```

Count shards against the Hub sibling list before serving. Do **not**
substitute a third-party quant without re-measuring; MTP/PLE layouts
differ between quantizers (docs/TRAPS.md).

**Quarantine dir (required by the launch commands):** oMLX scans
subdirectories of `--model-dir` and follows symlinks. Serve exactly one
checkpoint through a one-symlink dir:

```bash
mkdir -p ~/models/omlx-qwen38
ln -sfn ~/models/qwen38-flash-next-oq4e-mtp \
        ~/models/omlx-qwen38/qwen38-flash-next-oq4e-mtp
```
