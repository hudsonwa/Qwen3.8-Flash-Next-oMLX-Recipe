#!/usr/bin/env bash
# One-shot setup: oMLX 8-slot Flash-Next stack (2x252K + 2x32K + 2x64K + 2x64K)
# on a 128 GB Apple Silicon Mac. Checks prerequisites, patches oMLX config for
# chunked prefill + memory guard, renders the foreground launcher.
# Does NOT auto-start the server. Does NOT write a LaunchAgent unless
# --install-agent is passed (KeepAlive on a ~69 GB Metal process is opt-in).
set -euo pipefail
cd "$(dirname "$0")"

INSTALL_AGENT=0
STATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --install-agent) INSTALL_AGENT=1 ;;
    --state)
      shift
      STATE="${1:-}"
      [ -n "$STATE" ] || { echo "FAIL: --state needs a directory" >&2; exit 1; }
      ;;
    -h|--help)
      echo "usage: bash setup.sh [--install-agent] [--state DIR]"
      echo "  --state DIR  patch DIR/{settings,model_settings}.json instead of ~/.omlx"
      echo "               (set OMLX_HOME=DIR when serving if the binary honors it)"
      exit 0
      ;;
    *) echo "FAIL: unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done
OMLX_CONF="${STATE:-$HOME/.omlx}"

OS="$(uname -s)"; ARCH="$(uname -m)"
MEM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))

echo "==> machine: $OS $ARCH, ${MEM_GB} GB unified memory"
if [ "$OS" != "Darwin" ] || [ "$ARCH" != "arm64" ]; then
  echo "FAIL: this recipe is Apple Silicon (Darwin arm64) only" >&2; exit 1
fi
if [ "$MEM_GB" -lt 128 ]; then
  echo "FAIL: measured shape needs 128 GB unified memory (found ${MEM_GB})" >&2; exit 1
fi

OMLX_BIN="${OMLX_BIN:-$HOME/.omlx/bin/omlx}"
MODEL_SRC="${MODEL_SRC:-$HOME/models/qwen38-flash-next-oq4e-mtp}"
MODEL_DIR="${MODEL_DIR:-$HOME/models/omlx-qwen38}"
PORT="${PORT:-8000}"
OMLX_VERSION_PIN="${OMLX_VERSION_PIN:-0.6.4}"
HF_REVISION_PIN="${HF_REVISION_PIN:-2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8}"

fail=0
if [ ! -x "$OMLX_BIN" ]; then
  echo "MISSING: oMLX CLI shim at $OMLX_BIN (see MODELS.md section 1)"; fail=1
else
  raw_ver="$("$OMLX_BIN" --version 2>/dev/null || true)"
  ver="$(printf '%s' "$raw_ver" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  echo "==> oMLX version: ${raw_ver:-unknown} (parsed ${ver:-none})"
  if [ "$ver" != "$OMLX_VERSION_PIN" ]; then
    echo "FAIL: oMLX version '$ver' != pin $OMLX_VERSION_PIN" >&2
    fail=1
  fi
fi
if [ ! -d "$MODEL_SRC" ]; then
  echo "MISSING: model dir $MODEL_SRC (see MODELS.md section 2)"; fail=1
else
  if [ ! -f "$MODEL_SRC/config.json" ]; then
    echo "FAIL: $MODEL_SRC has no config.json — not a checkpoint dir" >&2
    fail=1
  fi
  got=""
  if [ -f "$MODEL_SRC/.hf_revision" ]; then
    got="$(tr -d '[:space:]' < "$MODEL_SRC/.hf_revision")"
  fi
  if [ -z "$got" ]; then
    echo "FAIL: $MODEL_SRC/.hf_revision missing. After a pinned download, run:" >&2
    echo "      echo $HF_REVISION_PIN > $MODEL_SRC/.hf_revision" >&2
    fail=1
  elif [ "$got" != "$HF_REVISION_PIN" ]; then
    echo "FAIL: model revision '$got' != pin $HF_REVISION_PIN" >&2
    fail=1
  else
    echo "==> model revision $got (OK)"
  fi
  python3 - "$MODEL_SRC" "$(pwd)/files/SHA256SUMS" <<'PY'
import hashlib, sys
from pathlib import Path
root, manifest = Path(sys.argv[1]), Path(sys.argv[2])
bad = 0
for line in manifest.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    digest, name = line.split(None, 1)
    p = root / name
    if not p.is_file():
        print("FAIL: missing", name)
        bad += 1
        continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if h != digest:
        print("FAIL: SHA256 mismatch", name)
        bad += 1
if bad:
    raise SystemExit(1)
print("==> SHA256 manifest OK (%s)" % manifest)
PY
fi
[ "$fail" = "1" ] && exit 1

mkdir -p "$MODEL_DIR"
ln -sfn "$MODEL_SRC" "$MODEL_DIR/$(basename "$MODEL_SRC")"
echo "==> quarantine dir ready: $MODEL_DIR -> $(basename "$MODEL_SRC")"

