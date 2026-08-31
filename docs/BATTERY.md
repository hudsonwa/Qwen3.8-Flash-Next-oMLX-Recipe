# BATTERY.md — how the numbers were measured

## Reference machine
128 GB unified Apple Silicon (M5 Max-class), macOS 26, mlx-serve 26.8.11-pre,
4-bit MLX checkpoints of Qwen3.8-Flash-Next (125B-A6B) and Qwen3.8-27B.

## Discipline

- **Capacity** = `footprint <pid>` phys_footprint. `ps` RSS is not used anywhere
  (mmap + buffer pool make it flat while real memory moves; see TRAPS #7).
- **KV/slot** = measured by prefilling a known token count and diffing
  footprint — never derived from config math (TRAPS #8).
- **Token counts** calibrated with `llama-tokenize --show-count` across arms
  (±0.5%); prompts salted per variant to block cross-stream cache hits.
- **Degraded runs are reported, not retried into submission.** A Metal-OOM
  scenario is isolated (per-scenario server guard + auto-relaunch) and the
  failure is the finding.
- **Claims gates**: any "cache enabled / MTP active / aborted" property is
  asserted from server telemetry in the captured JSON — never inferred from a
  completion.

## The 2×4 shape battery (raw JSON in results/)

- `shape2x4_results.json` — the full battery: cold-fill kill matrix (3/3 flash
  kills on simultaneous cold-fill; 90 s stagger still kills the 27B side),
  second-flash-instance demand (161 GB), FIFO/tick-latency scenarios, and the
  invalid first pass kept for the record.
- `shape2x4_finalcell.json` — the passing final cell: 27B hot first, flash
  fills 2×252K while ticks fire at 120 s/420 s (0.85–1.9 s tick latency),
  post-fill footprints, and the 27B hot-resume timing after the stride-256 fix.

## Reproducing

1. Boot per README (order matters), run `scripts/verify.sh` to PASS.
2. Run your own probes against `:10099`/`:10012` with salted prompts; capture
   server-side telemetry lines in your results JSON.
3. Publish your hardware row with the same fields (footprints, tick latency,
   kill/no-kill, hot-resume seconds) — additions welcome via PR.
