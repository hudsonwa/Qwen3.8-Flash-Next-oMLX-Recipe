# Qwen3.8 Flash-Next + 27B on a 128 GB Mac — mlx-serve dual-server recipe

**Two mlx-serve servers, one 128 GB Apple Silicon Mac: Flash-Next (125B-A6B MoE) at 256K context with MTP speculative decode, plus the dense 27B at 128K for worker/auditor streams. Proven shape: 2 hot 252K flash slots + 4 hot 118K 27B slots, ~91–103 GB combined, 4–16 GB under the Metal cap.**

Every number in this repo was measured on the reference machine (128 GB unified,
M5 Max-class) with mlx-serve 26.8.11-pre. Nothing is extrapolated. Run a number
yourself on different hardware before trusting it here.

---

## Quick start

```bash
git clone <this repo>
cd Qwen3.8-Flash-Next-27B-MLX-Serve-MBP-128GB
bash setup.sh          # fail-closed checks + renders launchers
bash scripts/serve-27b.sh    # FIRST — always
# wait for 'Hot prefix cache: ENABLED' in /tmp/qwen38-stack/27b.log
bash scripts/serve-flash.sh  # SECOND
# wait for 'Hot prefix cache: ENABLED' in /tmp/qwen38-stack/flash.log
bash scripts/verify.sh       # footprint + live-generation checks
```

An AI agent doing this install should read [AGENT.md](AGENT.md) first.
Model/binary sources: [MODELS.md](MODELS.md).

---

## The two launch commands (what setup.sh renders)

**Server 1 — Flash :10099 (long-context fast decoder):**
```bash
mlx-serve --model <flash-4bit-dir> --serve --host 127.0.0.1 --port 10099 \
  --ctx-size 262144 --mtp --timeout 0 \
  --ssm-checkpoint-stride 256 --ssm-checkpoint-max 4 \
  --prefix-cache-mem 28GB --api-key <key>
```

**Server 2 — 27B :10012 (worker/auditor):**
```bash
mlx-serve --model <27b-4bit-dir> --serve --host 127.0.0.1 --port 10012 \
  --ctx-size 131072 --timeout 0 \
  --ssm-checkpoint-stride 256 --ssm-checkpoint-max 4 \
  --prefix-cache-mem 12GB --api-key <key>
```

### Why every flag is there

| Flag | Reason (measured) |
|---|---|
| `--mtp` (flash) | MoE checkpoints default speculative decode OFF. Without it: silent 2.3× slowdown. Dense 27B does not get this flag. |
| `--ssm-checkpoint-stride 256 --ssm-checkpoint-max 4` | Enables the hot prefix cache on these hybrid models. Stride 0 (or unset) silently DISABLES restore: every repeat of a big prompt re-prefilled at full price. With 256/4: 252K repeat 613 s → 1.3 s (486×), 40K → ~0.7 s. |
| `--prefix-cache-mem 28GB / 12GB` | Default 2 GB cannot hold one 252K flash entry (~9.2 GB) or one 118K 27B entry (~2.2 GB). |
| `--timeout 0` | Default 300 s stall-kill aborts a ~10-minute 256K prefill. |
| `--ctx-size 262144 / 131072` | Flash carries long context (2 hot slots ~252K usable); 27B runs 4 slots at 118K usable. |

---

## Memory budget (phys_footprint, never `ps` RSS)

| State | Flash | 27B | Combined |
|---|---|---|---|
| Booted, idle | ~68 GB | ~16–17 GB | ~84 GB |
| Steady: 2×252K + 4×118K hot slots | ~76 GB | ~15–27 GB | ~91–103 GB |
| Worst transient (one server filling) | +~6 GB | +~17 GB | ≤ ~106 GB |

**Budget line is the 107.5 GB Metal working-set cap, not 128 GB RAM.**
Metal OOM is the GPU allocator — host RAM and swap are red herrings.

## Boot-order rule (breaks servers if ignored)

1. Boot 27B first, warm its slots.
2. Then boot flash and let it fill.
3. **NEVER cold-fill both simultaneously** — 3/3 memory-pressure kills of flash
   (transients stack ~137 GB > 128 GB physical). A 90 s stagger does not save it.
4. While one server fills a big slot, send short/tick requests to the OTHER
   server. A tick into a filling flash FIFO-waits the whole prefill (553 s
   measured); on the idle 27B it answers in 0.85–1.9 s.

## Concurrency (measured)

- Short (≤150 tok) and mid (2×8K) prompts **true-interleave** on both servers —
  every stream TTFT≈0. FIFO only appears when 256K prefills saturate a server.
- 27B 4-way: 22–23 tok/s each (~89 aggregate). 8-way: 91–99 aggregate.
- Cross-server 2+4 (flash+27B): 6 streams, ~104 tok/s aggregate, zero FIFO.
- Flash solo: short-ctx decode 61–71 tok/s (86–115 with MTP); 256K prefill
  ~424–430 tok/s (~620 s wall); M5 Max llmprobe reference: 86.2 avg decode,
  114.7 predictable / 65.5 novel, 1868 tok/s prefill hot.
- Past ~8 total concurrent streams the GPU — not memory — is the limit.

## Verify (after every boot)

1. Both boot logs: `Hot prefix cache: ENABLED (capacity=N, mem-cap=X MB)`.
   `disabled` = stride flags didn't take — stop and fix.
2. `footprint <pid>`: flash ~68 GB, 27B ~16–17 GB (idle).
3. One live full-speed generation per port.
4. Ports clean before any relaunch: `lsof -nP -iTCP:10099 -sTCP:LISTEN` (and 10012).

`scripts/verify.sh` automates 1–4 and fail-closes on any miss.

## Traps (all measured — full list in [docs/TRAPS.md](docs/TRAPS.md))

- Forgotten `--mtp` on flash → silent 2.3× slowdown, no error.
- Stride 0 / missing stride flags → cache "ENABLED" line absent; repeats cost full price.
- Missing `--timeout 0` → 256K prefill dies at ~300 s.
- Both servers cold-filled together → flash killed by memory pressure 3/3.
- Port conflict → NEW instance dies, OLD keeps serving with wrong flags.
- Read capacity with `footprint`, not RSS — MLX mmaps weights and pools buffers.

## Scaling limits (measured NOs)

| Attempt | Result |
|---|---|
| Second flash instance | Impossible: 2×68 GB weights + 27B = 161 GB demanded |
| Simultaneous cold-fill | 3/3 kills |
| 27B 4→8 streams | +11% only (GPU-bound) |

## Results

Raw measurement JSON from the reference machine: [results/](results/).
Methodology notes and the concurrency battery: [docs/BATTERY.md](docs/BATTERY.md).

## Credits

- mlx-serve (ddalcu) — the serving runtime.
- Qwen team — Flash-Next and 27B checkpoints.
- Recipe format inspired by MiaAI-Lab's per-config deployment recipes and
  tonyd2wild's cookbook/setup.sh/AGENT.md pattern.

## License

MIT — see [LICENSE](LICENSE).
