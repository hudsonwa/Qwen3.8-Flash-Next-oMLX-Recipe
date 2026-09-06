# PENDING — unbacked comparisons

Moved out of README / BATTERY so they are not treated as measured.

## mlx-serve vs this recipe

**Claim (historical, no current receipt):** 2 serial FIFO prefills, 1,084 s wall /
spread 563 s, planner tick 553 s mid-fill.

**Missing protocol:** same Flash-Next oQ4e checkpoint, same Mac, same prompts as
`results/hot_cache_one_brain.json` A (frozen prefix, salt on tail), JSON with
`machine`, `omlx`, `hf_revision`, `peak_gb`, `prompt_tokens`, `ttft_s`, `wall_s`,
`cached_tokens`, `n`. File would live at `results/mlx_serve_*.json`.

Until that file exists, do not put mlx-serve numbers in README or BATTERY.

## llama.cpp long-prefill concurrency

**Claim:** FIFO staircase on llama.cpp. **Missing:** JSON in `results/`.
27B-dense oMLX FIFO vs chunked **is** measured (`results/omlx27_4way_results.json`)
and stays in [BATTERY.md](BATTERY.md) experiment 1.
