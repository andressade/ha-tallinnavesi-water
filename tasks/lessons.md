# Lessons

- Before claiming confidence, stand up a runnable local test environment with `uv` and execute the suite; `compileall` alone is not enough.
- When new API specs arrive, verify setup logic against the authoritative discovery endpoint, not descriptive fields like `meterType` that may change semantics.
- ASTV `GetSmartMeterReadings` may return `500 Internal server error` when `from/to` filters are sent even though the spec documents them, and can ignore `pageNo/pageSize`; request without date filters, use `orderBy=ReadingDate DESC`, filter client-side, and guard pagination against duplicate pages.
