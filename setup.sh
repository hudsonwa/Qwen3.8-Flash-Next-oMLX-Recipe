#!/usr/bin/env bash
# One-shot setup: oMLX 8-slot Flash-Next stack (default 1x252K head + short slots;
# historical dual 2x252K is a 2026-08-31 receipt, not the daily warm path)
# on a 128 GB Apple Silicon Mac. Checks prerequisites, patches oMLX config for
# chunked prefill + memory guard, renders the foreground launcher.
# Does NOT auto-start the server. Does NOT write a LaunchAgent unless
# --install-agent is passed (KeepAlive on a ~69 GB Metal process is opt-in).
set -euo pipefail
cd "$(dirname "$0")"

INSTALL_AGENT=0
STATE=""
BOOTSTRAP_CHECK=0
HOT_12G=0
PRINT_BOOTSTRAP=0
RESTORE=0
INIT_CONFIG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --install-agent) INSTALL_AGENT=1 ;;
    --bootstrap-check) BOOTSTRAP_CHECK=1 ;;
    --print-bootstrap) PRINT_BOOTSTRAP=1 ;;
    --hot-cache-12gb) HOT_12G=1 ;;
    --restore) RESTORE=1 ;;
    --init-config) INIT_CONFIG=1 ;;
    --state)
      shift
      STATE="${1:-}"
      [ -n "$STATE" ] || { echo "FAIL: gate=args --state needs a directory" >&2; exit 1; }
      ;;
    -h|--help)
      echo "usage: bash setup.sh [--install-agent] [--state DIR] [--bootstrap-check] [--print-bootstrap] [--hot-cache-12gb] [--restore] [--init-config]"
      echo "  --state DIR         isolated config dir (does not mutate ~/.omlx)"
      echo "  --bootstrap-check   dry run: same gates, no writes; names the missing gate on failure"
      echo "  --print-bootstrap   print BOOTSTRAP.md with pins filled in (no writes)"
      echo "  --hot-cache-12gb    optional one-brain RAM variant (not daily default)"
      echo "  --restore           restore settings.json / model_settings.json from newest *.bak.<utc>"
      echo "  --init-config       write minimal settings if missing (does not start oMLX)"
      echo "setup.sh is the config patcher. Fetch bits with scripts/fetch-pins.sh."
      exit 0
      ;;
    *) echo "FAIL: gate=args unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done
EXACT_MODEL_ID="qwen38-flash-next-oq4e-mtp"
OMLX_CONF="${STATE:-$HOME/.omlx}"
OMLX_BIN="${OMLX_BIN:-$HOME/.omlx/bin/omlx}"
MODEL_SRC="${MODEL_SRC:-$HOME/models/qwen38-flash-next-oq4e-mtp}"
MODEL_DIR="${MODEL_DIR:-$HOME/models/omlx-qwen38}"
PORT="${PORT:-8000}"
OMLX_VERSION_PIN="${OMLX_VERSION_PIN:-0.6.4}"
HF_REVISION_PIN="${HF_REVISION_PIN:-2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8}"
HF_ID="${HF_ID:-Jundot/Qwen3.8-Flash-Next-oQ4e-mtp}"
DMG_NAME="${OMLX_DMG_NAME:-oMLX-0.6.4-macos26-27.dmg}"
DMG_SHA="${OMLX_DMG_SHA:-53f1506c2385e8920a67198b72d1fe09351c1b3538be9c6bdeb78e5277d06d93}"
DMG_SIZE="${OMLX_DMG_SIZE:-805799490}"

if [ "$PRINT_BOOTSTRAP" = "1" ]; then
  echo "PINS filled in from this recipe:"
  echo "  oMLX_VERSION_PIN=$OMLX_VERSION_PIN"
  echo "  HF_ID=$HF_ID"
  echo "  HF_REVISION_PIN=$HF_REVISION_PIN"
  echo "  DMG_NAME=$DMG_NAME"
  echo "  DMG_SHA256=$DMG_SHA"
  echo "  DMG_SIZE_BYTES=$DMG_SIZE"
  echo "  EXACT_MODEL_ID=$EXACT_MODEL_ID"
  echo "  fetch: bash scripts/fetch-pins.sh"
  echo "  patch: bash setup.sh"
  echo "---- BOOTSTRAP.md ----"
  cat BOOTSTRAP.md
  exit 0
fi

OS="$(uname -s)"; ARCH="$(uname -m)"
MEM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))

echo "==> machine: $OS $ARCH, ${MEM_GB} GB unified memory"
if [ "$OS" != "Darwin" ] || [ "$ARCH" != "arm64" ]; then
  echo "FAIL: gate=darwin-arm64 this recipe is Apple Silicon (Darwin arm64) only" >&2; exit 1
fi
if [ "$MEM_GB" -lt 128 ]; then
  echo "FAIL: gate=mem-128 measured shape needs 128 GB unified memory (found ${MEM_GB})" >&2; exit 1
fi

