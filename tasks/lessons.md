# Lessons

- Before claiming confidence, stand up a runnable local test environment with `uv` and execute the suite; `compileall` alone is not enough.
- When new API specs arrive, verify setup logic against the authoritative discovery endpoint, not descriptive fields like `meterType` that may change semantics.
