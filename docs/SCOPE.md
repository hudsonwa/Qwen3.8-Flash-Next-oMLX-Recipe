# SCOPE

This repository is a **measured appliance recipe** for one 8-slot oMLX serving
shape on one class of Mac.

It is **not**:

- a library or SDK
- Linux or CUDA
- multi-host / multi-machine serving
- productized serving (no SLA, no packaged installer beyond BOOTSTRAP.md)
- a full eval harness

Do **not** package the harness (`scripts/warm-8slot.py`, `scripts/benchmark.py`,
canaries) as a pip module or product.

## Facts that stay true (as of the string in [VERSION](../VERSION))

- **One dedicated box.** Numbers are from one 128 GB Apple Silicon Mac. See
  [HARDWARE.md](HARDWARE.md).
- The budget line is the **Metal working-set cap** (≈ 107.5 GB), **not**
  “128 GB RAM”.
- **Install** still hits GitHub (oMLX DMG) and Hugging Face (checkpoint).
  **Inference** after that can stay on the Mac (no cloud API).
- The **repo name is a dated snapshot** of this recipe, not a living product
  line.
- **08-31 dual-252K** is a historical **n=1** battery, not the daily warm path.
- **Launchd KeepAlive** is **opt-in only** (`bash setup.sh --install-agent`).
- **Zero independent reproductions** as of the version in [VERSION](../VERSION).
  A second machine does not exist in git until someone commits a receipt.

Daily serving profile (unchanged): 1×252K head + short slots, `hot_cache_max_size=0`,
`max_concurrent_requests=8`, MTP off, oMLX 0.6.4.