fail=0
if [ ! -x "$OMLX_BIN" ]; then
  echo "FAIL: gate=omlx-cli MISSING oMLX CLI shim at $OMLX_BIN (see MODELS.md section 1)"; fail=1
else
  raw_ver="$("$OMLX_BIN" --version 2>/dev/null || true)"
  ver="$(printf '%s' "$raw_ver" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
  echo "==> oMLX version: ${raw_ver:-unknown} (parsed ${ver:-none})"
  if [ "$ver" != "$OMLX_VERSION_PIN" ]; then
    echo "FAIL: gate=omlx-version oMLX version '$ver' != pin $OMLX_VERSION_PIN" >&2
    fail=1
  fi
fi
if [ ! -d "$MODEL_SRC" ]; then
  echo "FAIL: gate=model-dir MISSING model dir $MODEL_SRC (see MODELS.md section 2)"; fail=1
else
  if [ ! -f "$MODEL_SRC/config.json" ]; then
    echo "FAIL: gate=config-json $MODEL_SRC has no config.json — not a checkpoint dir" >&2
    fail=1
  fi
  got=""
  if [ -f "$MODEL_SRC/.hf_revision" ]; then
    got="$(tr -d '[:space:]' < "$MODEL_SRC/.hf_revision")"
  fi
  if [ -z "$got" ]; then
    echo "FAIL: gate=hf-revision $MODEL_SRC/.hf_revision missing. After a pinned download, run:" >&2
    echo "      echo $HF_REVISION_PIN > $MODEL_SRC/.hf_revision" >&2
    fail=1
  elif [ "$got" != "$HF_REVISION_PIN" ]; then
    echo "FAIL: gate=hf-revision model revision '$got' != pin $HF_REVISION_PIN" >&2
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
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            b = fh.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    h = h.hexdigest()
    if h != digest:
        print("FAIL: SHA256 mismatch", name)
        bad += 1
if bad:
    raise SystemExit(1)
print("==> SHA256 manifest OK (%s)" % manifest)
PY
fi
[ "$fail" = "1" ] && exit 1

if [ "$RESTORE" = "1" ] && [ "$INIT_CONFIG" = "1" ]; then
  echo "FAIL: gate=args --restore and --init-config are mutually exclusive" >&2
  exit 1
fi

if [ "$RESTORE" = "1" ]; then
  python3 - "$OMLX_CONF" "$BOOTSTRAP_CHECK" <<'PY'
import sys
from pathlib import Path
conf = Path(sys.argv[1])
dry = sys.argv[2] == "1"
names = ("settings.json", "model_settings.json")
todo = []
for name in names:
    dest = conf / name
    cands = sorted(p for p in dest.parent.glob(name + ".bak.*") if p.is_file())
    if not cands:
        print("FAIL: gate=restore no bak for %s (looked for %s.bak.<utc>)" % (dest, name), file=sys.stderr)
        sys.exit(1)
    src = cands[-1]
    todo.append((src, dest))
for src, dest in todo:
    print("RESTORE src=%s dest=%s%s" % (src, dest, " (dry-run, no write)" if dry else ""))
    if not dry:
        dest.write_bytes(src.read_bytes())
if dry:
    print("PASS: --restore --bootstrap-check (no writes)")
    sys.exit(0)
print("PASS: restored %d file(s) from newest bak" % len(todo))
PY
  [ "$BOOTSTRAP_CHECK" = "1" ] && exit 0
fi

if [ "$INIT_CONFIG" = "1" ]; then
  python3 - "$OMLX_CONF" "$BOOTSTRAP_CHECK" "$EXACT_MODEL_ID" <<'PY'
import json, os, sys
from pathlib import Path
conf = Path(sys.argv[1])
dry = sys.argv[2] == "1"
exact = sys.argv[3]
settings = {
    "scheduler": {
        "chunked_prefill": True,
        "prefill_priority": "context",
        "decode_fairness": True,
        "max_concurrent_requests": 8,
    },
    "memory": {
        "prefill_memory_guard": True,
        "memory_guard_tier": "balanced",
        "soft_threshold": 0.85,
        "hard_threshold": 0.95,
    },
    "cache": {"hot_cache_max_size": "0"},
}
models = {
    "models": {
        exact: {
            "mtp_enabled": False,
            "max_context_window": 262144,
            "qwen4_ple_ssd_offload": True,
        }
    }
}
todo = [
    (conf / "settings.json", settings),
    (conf / "model_settings.json", models),
]
wrote = 0
for dest, obj in todo:
    if dest.exists():
        print("INIT-CONFIG keep existing %s" % dest)
        continue
    print("INIT-CONFIG write %s%s" % (dest, " (dry-run, no write)" if dry else ""))
    if dry:
        continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp." + str(os.getpid()))
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    os.replace(tmp, dest)
    wrote += 1
if dry:
    print("PASS: --init-config --bootstrap-check (no writes)")
    sys.exit(0)
