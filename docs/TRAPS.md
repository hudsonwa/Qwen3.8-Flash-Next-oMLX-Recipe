# TRAPS — every way this stack has actually failed

Each trap below was hit and measured on the reference machine. Not folklore.

1. **Silent MTP loss on flash.** MoE checkpoints default speculative decode off.
   Missing `--mtp` = 2.3×→1.0× decode with zero errors. Verify speed, not logs.

2. **Stride 0 silently disables the hot prefix cache.** Hybrid models
   (QSAKVCache) need SSM checkpoints to restore entries. Boot log then reads
   `Hot prefix cache: ... full-attention-interval — disabled` and every hot
   resume re-prefills at full price (613 s for a 252K repeat). Fix:
   `--ssm-checkpoint-stride 256 --ssm-checkpoint-max 4`. Read the boot log line
   on EVERY relaunch.

3. **Default 300 s timeout kills long prefills.** A 256K prefill runs ~10 min.
   `--timeout 0` is not optional for the flash server.

4. **Default 2 GB prefix-cache-mem cannot hold one slot.** One 252K flash entry
   ~9.2 GB; one 118K 27B entry ~2.2 GB. Undersized cache = every test of cache
   behavior measures a miss.

5. **Simultaneous cold-fill kills flash.** Transients stack (~78 GB + ~59 GB
   over physical). 3/3 kills measured. 90 s stagger still kills the 27B side.
   Boot 27B hot first, always.

6. **Port conflict kills the NEW instance, old one keeps serving.** Symptom:
   "new" flags seem ignored. `lsof -nP -iTCP:<port> -sTCP:LISTEN`, kill the
   listener, relaunch, re-read boot log.

7. **RSS lies.** MLX mmap-weights + buffer pool: `ps` RSS stayed 14.4 GB
   before/after a prefill that added real KV (footprint 18→19 GB). Measure
   `footprint <pid>` (phys_footprint) and budget against the 107.5 GB Metal
   working-set cap.

8. **KV-per-token derived from config math is wrong.** Config math said
   5.3 GB/64K slot for 27B; measured 1.2 GB (4× off). Always calibrate with a
   real prefill probe before capacity claims.

9. **A tick aimed at a filling server FIFO-waits the whole prefill.** 553 s
   measured for a 2K tick into a 252K fill; 0.85–1.9 s on the other server.
   Route around fills.

10. **Metal OOM ≠ out of RAM.** The GPU allocator throws it; host RSS and swap
    look fine. Reduce KV/slots/entries or lower stride. Never chase system RAM.

11. **Don't raise wired-limit to "fix" a memory kill.** It moves the cliff,
    destabilizes the OS, and hides the real overbudget. Shrink the shape.

12. **Third-party MTP quant layouts differ.** The measured config used a
    specific 4-bit MLX flash checkpoint; oQ4e-mtp layouts from other quantizers
    change MTP tensor placement. Re-verify MTP activation + speed on any new
    checkpoint before publishing numbers.
