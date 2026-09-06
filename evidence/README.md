# evidence/

Raw lab dumps only: SSE traces, server logs, scratch prefixes.

**Not published.** Keep out of git (see `.gitignore`: `evidence/*/` except this
README). Do not put stamped `results/*.json` copies here — that would be a
second receipt store, and `scripts/check-results.py` fails the tree if
`evidence/` still has JSON.

Published numbers belong in [`results/`](../results/README.md).
