# Changelog

## profile-1.2.0-2026-09-07

Daily serving is unchanged: **1×252K head + short slots**, MTP **off**,
`hot_cache_max_size=0`, `max_concurrent_requests=8`, oMLX **0.6.4**.

- `results/decode_table.json` published (n=3, solo + short8, 128 GB Mac)
- `results/quality_canary.json` published (fail-closed; not a full eval harness)
- mlx-serve: no receipt, no claim
- Hardware matrix, short README, warm `--out` gate, public receipt template

## profile-1.1.0-2026-09-06

Daily serving is unchanged: **1×252K head + short slots**, MTP **off**,
`hot_cache_max_size=0`, `max_concurrent_requests=8`, oMLX **0.6.4**.

- **#48** (optional, not default): `--hot-cache-max-size 12GB` after a cold
  miss (hits 2.45–2.76 s, peak 91 GB) is pre-register **inconclusive** (2–6 s),
  not RAM. A-B-A-B on the resident prefix did not win
  (`results/hot_cache_one_brain.json`). Daily disk path remains hot=0.
- BOOTSTRAP.md + fail-closed `setup.sh --bootstrap-check`
- Canonical numbers: `docs/PROFILE.md`
- Decode protocol: `docs/DECODE.md` (`decode_table.json` still not in git)
- Results schema CI: `scripts/check-results.py`

Profile changes increment this version.
