# COMPAT

Measured shape is **this tuple**. Change any field → re-measure. Do not
copy numbers across.

- **oMLX 0.6.4** — any other version = re-measure
- **HF revision** `2615fc0e976e65c2f3b55daca3a948f1cdc5b9f8` (`MODELS.md`)
- **Quant layout** oQ4e-mtp (filename `-mtp` is not activation)
- **hot_cache_max_size** `"0"` (daily) vs `"12GB"` (optional one-brain) are
  **different profiles**. Do not average them.
- **max_concurrent_requests=8**, chunked_prefill on, MTP off
- Dedicated **128 GB** Apple Silicon, Metal cap ≈ 107.5 GB

See [PROFILE.md](PROFILE.md) for the locked table.
