# Bootstrap — first install on a 128 GB Apple Silicon Mac

`setup.sh` does **not** install oMLX and does **not** download weights.
It only checks pins, patches config, and renders `scripts/serve-flash.sh`.
Fetch: `bash scripts/fetch-pins.sh` (DMG SHA + hf download only).
Print this file with pins filled in: `bash setup.sh --print-bootstrap`.

Daily profile (unchanged by PR #48): **1×252K head + short slots**, MTP **off**,
`hot_cache_max_size=0`, `max_concurrent_requests=8`, oMLX **0.6.4**, HF rev in
[MODELS.md](MODELS.md). `--hot-cache-max-size 12GB` is an optional measured
variant, not the default.

SSD KV/prefix cache (`~/.omlx/ssd-cache`) is prompt-derived data at rest.
FileVault is assumed. Wipe only after the server is stopped:
[docs/PRIVACY.md](docs/PRIVACY.md). “Keep ~100 GB free” is capacity, not a wipe.

Do these steps in order.

## (a) Machine

Darwin **arm64**, **≥128 GB** unified memory. This recipe was measured on one
dedicated 128 GB Mac. Do not also run a second GPU-heavy app.

## (b) Install oMLX 0.6.4

Pinned DMG, SHA256, and size: [MODELS.md](MODELS.md) section 1.

Install `oMLX.app` into `~/Applications` (not `/Applications` — TCC blocks
in-place upgrades from a terminal). Confirm:

```bash
~/.omlx/bin/omlx --version    # must print 0.6.4
```

## (c) Download the checkpoint

Pinned Hugging Face id + revision: [MODELS.md](MODELS.md) section 2.

```bash
hf download Jundot/Qwen3.8-Flash-Next-oQ4e-mtp \
  --revision 2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8 \
  --local-dir ~/models/qwen38-flash-next-oq4e-mtp
echo 2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8 \
  > ~/models/qwen38-flash-next-oq4e-mtp/.hf_revision
```

Quarantine dir (one symlink) is required by the launch commands — see MODELS.md.

## (d) First serve so oMLX writes config

Start the server **once** so it creates `~/.omlx/settings.json` and
`~/.omlx/model_settings.json`. Then stop it (next step). Missing files are a
**fail** for `setup.sh`.

## (e) Stop by port

```bash
kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)
```

Killing the `omlx serve` wrapper does nothing. The child `omlx-server` holds
the port.

## (f) Patch config

```bash
git clone https://github.com/hudsonwa/Qwen3.8-Flash-Next-oMLX-Recipe.git
cd Qwen3.8-Flash-Next-oMLX-Recipe
bash setup.sh
```

Dry run (no writes): `bash setup.sh --bootstrap-check` (issue #51).

## (g) Serve daily flags

```bash
bash scripts/serve-flash.sh
```

Daily: **hot=0**, **mc=8**, **MTP off**. Do not pass `--hot-cache-max-size 12GB`
unless you mean the optional one-brain variant in
`results/hot_cache_one_brain.json`.

Never run `serve-flash.sh` and the LaunchAgent together.

## (h) Verify (fail-closed)

```bash
bash scripts/verify.sh
```

If it reports a miss, stop. Do not declare success.

## (i) Optional warm

```bash
python3 scripts/warm-8slot.py
```

Default is **one** 252K head + short slots. Dual-head is
`python3 scripts/warm-8slot.py --dual-head` only.

Agents: read [AGENT.md](AGENT.md) first.
