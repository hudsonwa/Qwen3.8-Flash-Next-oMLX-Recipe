# PRIVACY — KV on disk is the private-server gap

This recipe does **not** encrypt prompt-derived state. oMLX’s SSD KV/prefix
cache is the gap. FileVault (or equivalent full-disk encryption) is **assumed**
on the Mac. This repository does not provide it.

No crypto is implemented here on purpose.

## What sits on disk

oMLX spills prefix cache and paged KV to:

```
~/.omlx/ssd-cache
```

(or `--paged-ssd-cache-dir` / `--state DIR` if you pointed the server elsewhere).

That directory is **prompt-derived data at rest**. Completions you served,
system prefixes you warmed, and KV pages from those prompts can remain after
the HTTP request ends. The files persist **across reboots**. This recipe does
not encrypt them.

`ssd_cache_max_size: "auto"` resolved on the reference box to a **self-managed
LRU** with a measured cap of **~185.8 GB**. Eviction is native. Disk filling
to that cap is by design — see [TRAPS.md](TRAPS.md) #12.

## Capacity is not a wipe

**Keep ~100 GB free** on the SSD-cache volume is a **capacity** rule
(`scripts/verify.sh` gate). It is **not** a confidentiality wipe. Free space
does not mean old KV is gone. LRU eviction is not a delete-on-idle policy you
can cite as sanitization.

## Wipe (server stopped first)

Do **not** hand-delete cache files while the server holds the port. That is a
corruption / race (TRAPS #12).

1. Stop by port (killing the `omlx serve` wrapper is not enough):

   ```bash
   kill -TERM $(lsof -tnP -iTCP:8000 -sTCP:LISTEN)
   ```

2. Confirm the port is free (must print nothing):

   ```bash
   lsof -nP -iTCP:8000 -sTCP:LISTEN
   ```

3. Remove the live cache directory, then recreate the empty dir if you still
   use the default path:

   ```bash
   CACHE="${OMLX_SSD_CACHE:-$HOME/.omlx/ssd-cache}"
   rm -rf "$CACHE"
   mkdir -p "$CACHE"
   ```

   If the process was started with `--paged-ssd-cache-dir`, wipe **that** path
   instead of the default.

4. Reboot is optional. It does **not** replace step 3.

This deletes the local SSD KV/prefix cache only. It does not uninstall oMLX,
does not delete weights, and does not disable FileVault.

## What this recipe does not do

- No at-rest encryption of `ssd-cache`
- No key management
- No claim that FileVault is configured
- No multi-tenant isolation

If the Mac is shared, treat `ssd-cache` as sensitive as the prompts you sent.
