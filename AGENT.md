# AGENT.md — instructions for an AI agent setting this up

You are an AI agent on the operator's machine. The operator wants the dual-server
Qwen3.8 stack from this recipe running and verified. Do it end to end without
asking questions you can answer by inspecting the machine.

## Goal

Two mlx-serve processes resident on one 128 GB Apple Silicon Mac:
- Flash (Qwen3.8-Flash-Next, 256K ctx, MTP) on port 10099
- 27B (Qwen3.8-27B dense, 128K ctx) on port 10012

Verified = boot logs show `Hot prefix cache: ENABLED` on BOTH servers, one live
full-speed generation per port, and `footprint` of each process inside the
README memory table.

## Steps

1. Run `bash setup.sh`. It fail-closes on: non-arm64, <128 GB, missing binary,
   missing model dirs. Fix what it names (MODELS.md has the sources).
2. Boot order is a HARD RULE: **27B first**, then flash. NEVER start both cold
   at the same time — measured 3/3 memory-pressure kills of the flash process.
3. After each boot, read the server log and require the exact line
   `Hot prefix cache: ENABLED (capacity=N, mem-cap=X MB)`.
   If it says `disabled`, the stride flags did not take — stop and fix.
4. Verify per README "Verify" section: footprint values, one generation per port,
   ports clean (`lsof -nP -iTCP:<port> -sTCP:LISTEN`) before any relaunch.
5. Report: both ports, both cache lines, both footprints, both decode speeds.

## Hard rules

- Never claim DONE without reading the boot logs and footprint values back.
- Never "fix" a memory kill by raising any wired-limit; reduce slots/entries.
- Never swap these flags for defaults: `--mtp` (flash), `--timeout 0`,
  `--ssm-checkpoint-stride 256 --ssm-checkpoint-max 4`,
  `--prefix-cache-mem 28GB` (flash) / `12GB` (27B). Each one earns its place in
  the README.
- If a scenario in the README cannot be reproduced on this machine, report the
  mismatch honestly. Do not extrapolate README numbers to new hardware.
