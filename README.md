# Qwen3.8 Flash-Next on a 128 GB Mac — oMLX single-server recipe

**Tweet-sized, JSON-backed (serving profile only):** [docs/PROFILE.md](docs/PROFILE.md).
Default: one ~240k head + short slots, hot=0, MTP off, oMLX 0.6.4,
`max_concurrent_requests=8`. Dual 08-31 is historical n=1. Decode tok/s:
[results/decode_table.json](results/decode_table.json).

```
This recipe (128 GB, 8 HTTP slots)     Different lab (e.g. 256 GB single-stream)
-----------------------------------    ---------------------------------------
default: 1 x ~240k head + short slots  single-stream *decode* / ANE / MTP draft
historical dual 08-31 (PROFILE table)  different memory regime — do not port here
generation tok/s: results/decode_table.json
```

## Machine contract

These numbers are from **one dedicated 128 GB Apple Silicon Mac** (M5 Max-class,
macOS 26) unless a newer file is in `results/`. They are **not portable**.
**Zero independent reproductions** as of [VERSION](VERSION). A second machine
does not exist in git unless you commit a receipt (even a 60k fill +
`scripts/verify.sh`). Matrix: [docs/HARDWARE.md](docs/HARDWARE.md).
Scope: [docs/SCOPE.md](docs/SCOPE.md).

- Metal working-set cap ≈ **107.5 GB** (not “128 GB RAM”). Planning peak = **102 GB**.
  Soft **96.8 GB** is a fail.
- Keep ~**100 GB free** on the SSD cache volume (`~/.omlx/ssd-cache`). That is
  a **capacity** rule, not a wipe. Prefix/KV on disk is unencrypted by this
  recipe — [docs/PRIVACY.md](docs/PRIVACY.md).
- Do **not** also run a second GPU-heavy app on this machine.
- Two 252K prefixes may not both stay in the LRU.
- **Install** hits GitHub (oMLX DMG) and Hugging Face (checkpoint). **Inference**
  after that can stay on the Mac.
- The **repo name is a dated snapshot**, not a product line.
- **08-31 dual-252K** is historical **n=1**, not the daily warm path.
- **Launchd KeepAlive** is **opt-in only** (`bash setup.sh --install-agent`).

Canonical numbers: **[docs/PROFILE.md](docs/PROFILE.md)** (locked to `results/*.json`).
Do not copy those seconds into a second headline here.

Re-measure on your own hardware before trusting any figure here.

## Quick start

Full first-install path: **[BOOTSTRAP.md](BOOTSTRAP.md)** (a–i).
`setup.sh` does **not** install oMLX and does **not** download weights.

```bash
# after oMLX 0.6.4 is in ~/Applications and the pinned checkpoint exists:
git clone https://github.com/hudsonwa/Qwen3.8-Flash-Next-oMLX-Recipe.git
cd Qwen3.8-Flash-Next-oMLX-Recipe
kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)   # (e) stop by port if anything is up
bash setup.sh                                      # (f) patch config only
bash scripts/serve-flash.sh                        # (g) daily: hot=0, mc=8, MTP off
bash scripts/verify.sh                             # (h) fail-closed
# optional: python3 scripts/warm-8slot.py --out results/warm_8slot_<utc>.json
```

Agents: read [AGENT.md](AGENT.md) first.

CI (`.github/workflows/lint.yml`) is syntax / schema / scrub / self-test.
It does **not** run oMLX or Metal.

## Links

| Doc | What |
|---|---|
| [docs/PROFILE.md](docs/PROFILE.md) | Canonical numbers table |
| [BOOTSTRAP.md](BOOTSTRAP.md) | First install a–i |
| [MODELS.md](MODELS.md) | oMLX 0.6.4 DMG SHA + HF revision |
| [AGENT.md](AGENT.md) | Agent install rules |
| [docs/EXITCODES.md](docs/EXITCODES.md) | Gate scripts: 0 only on full pass |
| [docs/HARDWARE.md](docs/HARDWARE.md) | What was measured / what was not |
| [docs/SCOPE.md](docs/SCOPE.md) | Measured appliance recipe — not a library |
| [docs/PRIVACY.md](docs/PRIVACY.md) | KV/prefix cache on disk; FileVault assumed |
| [docs/TRAPS.md](docs/TRAPS.md) | Measured failure modes |
| [docs/BATTERY.md](docs/BATTERY.md) | How verdicts were earned (not a second numbers table) |
| [docs/DECODE.md](docs/DECODE.md) | Decode protocol |
| [docs/PENDING.md](docs/PENDING.md) | No receipt, no claim |
| [docs/COMPAT.md](docs/COMPAT.md) | Pin tuple |
| [docs/PREFIX_POLICY.md](docs/PREFIX_POLICY.md) | Split salt |
| [results/README.md](results/README.md) | Receipt index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Receipts welcome; number-only PRs closed |
| [VERSION](VERSION) / [CHANGELOG.md](CHANGELOG.md) | Profile version |

Shorts during a long fill are **4–12 s** (`results/two_lane_latency.json`) — **OPEN**, not solved.
12 GB hot KV is an optional one-brain variant, **not** the daily default (daily hot=0).

## Credits

- oMLX (jundot) — the serving runtime; `chunked_prefill` is the whole ballgame.
- Qwen team — the Flash-Next checkpoint.

## License

MIT for **this recipe's scripts and docs only**. Model weights and oMLX are
not MIT — [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md). Provenance:
[docs/PROVENANCE.md](docs/PROVENANCE.md).