mkdir -p "$OMLX_CONF/logs" "$OMLX_CONF/ssd-cache"
if [ -n "$STATE" ]; then
  echo "==> isolated state: $OMLX_CONF (will not patch ~/.omlx)"
  mkdir -p "$OMLX_CONF"
  if [ ! -f "$OMLX_CONF/settings.json" ] && [ -f "$HOME/.omlx/settings.json" ]; then
    cp "$HOME/.omlx/settings.json" "$OMLX_CONF/settings.json"
    echo "==> copied settings.json from ~/.omlx into --state (original left untouched)"
  fi
  if [ ! -f "$OMLX_CONF/model_settings.json" ] && [ -f "$HOME/.omlx/model_settings.json" ]; then
    cp "$HOME/.omlx/model_settings.json" "$OMLX_CONF/model_settings.json"
  fi
fi

# Missing configs are a FAIL. oMLX writes them on first start; stop the server
# and re-run setup.sh. Never exit 0 on a half-install.
if [ ! -f "$OMLX_CONF/settings.json" ]; then
  echo "FAIL: $OMLX_CONF/settings.json missing — start the server once so oMLX writes it, stop it, re-run setup.sh" >&2
  exit 1
fi
if [ ! -f "$OMLX_CONF/model_settings.json" ]; then
  echo "FAIL: $OMLX_CONF/model_settings.json missing — start the server once so oMLX writes it, stop it, re-run setup.sh" >&2
  exit 1
fi

python3 - "$OMLX_CONF/settings.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
changed = []
sch = cfg.setdefault("scheduler", {})
if not sch.get("chunked_prefill"):
    sch["chunked_prefill"] = True; changed.append("scheduler.chunked_prefill=true")
sch.setdefault("prefill_priority", "context")
sch.setdefault("decode_fairness", True)
if sch.get("max_concurrent_requests") != 8:
    sch["max_concurrent_requests"] = 8; changed.append("scheduler.max_concurrent_requests=8")
mem = cfg.setdefault("memory", {})
mem.setdefault("prefill_memory_guard", True)
mem.setdefault("memory_guard_tier", "balanced")
mem.setdefault("soft_threshold", 0.85)
mem.setdefault("hard_threshold", 0.95)
if changed:
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print("PATCHED settings.json:", ", ".join(changed))
else:
    print("settings.json already correct (chunked_prefill on, mc=8)")
PYEOF

python3 - "$OMLX_CONF/model_settings.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
models = cfg.setdefault("models", {})
found = False
for name, m in models.items():
    if "flash" in name.lower():
        if m.get("mtp_enabled") is not False:
            m["mtp_enabled"] = False
            print(f"PATCHED {name}: mtp_enabled=false (measured slower on this box)")
        m.setdefault("max_context_window", 262144)
        m.setdefault("qwen4_ple_ssd_offload", True)
        print(f"model entry {name}: mtp off, ctx 262144, PLE ssd offload — OK")
        found = True
        break
if not found:
    print("FAIL: no flash-next model entry in model_settings.json — start the server once so oMLX writes one, stop it, re-run setup.sh", file=sys.stderr)
    sys.exit(1)
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

for f in scripts/serve-flash.sh.in scripts/com.omlx.flash8slot.plist.in; do
  [ -f "$f" ] || { echo "MISSING: $f"; exit 1; }
done
sed -e "s|@OMLX@|$OMLX_BIN|g" \
    -e "s|@MODELDIR@|$MODEL_DIR|g" \
    -e "s|@HOME@|$HOME|g" \
    -e "s|@PORT@|$PORT|g" \
    scripts/serve-flash.sh.in > scripts/serve-flash.sh
chmod +x scripts/serve-flash.sh

if [ "$INSTALL_AGENT" = "1" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  sed -e "s|@OMLX@|$OMLX_BIN|g" \
      -e "s|@MODELDIR@|$MODEL_DIR|g" \
      -e "s|@HOME@|$HOME|g" \
      -e "s|@PORT@|$PORT|g" \
      scripts/com.omlx.flash8slot.plist.in > "$HOME/Library/LaunchAgents/com.omlx.flash8slot.plist"
  echo "WROTE LaunchAgent (opt-in appliance mode: KeepAlive + 30s throttle on a ~69 GB Metal process)"
  echo "  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.omlx.flash8slot.plist"
  echo "  launchctl bootout    gui/\$(id -u)/com.omlx.flash8slot"
else
  echo "NOTE: LaunchAgent not installed (pass --install-agent for KeepAlive appliance mode)."
fi

echo "PASS: prerequisites OK, config patched, scripts/serve-flash.sh written."
echo "Next steps:"
echo "  manual start :  bash scripts/serve-flash.sh    (foreground)"
echo "  verify       :  bash scripts/verify.sh"
echo "  acceptance   :  python3 scripts/warm-8slot.py   (~13 min; doubles as boot-warm)"
