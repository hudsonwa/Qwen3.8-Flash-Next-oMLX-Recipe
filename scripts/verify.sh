#!/usr/bin/env bash
# Fail-closed post-boot verification for the oMLX 8-slot flash stack.
# Exits 1 on any miss. Safe to re-run any time.
set -u
PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
fails=0
say() { printf '==> %s\n' "$*"; }
miss() { printf 'FAIL: %s\n' "$*" >&2; fails=$((fails+1)); }

# 1. API up + advertised context (settings-file ctx caps are NOT ground truth)
models_json="$(curl -s -m 5 "$BASE/v1/models" 2>/dev/null || true)"
if [ -z "$models_json" ]; then
  miss "API not reachable on ${BASE}"; 
else
  ctx="$(printf '%s' "$models_json" | /usr/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print(max(m.get("max_model_len",0) for m in d["data"]))' 2>/dev/null || echo 0)"
  if [ "$ctx" -ge 262144 ]; then say "ctx advertised: ${ctx} (OK)"; else miss "advertised ctx ${ctx} < 262144"; fi
fi

# 2. Server process + real footprint (never RSS)
pid="$(lsof -tnP -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
if [ -z "$pid" ]; then
  miss "no process listening on :${PORT}"
else
  fp="$(/usr/bin/footprint "$pid" 2>/dev/null | awk '/phys_footprint:/ {print $2}' | head -1)"
  case "${fp:-}" in
    ''|*[!0-9]*) miss "could not read footprint for pid ${pid}" ;;
    *) say "phys_footprint: ${fp} GB (idle expectation ~69 GB)" ;;
  esac
fi

# 3. Live generation (small, streamed, must return tokens) — oMLX requires the
#    "model" field; resolve it from /v1/models instead of hardcoding.
mname="$(printf '%s' "$models_json" | /usr/bin/python3 -c 'import json,sys;print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || true)"
if [ -z "$mname" ]; then miss "could not resolve model name from /v1/models"; fi
gen="$(curl -s -m 60 "$BASE/v1/chat/completions" -H 'Content-Type: application/json' \
  -d "{\"model\":\"${mname}\",\"max_tokens\":8,\"temperature\":0,\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: READY\"}]}" \
  | /usr/bin/python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"][:40])
except Exception: print("")' 2>/dev/null)"
if [ -n "$gen" ]; then say "live generation: ${gen}"; else miss "live generation returned nothing"; fi

# 4. Boot log: enforcer line (rotation-aware — oMLX rotates server.log at midnight,
#    so the boot-time line may live in the rotated file)
log_newest="$(ls -t "$HOME"/.omlx/logs/server.log* 2>/dev/null | head -2)"
if [ -n "${log_newest:-}" ]; then
  if cat $log_newest | grep -q "memory enforcer started"; then
    say "enforcer line found in $(echo $log_newest | tr ' ' ',')"
  else
    miss "enforcer line not found in newest server logs"
  fi
else
  say "NOTE: no ~/.omlx/logs/server.log* yet — skipping log check"
fi

if [ "$fails" -gt 0 ]; then
  printf '%s\n' "FAIL: ${fails} check(s) failed — fix before relying on the stack." >&2
  exit 1
fi
echo "PASS: all checks green."
