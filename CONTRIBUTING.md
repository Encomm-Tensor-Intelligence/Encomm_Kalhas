# Contributing to KALHAS

Thank you for considering a contribution. KALHAS is developed under a strict,
test-first discipline; this document summarizes what a contribution must
satisfy. The durable repository rules live in [`AGENTS.md`](AGENTS.md).

## Ground rules

- **Three roles only.** NEXUS (dialogue/presentation), LEGION
  (strategy/exploration), and KALHAS (world models, uncertainty, campaigns,
  evidence, replay). Do not introduce new components or integration surfaces.
- **Domain-neutral kernel.** The `kalhas/` core contains no domain-specific
  logic; domain concerns arrive only as declarative domain packs behind the
  `DomainPack` protocol.
- **No new coupling.** KALHAS core never imports NEXUS or LEGION internals;
  the only allowed coupling is the adapter protocols in `kalhas/adapters/`.
- **No live actions.** No network calls, provider calls, telemetry, or
  real-world effects from the running application or tests.
- **Backward compatibility.** Contracts under `kalhas/contracts/v1/` are
  frozen once shipped. Breaking changes require a new version module and API
  segment — never in-place mutation.
- **Deterministic replay and fair comparison are mandatory.** Any simulation
  behavior must be reproducible from recorded models and seeds, and strategy
  comparisons must share identical recorded conditions.

## Workflow

1. Open an issue or claim an existing one before significant work.
2. Create a feature branch from `main`.
3. Make the change with tests: **every behavioral change ships with tests.**
4. Run the full gate locally (below) and ensure every command passes.
5. Open a pull request using the repository template, describing the change,
   the evidence, and the gate results.
6. Respond to review; CI must be green before merge.

## Gates (all required)

```bash
uv run pytest                              # full suite
uv run ruff check .                        # lint
uv run ruff format --check .               # formatting
uv run mypy kalhas tests                   # strict typing
PYTHONPATH= uv run python scripts/export_schemas.py --check   # schema sync
```

Additional change-specific rules:

- JSON Schema artifacts under `schemas/v1/` are **generated**. Never edit them
  by hand; change the contracts and re-run
  `uv run python scripts/export_schemas.py`.
- Do not add `skip`, `xfail`, `noqa`, `type: ignore`, or suppressed
  diagnostics to make gates pass.
- No real company or personal data in code, fixtures, docs, or tests.
- Determinism: no wall-clock calls, no randomness without a recorded seed, no
  hidden environment dependence in `kalhas/` production code.

## Commit and pull-request style

- Concise, imperative commit messages (for example
  `Phase 28: deterministic adaptive runtime and closure`).
- One logical change per pull request; keep diffs reviewable.
- State truthfully what is proven and what is not: deterministic replay and
  repository acceptance are not scientific validity, calibration, or
  production readiness.

## License note

No license has been selected for this repository yet. Until one is added, all
rights are reserved by the repository owner and contributions cannot be
redistributed under an open license.
