#!/usr/bin/env bash
# Public-readiness sweep: fail if personal patterns appear in TRACKED files.
# Run before any push or visibility change. Exits 1 on any hit in tracked content.
set -u
cd "$(dirname "$0")/.."
pats='joshua|hudsonwa|jhudson1980|mortimer|/Users/[a-z]+|\.hermes|exmachina'
hits=0
while IFS= read -r f; do
  m=$(grep -inE "$pats" -- "$f" 2>/dev/null | head -3)
  if [ -n "$m" ]; then
    echo "HIT: $f"; echo "$m"; hits=$((hits+1))
  fi
done < <(git ls-files)
# commit-object identity check (published metadata, not just working tree)
bad_ids=$(git log --format='%h %an %ae %cn %ce' --all | grep -viE 'noreply@users' || true)
if [ -n "$bad_ids" ]; then
  echo "HIT: non-neutral git identity in history:"; echo "$bad_ids"; hits=$((hits+1))
fi
if [ "$hits" -gt 0 ]; then
  echo "FAIL: ${hits} personal-pattern hit(s) — scrub before publishing." >&2
  exit 1
fi
echo "PASS: tracked files and git identities carry no personal patterns."
