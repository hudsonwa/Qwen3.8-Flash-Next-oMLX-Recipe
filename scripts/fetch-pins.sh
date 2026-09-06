#!/usr/bin/env bash
# Fetch pinned bits only. Does not patch ~/.omlx. Does not start the server.
# setup.sh stays the config patcher.
set -euo pipefail
cd "$(dirname "$0")/.."

OMLX_VERSION_PIN="${OMLX_VERSION_PIN:-0.6.4}"
HF_ID="${HF_ID:-Jundot/Qwen3.8-Flash-Next-oQ4e-mtp}"
HF_REVISION_PIN="${HF_REVISION_PIN:-2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8}"
MODEL_SRC="${MODEL_SRC:-$HOME/models/qwen38-flash-next-oq4e-mtp}"
DMG_DIR="${DMG_DIR:-$HOME/Downloads}"

# macos 26/27 is this recipe; override with OMLX_DMG_NAME for Sequoia.
DMG_NAME="${OMLX_DMG_NAME:-oMLX-0.6.4-macos26-27.dmg}"
DMG_SHA="${OMLX_DMG_SHA:-53f1506c2385e8920a67198b72d1fe09351c1b3538be9c6bdeb78e5277d06d93}"
DMG_URL="${OMLX_DMG_URL:-https://github.com/jundot/omlx/releases/download/v${OMLX_VERSION_PIN}/${DMG_NAME}}"

FETCH_DMG=1
FETCH_HF=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dmg-only) FETCH_HF=0 ;;
    --hf-only) FETCH_DMG=0 ;;
    -h|--help)
      echo "usage: bash scripts/fetch-pins.sh [--dmg-only|--hf-only]"
      echo "  DMG SHA check + hf download only. Does not patch settings."
      exit 0
      ;;
    *) echo "FAIL: unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

# Streaming SHA256 (not Path.read_bytes). shasum reads in chunks.
sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

if [ "$FETCH_DMG" = "1" ]; then
  mkdir -p "$DMG_DIR"
  dest="$DMG_DIR/$DMG_NAME"
  if [ -f "$dest" ]; then
    got="$(sha256_file "$dest")"
    if [ "$got" = "$DMG_SHA" ]; then
      echo "OK: $DMG_NAME SHA256 matches pin"
    else
      echo "FAIL: $dest SHA256 $got != pin $DMG_SHA — delete and re-run" >&2
      exit 1
    fi
  else
    echo "==> downloading $DMG_URL"
    curl -fL --retry 3 -o "$dest.partial" "$DMG_URL"
    mv "$dest.partial" "$dest"
    got="$(sha256_file "$dest")"
    if [ "$got" != "$DMG_SHA" ]; then
      echo "FAIL: downloaded $dest SHA256 $got != pin $DMG_SHA" >&2
      rm -f "$dest"
      exit 1
    fi
    echo "OK: downloaded $DMG_NAME SHA256 matches pin"
  fi
fi

if [ "$FETCH_HF" = "1" ]; then
  if ! command -v hf >/dev/null 2>&1; then
    echo "FAIL: gate=hf-cli — hf not on PATH (install huggingface_hub CLI)" >&2
    exit 1
  fi
  mkdir -p "$MODEL_SRC"
  echo "==> hf download $HF_ID @ $HF_REVISION_PIN -> $MODEL_SRC"
  hf download "$HF_ID" --revision "$HF_REVISION_PIN" --local-dir "$MODEL_SRC"
  printf '%s\n' "$HF_REVISION_PIN" > "$MODEL_SRC/.hf_revision"
  echo "OK: wrote $MODEL_SRC/.hf_revision"
fi

echo "PASS: fetch-pins (no config patch). Next: bash setup.sh"
