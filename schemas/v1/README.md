# KALHAS v1 JSON Schema artifacts

Generated deterministically from the Pydantic v2 contracts in
`kalhas/contracts/v1/` by `scripts/export_schemas.py`. **Never edit these
files by hand.**

One artifact per top-level public contract (see `PUBLIC_CONTRACTS` in
`kalhas/contracts/v1/__init__.py`).

Regenerate after any contract change:

```powershell
uv run python scripts/export_schemas.py
```

Verify artifacts are current (fails with exit code 1 when out of sync):

```powershell
uv run python scripts/export_schemas.py --check
```

`tests/test_schema_sync.py` enforces synchronization in CI-style runs.
