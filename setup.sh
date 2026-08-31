#!/usr/bin/env bash
# One-shot setup: dual mlx-serve stack (Qwen3.8-Flash-Next 256K + Qwen3.8-27B 128K)
# on a 128 GB Apple Silicon MBP. Detects machine, checks prerequisites, writes
# launcher config, verifies model dirs. Does NOT auto-start servers (see scripts/).
set -euo pipefail
cd "$(dirname "$0")"

OS="$(uname -s)"; ARCH="$(uname -m)"
MEM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))

echo "==> machine: $OS $ARCH, ${MEM_GB} GB unified memory"
if [ "$OS" != "Darwin" ] || [ "$ARCH" != "arm64" ]; then
  echo "FAIL: this recipe is Apple Silicon (Darwin arm64) only" >&2; exit 1
fi
if [ "$MEM_GB" -lt 128 ]; then
  echo "FAIL: measured shape needs 128 GB unified memory (found ${MEM_GB})" >&2; exit 1
fi

# ---- configurable locations (override via env) -----------------------------
MLX_SERVE_BIN="${MLX_SERVE_BIN:-$HOME/.local/opt/mlx-serve-26.8.11-pre/mlx-serve-macos-arm64/mlx-serve}"
MODEL_FLASH="${MODEL_FLASH:-$HOME/models/qwen38-flash-next-mlx-serve-4bit}"
MODEL_27B="${MODEL_27B:-$HOME/models/mlx-Qwen3.8-27B-4bit}"
API_KEY="${API_KEY:-change-me}"

# ---- checks ----------------------------------------------------------------
fail=0
if [ ! -x "$MLX_SERVE_BIN" ]; then
  echo "MISSING: mlx-serve binary at $MLX_SERVE_BIN (see MODELS.md section 1)"; fail=1
fi
for d in "$MODEL_FLASH" "$MODEL_27B"; do
  if [ ! -d "$d" ]; then
    echo "MISSING: model dir $d (see MODELS.md section 2)"; fail=1
  fi
done
[ "$fail" = "1" ] && exit 1

# ---- write launchers -------------------------------------------------------
for side in flash 27b; do
  sed -e "s|@BIN@|$MLX_SERVE_BIN|g" \
      -e "s|@MODEL@|$( [ "$side" = flash ] && echo "$MODEL_FLASH" || echo "$MODEL_27B" )|g" \
      -e "s|@KEY@|$API_KEY|g" \
      "scripts/serve-$side.sh.in" > "scripts/serve-$side.sh"
  chmod +x "scripts/serve-$side.sh"
done

echo "PASS: prerequisites OK, launchers written (scripts/serve-flash.sh, scripts/serve-27b.sh)"
echo "Next: bash scripts/serve-27b.sh first, wait for 'Hot prefix cache: ENABLED',"
echo "      then bash scripts/serve-flash.sh — boot order matters (see README)."
