## Summary

<!-- What does this PR change, in one or two sentences? -->

## Related issues

<!-- e.g. Fixes #123 -->

## Change type

- [ ] Kernel behavior (ships with tests)
- [ ] Contracts / schemas (generated artifacts regenerated; backward compatible)
- [ ] Documentation only
- [ ] Tooling / CI only

## Gates (all must pass locally before opening)

- [ ] `uv run pytest` (full suite)
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run mypy kalhas tests`
- [ ] `PYTHONPATH= uv run python scripts/export_schemas.py --check`
- [ ] `git diff --check`

## Truthfulness checklist

- [ ] No unsupported claims: deterministic replay and repository acceptance are not scientific validity, calibration, certification, or production readiness
- [ ] No `skip`, `xfail`, `noqa`, or `type: ignore` added to make gates pass
- [ ] No network, provider, or live actions introduced
- [ ] No real company or personal data in code, fixtures, docs, or tests
