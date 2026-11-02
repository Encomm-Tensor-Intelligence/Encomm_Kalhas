# Changelog

All notable changes to KALHAS are recorded here. KALHAS develops in numbered,
gate-verified phases; each phase closes with a full-suite gate run and an
independent audit before it is committed to `main`.

## [Phase 29] — 2026-11-01

### Added

- H29-S07: `kalhas-conformance-stockflow` 0.1.0, a tiny synthetic, non-health,
  integer stock-flow fixture under `kalhas/domain_packs/conformance_stockflow/`.
  It is labeled `conformance_only` and is never a product pack or a portfolio
  entry.
- H29-S08: shared-boundary acceptance proof. PAN and the fixture traverse the
  same generic dispatcher and Runtime-4 bridge under one identical authority
  chain (exact identities, one invocation per call, deterministic evidence,
  cross-pack fail-closed cases including a hybrid pack, cross-tenant
  rejection), with zero domain-specific kernel change.
- H29-S09A: `scripts/export_model_pack_artifacts.py` and three checked-in
  artifacts under `model_packs/v1/` (two `ModelPackAssuranceProfile` files and
  a 13-entry `ModelPackCatalogueEntry` list), verified by `--check`.
- H29-S09B: the human-readable catalogue `docs/model-packs/README.md`, a
  `Model Pack artifact synchronization check` CI step, a targeted
  `.gitattributes` that pins LF for the evidence paths, and documentation
  guard tests.

### Maturity

- PAN is `experimental`, derived only from `synthetic_conformance` and
  `deterministic_execution` evidence: no benchmark evidence, no external
  review, and no empirical adequacy claim. The fixture is `conformance_only`.
  The other 12 catalogue entries are `catalogued`: roadmap candidates only,
  with no implemented capability. Their list order is not a delivery order;
  only PAN (Phases 29–35) and MARITIME-TRADE (34A–35) have a planned wave, the
  rest are `post-35`, and their sequencing is not decided by the catalogue.

### Claim boundary

- The domain-neutral kernel and the frozen v1 contracts are unchanged (still 61
  contracts and 61 schema artifacts). There is no live action, no network or
  provider call, and no real data; fixtures are synthetic only, and no
  cross-platform proof is claimed.

### Known limitations

- Every evidence record pins the SHA-256 of the exact bytes of a named test
  module. Changing an evidence module or a pack release profile requires
  regenerating the artifacts with
  `uv run python scripts/export_model_pack_artifacts.py` and reviewing the diff;
  `--check` fails otherwise.
- The catalogue's 13 entries are the 11-pack strategic portfolio plus
  `kalhas-robotics` and `kalhas-neuro-symbolic`. Both were added by owner
  decision with the H29-S09A artifacts (declared 2026-10-28), as `catalogued`
  entries only; they change no ADR-005 decision.
- Mechanism step results are not yet consumed by campaign outcomes, objective
  evaluations, or decision briefs. The slice-map wording "pack-to-runtime-to-
  brief" is therefore proven only up to the runtime boundary; the pack-to-brief
  evidence path is open work for a later, separately authorized slice, to be
  planned at the Phase 30 entry audit.

### Gate

- 7,553 tests collected; exit code 0 (2026-11-01).

### Committed

- `b3b19719bc9a7557800584a0d434bca75d7b24a9` — Phase 29: conformance
  fixture, shared-boundary proof, Model Pack assurance/catalogue, closure docs.

## [Phase 29 foundation] — 2026-10-03

### Added

- ADR 005 and the additive versioned `DomainPack` mechanism boundary: pure,
  fail-closed step requests/results, exact mechanism/platform/configuration
  identity, dispatcher translation, and runtime integration without dynamic
  discovery or pack-specific kernel imports.
- Six top-level public v1 contracts (indexes 55–60, 61 total):
  `DomainMechanismSpec`, `DomainMechanismStepRequest`,
  `DomainMechanismStepResult`, `ModelPackReleaseProfile`,
  `ModelPackAssuranceProfile`, and `ModelPackCatalogueEntry`, with six
  synchronized JSON Schema artifacts (61 artifacts; 62 files in
  `schemas/v1/`).
- `KALHAS-PAN` v0.1: a minimal, deterministic, synthetic compartment-flow
  reference pack with an exact release profile, declared numerical/platform
  identity, conservation/capacity invariants, evidence, and tamper-resistant
  execution through the generic mechanism boundary.

### Claim boundary

- PAN remains synthetic architecture/conformance evidence only. Phase 29 adds
  no real data, empirical calibration, external scientific validity,
  government certification, live provider, network call, or autonomous action.
- The release profile assigns no assurance maturity; later benchmark, review,
  catalogue, and partner-evaluation states require their own exact evidence.
- This published foundation is not recorded as the complete Phase 29 roadmap
  checkpoint: the planned synthetic non-health conformance fixture, instantiated
  catalogue/assurance evidence, truthful final handoff, and closure audit remain
  separate work.

### Committed

- `1e15d14cac1594c1d74d724ce7f1b3cef6ad2609` — Phase 29: add Model Pack
  mechanism foundation and PAN v0.1.

## [Phase 28] — 2026-09-02

### Added

- Adaptive deterministic runtime `4.0.0` on top of runtime `3.0.0`: causal
  mid-run observation events under the frozen
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

- Full suite: 6,850 tests, 0 failures, 0 errors, 0 skipped.
- Ruff check, Ruff format check, strict mypy (340 source files), and
  schema-export `--check` all green.

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

- Full suite: 5,480 tests, 0 failed, 0 skipped.

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
preserved in Git history and described by the architecture documentation.

## [Unreleased]

No unreleased changes.
