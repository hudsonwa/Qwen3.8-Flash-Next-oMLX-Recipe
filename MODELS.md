# MODELS.md — where every artifact comes from

## 1. Server binary

mlx-serve 26.8.11-pre (arm64). The measured build for every number in this repo.

- Expected location: `~/.local/opt/mlx-serve-26.8.11-pre/mlx-serve-macos-arm64/mlx-serve`
- Override with `MLX_SERVE_BIN=/path/to/mlx-serve bash setup.sh`
- Upstream project: mlx-serve (ddalcu) — check releases for a newer build, but
  re-verify the README memory tables on any newer version before trusting them.

## 2. Models

| Role | Model | Footprint | Hugging Face |
|---|---|---|---|
| Flash :10099 | Qwen3.8-Flash-Next 125B-A6B, 4-bit MLX | ~68 GB weights | search "Qwen3.8-Flash-Next 4bit MLX" on huggingface.co — use the official Qwen 4-bit MLX release |
| 27B :10012 | Qwen3.8-27B dense, 4-bit MLX | ~16 GB weights | search "Qwen3.8-27B 4bit MLX" on huggingface.co — official Qwen MLX release |

- Default dirs: `~/models/qwen38-flash-next-mlx-serve-4bit` and
  `~/models/mlx-Qwen3.8-27B-4bit` — override with `MODEL_FLASH=` / `MODEL_27B=`.
- Download with the HF CLI: `hf download <repo> --local-dir <dir>`.
- Do NOT substitute the oQ4e-mtp checkpoint from third-party quantizers without
  re-measuring — MTP layouts differ between quantizers (see docs/TRAPS.md).
