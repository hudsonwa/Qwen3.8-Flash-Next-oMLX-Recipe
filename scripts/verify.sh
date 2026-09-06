#!/usr/bin/env bash
# Fail-closed post-boot verification for the oMLX 8-slot flash stack.
# Exits 1 on any miss. Safe to re-run any time.
set -u
PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
HERE="$(cd "$(dirname "$0")" && pwd)"
fails=0
say() { printf '==> %s\n' "$*"; }
miss() { printf 'FAIL: %s\n' "$*" >&2; fails=$((fails+1)); }

# 1. API up + advertised context (settings-file ctx caps are NOT ground truth)
models_json="$(curl -s -m 5 "$BASE/v1/models" 2>/dev/null || true)"
if [ -z "$models_json" ]; then
  miss "API not reachable on ${BASE}"
else
  ctx="$(printf '%s' "$models_json" | /usr/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(max(m.get("max_model_len",0) for m in d["data"]))' 2>/dev/null || echo 0)"
  if [ "$ctx" -ge 262144 ]; then say "ctx advertised: ${ctx} (OK)"; else miss "advertised ctx ${ctx} < 262144"; fi
fi

# 2. Server process + real footprint (never RSS). Accept 69, 69.2, 69G, 69000000000.
pid="$(lsof -tnP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
if [ -z "$pid" ]; then
  miss "no process listening on :${PORT}"
else
  fp_line="$(/usr/bin/footprint "$pid" 2>/dev/null | awk '/phys_footprint:/ {print $0}' | head -1)"
  gb="$(printf '%s' "$fp_line" | /usr/bin/python3 -c '
import re,sys
s=sys.stdin.read()
m=re.search(r"phys_footprint:\s*([0-9.]+)\s*([KMGTPE]i?B?)?", s, re.I)
if not m:
    print(""); sys.exit(0)
n=float(m.group(1)); u=(m.group(2) or "G").upper()
mult={"B":1/1e9,"K":1/1e6,"KB":1/1e6,"KI":1/1024**3*1024,"M":1/1e3,"MB":1/1e3,"G":1,"GB":1,"T":1e3,"TB":1e3}
# numeric already in GB on macOS footprint(1) default; if unit missing treat as GB
if m.group(2) is None:
    print(f"{n:.2f}")
elif n > 1000 and u.startswith("G"):
    # already GB-like
    print(f"{n:.2f}")
else:
    print(f"{n * mult.get(u,1):.2f}")
' 2>/dev/null || true)"
  if [ -z "$gb" ]; then
    miss "could not parse footprint for pid ${pid} (line: ${fp_line:-empty})"
  else
    say "phys_footprint: ${gb} GB (idle expectation ~69 GB)"
  fi
fi

# 3. Live generation — same model id resolver as warm-8slot.py
export PORT
mname="$(OMLX_REQUIRE_LIVE=1 /usr/bin/python3 "$HERE/resolve_model.py" 2>/dev/null || true)"
if [ -z "$mname" ]; then miss "could not resolve model name from /v1/models"; fi
gen="$(curl -s -m 60 "$BASE/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"${mname}\",\"max_tokens\":8,\"temperature\":0,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: READY\"}]}" \
  | /usr/bin/python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"][:40])
except Exception: print("")' 2>/dev/null)"
if [ -n "$gen" ]; then say "live generation: ${gen}"; else miss "live generation returned nothing"; fi

# 4. Live chunked_prefill in settings.json
if [ -f "$HOME/.omlx/settings.json" ]; then
  chunked="$(/usr/bin/python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get("scheduler",{}).get("chunked_prefill")).lower())' "$HOME/.omlx/settings.json" 2>/dev/null || echo "")"
  if [ "$chunked" = "true" ]; then say "settings.json chunked_prefill: true"; else miss "chunked_prefill is not true in settings.json (got ${chunked:-empty})"; fi
else
  miss "settings.json missing — cannot confirm chunked_prefill"
fi

# 5. Enforcer line from THIS boot (log mtime/start vs process start), not a rotated yesterday file
if [ -n "${pid:-}" ]; then
  /usr/bin/python3 - "$pid" "$HOME/.omlx/logs" <<'PY' || miss "enforcer line not from this boot"
import os, sys, time, glob, subprocess
pid = sys.argv[1]
logdir = sys.argv[2]
et = subprocess.check_output(["ps", "-p", pid, "-o", "etime="], text=True).strip()
if "-" in et:
    days, rest = et.split("-", 1)
    days = int(days)
else:
    days = 0
    rest = et
parts = [int(x) for x in rest.split(":")]
while len(parts) < 3:
    parts.insert(0, 0)
h, m, s = parts[-3:]
start = time.time() - (int(days) * 86400 + h * 3600 + m * 60 + s)
needle = "memory enforcer started"
found = False
paths = sorted(glob.glob(os.path.join(logdir, "server.log*")), key=os.path.getmtime, reverse=True)[:4]
for p in paths:
    try:
        with open(p, "r", errors="replace") as f:
            text = f.read()
    except OSError:
        continue
    if needle not in text:
        continue
    if os.path.getmtime(p) >= start - 120:
        print("==> enforcer line found in", p, "(this boot)")
        found = True
        break
if not found:
    sys.exit(1)
PY
else
  miss "no pid — skipped this-boot enforcer check"
fi

# 6. Port owner is the omlx server, not a random listener
if [ -n "${pid:-}" ]; then
  comm="$(ps -p "$pid" -o comm= 2>/dev/null | tr -d ' ')"
  case "$comm" in
    *omlx*) say "port owner: ${comm} pid ${pid}" ;;
    *) miss "port :${PORT} owner is '${comm}', want omlx*" ;;
  esac
fi

# 7. No second GPU-heavy sibling (omlx/mlx-serve/mtplx besides this pid)
extras="$(ps -axo pid=,comm= | awk -v keep="${pid:-0}" '
  $1==keep {next}
  $2 ~ /omlx-server|mlx-serve|mtplx/ {print $1,$2}
')"
if [ -n "$extras" ]; then
  miss "second GPU hog running: ${extras}"
else
  say "no second omlx/mlx-serve/mtplx process"
fi

# 8. >=100 GB free on the ssd-cache volume
cache_dir="${OMLX_SSD_CACHE:-$HOME/.omlx/ssd-cache}"
if [ ! -d "$cache_dir" ]; then
  miss "ssd-cache dir missing"
else
  free_gb="$(df -k "$cache_dir" | /usr/bin/python3 -c 'import sys
lines=sys.stdin.read().strip().splitlines()
parts=lines[-1].split()
print(int(parts[3])//1048576)')"
  if [ "${free_gb:-0}" -ge 100 ]; then
    say "ssd-cache free: ${free_gb} GB (>=100)"
  else
    miss "ssd-cache free ${free_gb} GB < 100"
  fi
fi

if [ "$fails" -gt 0 ]; then
  printf '%s\n' "FAIL: ${fails} check(s) failed — fix before relying on the stack." >&2
  exit 1
fi
echo "PASS: all checks green."
