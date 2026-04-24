- [x] Read `specs/` and map new API differences against current integration
- [x] Switch API client to the new Tallinna Vesi base URL and compatible request params
- [x] Stop config flow from depending on legacy overview `meterType == "smart"` values
- [x] Add regression tests for new API assumptions and config-flow meter selection logic
- [x] Update user-facing docs/version for the new API migration
- [x] Run verification and capture results

## Review

- `python3 -m compileall custom_components tests` passed
- `uv run --python 3.12 --with pytest --with pytest-asyncio --with homeassistant==2024.8.3 --with josepy==1.15.0 python -m pytest -q` passed (`16 passed`)
- live smoke on 2026-04-24: ASTV returned `200` for overview and supply points; `GetSmartMeterReadings` returned readings when called without `from/to` filters
