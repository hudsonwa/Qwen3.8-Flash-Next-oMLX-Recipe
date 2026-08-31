#!/usr/bin/env bash
# One-shot setup: oMLX 8-slot Flash-Next stack (2x252K + 2x32K + 2x64K + 2x64K)
# on a 128 GB Apple Silicon Mac. Checks prerequisites, patches oMLX config for
# chunked prefill + memory guard, renders launchers and a launchd plist.
# Does NOT auto-start the server (see scripts/serve-flash.sh or the plist).
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
OMLX_BIN="${OMLX_BIN:-$HOME/.omlx/bin/omlx}"
MODEL_SRC="${MODEL_SRC:-$HOME/models/qwen38-flash-next-oq4e-mtp}"
MODEL_DIR="${MODEL_DIR:-$HOME/models/omlx-qwen38}"   # one-symlink quarantine dir
PORT="${PORT:-8000}"

# ---- checks ----------------------------------------------------------------
fail=0
if [ ! -x "$OMLX_BIN" ]; then
  echo "MISSING: oMLX CLI shim at $OMLX_BIN (see MODELS.md section 1)"; fail=1
else
  echo "==> oMLX version: $("$OMLX_BIN" --version 2>/dev/null || echo unknown)"
fi
if [ ! -d "$MODEL_SRC" ]; then
  echo "MISSING: model dir $MODEL_SRC (see MODELS.md section 2)"; fail=1
fi
[ "$fail" = "1" ] && exit 1

mkdir -p "$MODEL_DIR"
ln -sfn "$MODEL_SRC" "$MODEL_DIR/$(basename "$MODEL_SRC")"
echo "==> quarantine dir ready: $MODEL_DIR -> $(basename "$MODEL_SRC")"

# ---- oMLX config: chunked prefill + memory guard (THE lever) ---------------
mkdir -p "$HOME/.omlx/logs" "$HOME/.omlx/ssd-cache"
python3 - "$HOME/.omlx/settings.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    print(f"NOTE: {path} not found — start the server once, stop it, re-run setup.sh,"
          " then this script will patch the generated config.")
    sys.exit(0)
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

python3 - "$HOME/.omlx/model_settings.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        cfg = json.load(f)
except FileNotFoundError:
    print(f"NOTE: {path} not found — start the server once, stop it, re-run setup.sh.")
    sys.exit(0)
models = cfg.setdefault("models", {})
# find the flash-next entry (name may vary by checkpoint dir)
for name, m in models.items():
    if "flash" in name.lower():
        if m.get("mtp_enabled") is not False:
            m["mtp_enabled"] = False
            print(f"PATCHED {name}: mtp_enabled=false (measured slower on)")
        m.setdefault("max_context_window", 262144)
        m.setdefault("qwen4_ple_ssd_offload", True)
        print(f"model entry {name}: mtp off, ctx 262144, PLE ssd offload — OK")
        break
else:
    print("NOTE: no flash-next model entry found yet — server writes one on first start.")
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PYEOF

# ---- render launchers + launchd plist --------------------------------------
for f in scripts/serve-flash.sh.in scripts/com.omlx.flash8slot.plist.in; do
  [ -f "$f" ] || { echo "MISSING: $f"; exit 1; }
done
sed -e "s|@OMLX@|$OMLX_BIN|g" \
    -e "s|@MODELDIR@|$MODEL_DIR|g" \
    -e "s|@HOME@|$HOME|g" \
    -e "s|@PORT@|$PORT|g" \
    scripts/serve-flash.sh.in > scripts/serve-flash.sh
chmod +x scripts/serve-flash.sh
sed -e "s|@OMLX@|$OMLX_BIN|g" \
    -e "s|@MODELDIR@|$MODEL_DIR|g" \
    -e "s|@HOME@|$HOME|g" \
    -e "s|@PORT@|$PORT|g" \
    scripts/com.omlx.flash8slot.plist.in > "$HOME/Library/LaunchAgents/com.omlx.flash8slot.plist"

echo "PASS: prerequisites OK, config patched, launchers written."
echo "Next steps:"
echo "  manual start :  bash scripts/serve-flash.sh    (foreground)"
echo "  boot start   :  launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.omlx.flash8slot.plist"
echo "                  (RunAtLoad + KeepAlive — starts now and at every login;"
echo "                   do NOT also run serve-flash.sh, the port conflict kills the newcomer)"
echo "  verify       :  bash scripts/verify.sh"
echo "  acceptance   :  python3 scripts/warm-8slot.py   (~13 min; doubles as boot-warm)"
