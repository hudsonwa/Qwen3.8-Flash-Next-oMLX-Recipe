# Profiles

Canonical serving numbers: **[PROFILE.md](PROFILE.md)**.
Pin tuple (oMLX / HF rev / hot / MTP / mc): **[COMPAT.md](COMPAT.md)**.

This file is a stub. Do not keep a second copy of daily walls here.

- **Daily serving:** 1×252K head + short slots, hot=0, `max_concurrent_requests=8`, MTP off, oMLX 0.6.4.
- **Optional 12 GB hot:** one-brain variant in PROFILE.md — not the daily default.
- **Interactive MTP:** named second profile only (`omlx-config.py --mode interactive --apply`). Filename `-mtp` is not activation. Leave MTP off on the daily stack.

## Admission only (same engine)

Optional client send-caps. They do **not** pin KV and do **not** load
another model. The engine still advertises 262144.

| Name | Send-cap | Meaning |
|---|---|---|
| `flash:planner` | 120k | Clients should not send more than ~120k |
| `flash:worker` | 32k | Clients should not send more than ~32k |
| `flash:chat` | 32k | Clients should not send more than ~32k |

These are send-caps, not `max_context_window` pins. TRAPS #2: a per-model
cap can silently fail to apply; trust `/v1/models`. See
[PREFIX_POLICY.md](PREFIX_POLICY.md).
