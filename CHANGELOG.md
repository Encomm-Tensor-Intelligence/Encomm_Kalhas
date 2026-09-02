# Changelog

All notable changes to KALHAS are recorded here. KALHAS develops in numbered,
gate-verified phases; each phase closes with a full-suite gate run and an
independent audit before it is committed to `main`.

## [Phase 28] — 2026-09-02

### Added

- Adaptive deterministic runtime `4.0.0` on top of runtime `3.0.0`
  (`H28-S01`–`H28-S13`): causal mid-run observation events under the frozen
  `kalhas-observation-noise-v1` coordinate, a closed bounded policy AST (no
  expressions, callbacks, imports, or LLM calls), immutable bound adaptive
  policies, policy decision/switch evidence with dwell/cooldown/budget
  semantics, adaptive trajectory execution with exact replay, and
  adaptive-versus-static comparison evidence under identical shared
  coordinates.
- Five top-level public v1 contracts (indexes 50–54, 55 total):
  `RuntimeObservationDeclaration`, `ExternalObservationInputBundle`,
  `AdaptivePolicy`, `AdaptiveRunTrajectoryExecution`,
  `AdaptiveRunTrajectoryReplayManifest`, with five synchronized JSON Schema
  artifacts (55 artifacts; 56 files in `schemas/v1/`).
- Three read-only adaptive API paths:
  `/v1/runs/{run_id}/adaptive/{observations,decisions,switches}`.
- ADR 004: deterministic adaptive runtime design decisions (D28-01–D28-04).
- Unpatched exact-five-plus-adaptive acceptance proof (24 focused tests)
  through the real services: causal switching, paired comparison evidence,
  exact replay, tenant isolation, adversarial rejection.
- Repository presentation: banner, condensed README, this changelog,
  contributing/security guides, issue/PR templates, and a CI workflow.

### Verified

- Full suite: 6,850 tests, 0 failures, 0 errors, 0 skipped (Codex-owned
  `CP28-B` audit run, 2026-09-02).
- Ruff check, Ruff format check, strict mypy (340 source files), and
  schema-export `--check` all green.
- `CP28-B` accepted by the independent Codex audit on 2026-09-02.

### Committed

- `f001d5f027cf21e8964eac72f122730e98ebdd3d` — Phase 28: deterministic
  adaptive runtime and closure.

## [Gate 27.1] — 2026-08-25

### Added

- Truthful-baseline closure: active-documentation truth with boundary
  assertions, the architecture-policy conflict resolution, and the unpatched
  exact-five trajectory-plan acceptance proof with permanent closure
  boundaries (`tests/test_phase27_1_boundaries.py`).

### Verified

- Full suite: 5,480 tests, 0 failed, 0 skipped (Codex-owned run).

### Committed

- `777a4472ef0d1edc6d30ce61a05851302b981027` — Gate 27.1: truthful baseline
  closure.

## [Phase 27] — 2026-08-25

### Added

- Evidence-based campaign decision support: immutable per-campaign decision
  policies, paired same-seed strategy comparisons (weighted regret, minimax
  robustness, Pareto dominance), deterministic decision briefs, explicit
  terminal states, read-only verified query services, and a 100-seed causal
  acceptance proof.
- Contracts: `CampaignDecisionPolicy`, `CampaignStrategyComparison`,
  `CampaignDecisionBrief` (indexes 47–49).

### Committed

- `a905d2af6b155a0f2568037e2b0f410b20be8d91` — Phase 27: evidence-based
  campaign decision support.

## [Phase 26] — 2026-08-16

### Added

- Empirical campaign outcome distributions: exact ordered samples, empirical
  distribution statistics, Hyndman-Fan Type-7 quantiles, fixed-alpha
  (`0.95`) adverse-tail and target-violation CVaR evidence, one-ULP
  golden-test discipline, and the `CampaignOutcomeDistributionMatrix`
  contract (index 46).

### Committed

- `886f398c288971d612fa57bd1d1e731113a69f72` — Phase 26: empirical campaign
  outcome distributions.

## [Phase 25] — 2026-08-14

### Added

- Realization-aware runtime `3.0.0`: deterministic realizations bound to
  recorded scenario seeds, realization trajectory execution and replay,
  strategy trajectory plans, and campaign trajectory matrices under fair
  identical-condition invariants.

### Committed

- `e6a39e7bd51e7cf60d7eaeea8d710f6cdf4ad9e5` — Phase 25: complete
  realization-aware runtime 3.0.0 closure.

## Earlier phases

Phases 0–24 (versioned contracts and lifecycle, scenario validation and world
compilation, campaign preparation, structural execution and exact replay,
input-integrity verification, domain-pack registry/bindings/declarations,
operational activity feed, Colony UI, declarative state models and
transitions, pure transition kernel, snapshot isolation, trajectory plans and
execution, verified inspection, trajectory matrices, observation bindings and
extraction, metric-observation matrices, deterministic metric statistics,
objective-to-metric evaluation semantics, world uncertainty realizations) are
documented in [`docs/PHASE_HISTORY.md`](docs/PHASE_HISTORY.md) and the phase
handoffs at the repository root.

## [Unreleased]

Phase 29 (Model Pack foundation and KALHAS-PAN v0.1) is **not started** and
**not authorized**. Nothing is in development.
