# PREFIX_POLICY

Frozen **system + tools first**. Volatile user / session / salt **last**.
The frozen head is shared across orchestrator, worker, auditor, and chat.

## Split salt

| Context | Prefix bytes | Tail |
|---|---|---|
| **Production** | **Byte-identical** across orch / worker / auditor / chat | no `[variant]` |
| **Benchmark** | Same frozen head as the test under study | `[variant <tag>]` on the tail only |

Do not salt production. A unique header salt makes every call a miss.

## Failure table

| Failure | What happens |
|---|---|
| Two different 240k systems | Prefix bytes differ → miss (hot=0 class ~229–256 s TTFT) |
| Per-role heads | Each role keeps its own 240k prefix → four caches, not one shared head |
| Edit-at-top | Changing system or tools at the start invalidates the whole prefix → miss |

Disk vs RAM vs miss walls are **config-specific**. The 8.7 s / 229 s and
8.3–9.0 s / 256 s cites were measured with the hot tier **off / unset**.
See [PROFILE.md](PROFILE.md).