print("PASS: --init-config (%d new file(s)); patcher can run; oMLX not started" % wrote)
PY
  [ "$BOOTSTRAP_CHECK" = "1" ] && exit 0
fi

if [ "$BOOTSTRAP_CHECK" = "1" ]; then
  if [ ! -f "$OMLX_CONF/settings.json" ]; then
    echo "FAIL: gate=settings.json $OMLX_CONF/settings.json missing — bash setup.sh --init-config" >&2
    exit 1
  fi
  if [ ! -f "$OMLX_CONF/model_settings.json" ]; then
    echo "FAIL: gate=model_settings.json $OMLX_CONF/model_settings.json missing — bash setup.sh --init-config" >&2
    exit 1
  fi
  echo "PASS: --bootstrap-check (no writes). A subsequent bash setup.sh would succeed on these gates."
  exit 0
fi

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

# Missing configs are a FAIL. --init-config writes the minimal JSON this
# recipe patches. Never start oMLX just to materialize settings. Never exit 0
# on a half-install.
if [ ! -f "$OMLX_CONF/settings.json" ]; then
  echo "FAIL: $OMLX_CONF/settings.json missing — bash setup.sh --init-config (does not start oMLX)" >&2
  exit 1
fi
if [ ! -f "$OMLX_CONF/model_settings.json" ]; then
  echo "FAIL: $OMLX_CONF/model_settings.json missing — bash setup.sh --init-config (does not start oMLX)" >&2
  exit 1
fi

python3 - "$OMLX_CONF/settings.json" "$HOT_12G" <<'PYEOF'
import json, os, sys, time
from pathlib import Path
path = Path(sys.argv[1])
hot12 = sys.argv[2] == "1"

def atomic_write(p: Path, obj):
    utc = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    bak = p.with_name(p.name + ".bak." + utc)
    bak.write_bytes(p.read_bytes())
    print("BACKUP", bak.name)
    tmp = p.with_name(p.name + ".tmp." + str(os.getpid()))
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    os.replace(tmp, p)

cfg = json.loads(path.read_text())
changed = []
sch = cfg.setdefault("scheduler", {})
if not sch.get("chunked_prefill"):
    sch["chunked_prefill"] = True
    changed.append("scheduler.chunked_prefill=true")
sch.setdefault("prefill_priority", "context")
sch.setdefault("decode_fairness", True)
if sch.get("max_concurrent_requests") != 8:
    sch["max_concurrent_requests"] = 8
    changed.append("scheduler.max_concurrent_requests=8")
mem = cfg.setdefault("memory", {})
mem.setdefault("prefill_memory_guard", True)
mem.setdefault("memory_guard_tier", "balanced")
mem.setdefault("soft_threshold", 0.85)
mem.setdefault("hard_threshold", 0.95)
cache = cfg.setdefault("cache", {})
want = "12GB" if hot12 else "0"
if str(cache.get("hot_cache_max_size")) != want:
    cache["hot_cache_max_size"] = want
    changed.append("cache.hot_cache_max_size=%s" % want)
if changed:
    atomic_write(path, cfg)
    print("PATCHED file=%s:" % path.name, ", ".join(changed))
else:
    print("settings.json already correct (chunked_prefill on, mc=8, hot=%s) file=%s" % (want, path.name))
PYEOF

python3 - "$OMLX_CONF/model_settings.json" "$EXACT_MODEL_ID" <<'PYEOF'
import json, os, re, sys, time
from pathlib import Path
path = Path(sys.argv[1])
exact = sys.argv[2]

def atomic_write(p: Path, obj):
    utc = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    bak = p.with_name(p.name + ".bak." + utc)
    bak.write_bytes(p.read_bytes())
    print("BACKUP", bak.name)
    tmp = p.with_name(p.name + ".tmp." + str(os.getpid()))
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    os.replace(tmp, p)

cfg = json.loads(path.read_text())
models = cfg.setdefault("models", {})
glm = [n for n in models if re.search(r"GLM-.*Flash", n, re.I)]
if glm:
    print("FAIL: refuse GLM-*-Flash entries: %s" % ", ".join(glm), file=sys.stderr)
    sys.exit(1)
flashish = [n for n in models if "flash" in n.lower()]
if exact not in models:
    print("FAIL: no exact model id %s in model_settings.json (have %s)" % (exact, flashish or list(models)), file=sys.stderr)
    sys.exit(1)
others = [n for n in flashish if n != exact]
if others:
    print("FAIL: second flash hit refused: %s (only %s is allowed)" % (", ".join(others), exact), file=sys.stderr)
    sys.exit(1)
m = models[exact]
if m.get("mtp_enabled") is not False:
    m["mtp_enabled"] = False
m.setdefault("max_context_window", 262144)
m.setdefault("qwen4_ple_ssd_offload", True)
atomic_write(path, cfg)
print("PATCHED file=%s model_id=%s mtp_enabled=false ctx=262144 PLE ssd offload" % (path.name, exact))
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
