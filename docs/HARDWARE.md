# HARDWARE — what was measured, what was not

Figures in this repo are **not portable**. They come from one dedicated box.
There is **no second-machine reproduction** in git unless a receipt is
committed (even a 60k fill + `scripts/verify.sh` counts).

| Machine | Status | Why |
|---|---|---|
| **This 128 GB Apple Silicon Mac** (M5 Max-class, Metal working-set cap ≈ 107.5 GB) | **Measured.** Daily receipts in `results/` | The only machine whose numbers are in PROFILE.md |
| **96 GB** Apple Silicon | **Expected fail** | Idle weights already ~69 GB. One ~240k fill peaks ~88 GB. Plan 102 / soft **96.8 GB = fail**. 96 GB unified memory cannot hold this 8-slot shape under the same Metal cap math |
| **192 / 256 GB single-stream labs** | **Do not port** | Different memory regime (ANE / 6-bit / single-stream decode through 255k). A green decode number that OOMs this 128 GB 8-slot layout is a regression |
| **Any other chip / RAM / macOS / oMLX build** | **Re-measure** | Change any field in [COMPAT.md](COMPAT.md) → new JSON. Do not copy seconds |

Planning RAM is the **Metal cap**, not “128 GB RAM”. See [SCOPE.md](SCOPE.md).
