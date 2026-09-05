#!/usr/bin/env bash
# Public-readiness sweep: fail if personal patterns appear in TRACKED files.
# Run before any push or visibility change. Exits 1 on any hit in tracked content.
set -u
cd "$(dirname "$0")/.." || exit 1
pats='joshua|hudsonwa|jhudson1980|mortimer|/Users/[a-z]+|\.hermes|exmachina'
# The repo's own public clone URL is public metadata on GitHub; strip the exact
# string before the sweep so copy-paste-clean quick start (issue #1) can exist.
# Everything else stays scrubbed. Keep this exclusion literal-exact.
own_repo_url='github\.com/hudsonwa/Qwen3\.8-Flash-Next-oMLX-Recipe'
hits=0
while IFS= read -r f; do
  # skip this script: its pattern list contains the literals by design
  [ "$f" = "scripts/check-scrub.sh" ] && continue
  m=$(sed -E "s|$own_repo_url|<OWN-REPO-URL>|g" -- "$f" 2>/dev/null | grep -inE "$pats" | head -3)
  if [ -n "$m" ]; then
    echo "HIT: $f"; echo "$m"; hits=$((hits+1))
  fi
done < <(git ls-files)
# commit-object identity: only commits this branch adds vs origin/main (or HEAD
# if that ref is missing). Full-history --all is a publish audit, not CI — old
# squash merges may carry the account mailbox; do not rewrite them.
range="HEAD"
if git rev-parse --verify origin/main >/dev/null 2>&1; then
  range="origin/main..HEAD"
fi
bad_ids=$(git log --format='%h %an %ae %cn %ce' "$range" | grep -viE 'users\.noreply\.github\.com|noreply@github\.com|noreply@users' || true)
if [ -n "$bad_ids" ]; then
  echo "HIT: non-neutral git identity in history:"; echo "$bad_ids"; hits=$((hits+1))
fi
if [ "$hits" -gt 0 ]; then
  echo "FAIL: ${hits} personal-pattern hit(s) — scrub before publishing." >&2
  exit 1
fi
echo "PASS: tracked files and git identities carry no personal patterns."
