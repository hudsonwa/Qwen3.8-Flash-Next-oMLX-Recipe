#!/usr/bin/env bash
# Post-boot verification: cache lines, footprints, ports, one live generation.
# Fail-closed: any miss exits 1.
set -u
FLASH_LOG="${FLASH_LOG:-/tmp/qwen38-stack/flash.log}"
B27_LOG="${B27_LOG:-/tmp/qwen38-stack/27b.log}"
fail=0

cache_ok() { grep -q "Hot prefix cache: ENABLED" "$1" 2>/dev/null; }

echo "==> 1) boot-log cache lines"
for side in flash 27b; do
  log=$([ "$side" = flash ] && echo "$FLASH_LOG" || echo "$B27_LOG")
  if cache_ok "$log"; then echo "  $side: ENABLED ✓"
  else echo "  $side: NO 'Hot prefix cache: ENABLED' in $log ✗"; fail=1; fi
done

echo "==> 2) ports listening"
for p in 10099 10012; do
  if lsof -tnP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then echo "  :$p listening ✓"
  else echo "  :$p NOT LISTENING ✗"; fail=1; fi
done

echo "==> 3) footprints (phys_footprint GB; idle expect flash ~68, 27b ~16-17)"
for p in 10099 10012; do
  pid=$(lsof -tnP -iTCP:$p -sTCP:LISTEN 2>/dev/null | head -1)
  [ -z "$pid" ] && continue
  fp=$(footprint "$pid" 2>/dev/null | awk '/phys_footprint/{print $NF}')
  [ -z "$fp" ] && fp=$(ps -o rss= -p "$pid" | awk '{printf "%.1f (RSS! use footprint)", $1/1048576}')
  echo "  :$p pid $pid → ${fp:-?} GB"
done

echo "==> 4) one live generation per port"
key="${API_KEY:-$([[ -f "$HOME/.config/qwen38-stack/key" ]] && cat "$HOME/.config/qwen38-stack/key")}"
for p in 10099 10012; do
  out=$(curl -s --max-time 60 "http://127.0.0.1:$p/v1/chat/completions" \
    -H "Authorization: Bearer ${key:-change-me}" \
    -H "Content-Type: application/json" \
    -d '{"model":"x","messages":[{"role":"user","content":"Say OK"}],"max_tokens":8}')
  if echo "$out" | grep -q '"content"'; then echo "  :$p responded ✓"
  else echo "  :$p no completion ✗"; fail=1; fi
done

[ "$fail" = 0 ] && echo "VERIFY: PASS" || { echo "VERIFY: FAIL"; exit 1; }
