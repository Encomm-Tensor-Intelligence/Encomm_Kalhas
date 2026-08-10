# AGENTS.md

Durable rules for anyone (human or agent) working in this repository.

## Architecture roles

- **NEXUS** owns natural-language dialogue, organizational context, memory, and presentation.
- **LEGION** owns strategy and agent exploration.
- **KALHAS** owns versioned world models, uncertainty, deterministic simulation
  campaigns, evidence, replay, and the future living-simulation experience.
- No other components exist. Do not introduce new components or integration
  surfaces; the three named roles are the only allowed ones.

## Hard rules

1. **Domain-neutral kernel.** The `kalhas/` core contains no domain-specific
   logic. All domain concerns arrive only as domain packs under
   `kalhas/domain_packs/`, which the kernel consumes solely through the
   `DomainPack` protocol.
2. **No imports of NEXUS/LEGION internals.** KALHAS core never imports NEXUS or
   LEGION modules. The only allowed coupling is the placeholder protocols in
   `kalhas/adapters/` (`NexusAdapter`, `LegionAdapter`).
3. **Deterministic replay and fair strategy comparison are mandatory.** Any
   future simulation campaign must be reproducible from a recorded world model
   and seed; strategy comparisons must share identical conditions.
4. **No live actions in the MVP.** No network calls, provider calls, or
   real-world effects. Local development only; no external provider
   configuration.
5. **Versioned public contracts remain backward compatible.** Contracts under
   `kalhas/contracts/v1/` are frozen once shipped. Breaking changes require a
   new version module (`v2`, ...) and a new API version segment - never
   in-place mutation.
6. **Tests accompany behavioral changes.** Every behavior change ships with
   tests; `pytest`, `ruff`, and `mypy` must pass before finishing.

## Data hygiene

- No real company or personal data in code, fixtures, docs, or tests.
- No network calls or live providers from the running application.

## Gates (run before finishing any change)

```powershell
uv run pytest
uv run ruff check .
uv run mypy kalhas tests
```
