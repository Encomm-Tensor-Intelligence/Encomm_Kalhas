# KALHAS Handoff — Phase 26 Implementation Complete (Documentation Snapshot, Not Yet Committed)

Date: 2026-08-16
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`
Branch: `main`
Local HEAD at the documentation snapshot:
`e6a39e7bd51e7cf60d7eaeea8d710f6cdf4ad9e5`
(Phase 25 closure commit, subject `Phase 25: complete realization-aware runtime 3.0.0 closure`)
Remote: `origin/main == f40e83de468ca14100d011454d15eb3dd561c810`
Divergence `origin/main...HEAD`: `0 1`
Push status: **not pushed** - push is intentionally deferred until Phases 26 and 27 are both complete.
Phase 26 status: **implementation-complete and gate-green locally; NOT yet committed; index empty.**

> **Read this handoff completely, then audit the repository directly.** This
> handoff is the authoritative record of Phase 26. The repository, not this
> prose, is always the final source of truth. Every claim below was verified
> against code and tests at the documentation snapshot; verify again after any
> later change.

---

## 1. Purpose and status

Phase 26 - **empirical campaign outcome distributions** - transforms the
verified runtime-3 shared-seed observations of a completed campaign into
campaign-level empirical strategy/objective outcome evidence. It is
**implementation-complete and gate-green locally**:

- the complete change set (Section 3) is present in the working tree,
  **uncommitted**;
- the Git index is **empty** (`git diff --cached` shows nothing);
- a local closure commit requires a **separate explicit user authorization**
  and has **not** been made;
- **no GitHub push occurs until both Phase 26 and Phase 27 are complete**;
- **Phase 27 implementation has not begun**. The authoritative Phase 27
  design already exists: the external blueprint
  (`KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md`) carries the
  complete Phase 27 design and `CODEX_HERMES_HANDOFF_PHASE_26_START.md`
  incorporates it; this handoff summarizes it in Section 16. No Phase 27
  production module, contract, schema, API route, test artifact,
  comparison result, decision policy, or decision brief has been
  implemented anywhere in the repository. The Phase 26 boundary suite
  proves absence from the implemented kernel/API surface - it does not
  prove absence from documentation.

This handoff supersedes the Phase-25-checkpoint statements in
`README.md`, `docs/architecture/README.md`, and
`docs/architecture/contracts-and-lifecycle.md` that "Phase 26 has not
begun" / "Phase 26 and Phase 27 are not implemented or designed here"
(the three documentation files now carry a Phase 26 status section that
explicitly supersedes those historical statements; the historical
statements in `CODEX_HERMES_HANDOFF_PHASE_26_START.md` and
`KALHAS_HANDOFF_PHASE_25.md` remain as historical checkpoints and were
not edited).

## 2. Baseline Git lineage (documentation snapshot)

- Branch: `main`
- Local HEAD: `e6a39e7bd51e7cf60d7eaeea8d710f6cdf4ad9e5` (Phase 25 closure commit)
- `origin/main`: `f40e83de468ca14100d011454d15eb3dd561c810` (unchanged; Phase 25 is local-only)
- Divergence `origin/main...HEAD`: `0 1`
- The accumulated Phase 26 tree is **uncommitted**: `git status --short`
  reports 21 modified (`M`) and 20 untracked (`??`) paths.
- The index is **empty**: `git diff --cached --name-only` returns nothing.
- No Phase 26 commit hash exists yet. Do not invent one. The Phase 26
  closure commit, once authorized, must be independently verified
  post-commit (Section 15).

## 3. Exact Phase 26 file inventory

### 3.1 Created files (19 Phase 26 paths + 1 orchestrator handoff = 20 untracked)

**Production - application (6):**

```text
kalhas/application/campaign_outcome_statistics.py
kalhas/application/campaign_outcome_runtime.py
kalhas/application/campaign_outcome_identity.py
kalhas/application/campaign_outcome_errors.py
kalhas/application/campaign_outcome_matrix_runtime.py
kalhas/application/campaign_outcome_query_service.py
```

**Production - contract (1):**

```text
kalhas/contracts/v1/campaign_outcome.py
```

**Production - API (1):**

```text
kalhas/api/routes_campaign_outcome.py
```

**Schema (1):**

```text
schemas/v1/CampaignOutcomeDistributionMatrix.schema.json
```

**Tests (10):**

```text
tests/phase26_helpers.py
tests/test_phase26_acceptance.py
tests/test_phase26_boundaries.py
tests/test_api_phase26.py
tests/test_campaign_outcome_contracts.py
tests/test_campaign_outcome_identity.py
tests/test_campaign_outcome_matrix_runtime.py
tests/test_campaign_outcome_query_service.py
tests/test_campaign_outcome_runtime.py
tests/test_campaign_outcome_statistics.py
```

**Orchestrator handoff (1, created at phase start, part of the Phase 26 change set):**

```text
CODEX_HERMES_HANDOFF_PHASE_26_START.md
```

### 3.2 Modified files (21 paths)

**Production integration seams (3):**

```text
kalhas/api/app.py                        (+2: import + include_router of the outcome router)
kalhas/api/errors.py                     (+4: import + 409 integrity_error mapping of
                                         CampaignOutcomeDistributionMatrixIntegrityError)
kalhas/contracts/v1/__init__.py          (+3: import + PUBLIC_CONTRACTS tail entry
                                         + __all__ entry)
```

**Primary contract test (1):**

```text
tests/test_contracts.py                  (+76: complete CampaignOutcomeDistributionMatrix
                                         fixture entry in the contract round-trip matrix)
```

**Mechanically migrated historical tests (17):** the public-contract and
schema counts moved from 46 to 47, so every historical suite that asserted
the old count or the old tail had to be migrated mechanically. The changes
are count literal updates and tail-index updates only; no historical
behavior, assertion, or golden value was weakened:

```text
tests/test_campaign_metric_observation_contracts.py   (46 -> 47; negative-index tail -> positive-index tail)
tests/test_campaign_metric_statistics_contracts.py    (same mechanical update)
tests/test_campaign_trajectory_contracts.py           (same mechanical update)
tests/test_run_metric_observation_contracts.py        (same mechanical update)
tests/test_realization_contracts.py                   (count/tail update)
tests/test_domain_metric_observation_contracts.py     (count update)
tests/test_objective_evaluation_contracts.py          (count update)
tests/test_trajectory_execution_contracts.py          (count update)
tests/test_phase17_boundaries.py                      (count update)
tests/test_phase18_boundaries.py                      (count update)
tests/test_phase19_boundaries.py                      (count update)
tests/test_phase20_boundaries.py                      (count update)
tests/test_phase21_boundaries.py                      (count update)
tests/test_phase22_boundaries.py                      (count update)
tests/test_phase23_boundaries.py                      (count update)
tests/test_phase24_boundaries.py                      (count update)
tests/test_phase25_boundaries.py                      (47 contracts; names[46] ==
                                                      CampaignOutcomeDistributionMatrix;
                                                      47 schemas; Phase 26 tail; no
                                                      Phase 26/27 surface scan)
```

### 3.3 Documentation files (4 paths; the only files this closure slice may change)

```text
README.md                                      (Phase 26 status section added; stale statements superseded)
docs/architecture/README.md                    (Phase 26 section added; stale statement superseded)
docs/architecture/contracts-and-lifecycle.md   (Phase 26 section added; stale statements superseded)
KALHAS_HANDOFF_PHASE_26.md                     (this file, new)
```

Nothing else changed. Every production file, test, schema, handoff-history
file, `AGENTS.md`, the external blueprint, profile, memory, skill, and
configuration file is byte-identical to the Phase 25 baseline (verified by
the preservation manifest, Section 12).

## 4. Architectural responsibilities of every new production module

| Module | Responsibility |
| --- | --- |
| `kalhas/application/campaign_outcome_statistics.py` | Pure, stdlib-only (`{__future__, math, typing}`) statistical primitives: `EMPIRICAL_QUANTILE_ALGORITHM == "hyndman-fan-type-7-v1"`, `EMPIRICAL_TAIL_ALGORITHM == "empirical-fractional-tail-mean-v1"`, `EMPIRICAL_TAIL_ALPHA == 0.95` (fixed; callers cannot supply another alpha); `empirical_type7_quantile` (percentiles 5/25/75/95 only, integer numerator/remainder indexing, `math.fsum` interpolation); `empirical_upper_tail_mean_95` / `empirical_lower_tail_mean_95` (exact fractional tail mass 5/100; no `ceil(0.05*n)`, no unweighted selection). Enforces the exact-type finite-numeric sample contract (Section 6) with `ValueError` / `OverflowError` semantics. Store-free; no clock, randomness, network, or adapters. |
| `kalhas/application/campaign_outcome_runtime.py` | Pure builder `build_strategy_objective_outcome`: one `StrategyObjectiveOutcome` from a strictly revalidated `ObjectiveMetricBinding` (serializer-based `model_validate(..., strict=True)`) plus the exact ordered observed values in authoritative seed order. Reuses (never redefines) the accepted primitives and the frozen Phase 22 statistics functions; derives targeted evidence (achievement count/probability, seed-order normalized violations, worst violation, CVaR95) and the direction-aware adverse-tail statistic; optimization-only objectives keep the five targeted fields `None`. No ranking/preference/recommendation surface. |
| `kalhas/application/campaign_outcome_identity.py` | Deterministic matrix identity: `campaign_outcome_distribution_matrix_identifier` (hash-derived from the canonical campaign/world/runtime/evaluation-profile/source-matrix identity with the prefix `campaign-outcome-distribution-matrix-`; never from the content hash, timestamps, or tenant) and `campaign_outcome_distribution_matrix_content_hash` (canonical SHA-256 of the complete payload excluding `content_hash`). |
| `kalhas/application/campaign_outcome_errors.py` | The single safe typed `CampaignOutcomeDistributionMatrixIntegrityError` (public message generic and non-leaking; internal `reason` for diagnostics). |
| `kalhas/application/campaign_outcome_matrix_runtime.py` | Pure complete matrix builder `build_campaign_outcome_distribution_matrix(profile, world_realization_matrix, observation_matrix)`: type boundary, recorded-runtime gate (exactly 3.0.0 else typed `UnsupportedRuntimeVersionError`), strict serializer-based revalidation of all three sources, independent identity/content-hash verification (profile; realization matrix and every nested realization; observation matrix), exact cross-source consistency (tenant/scenario/campaign/world/seed/timestamp/comparison-mode/realization tuples), independent observation-matrix structural verification (complete strategy x seed cell count, contiguous sequence positions, strategy-major/seed-minor positions, metric collections, binding provenance, raw-value numeric-kind), evaluation-profile binding boundary (unique objectives, metrics present, units equal), then complete strategy-major/objective-minor aggregation through the accepted outcome builder. `derived_at` = observation-matrix `assembled_at` (never wall clock). Any internal failure converts to the typed integrity error - never a partial artifact. |
| `kalhas/application/campaign_outcome_query_service.py` | Independently verified read-only query `get_verified_campaign_outcome_distributions(store, tenant_id, campaign_id)`: loads campaign + status (must be exactly COMPLETE), fully verifies world + manifest, requires the world-embedded evaluation profile and strictly verifies the stored profile record against it (canonical equality), calls the existing verified world-realization and metric-observation matrix queries exactly once each, then the pure builder exactly once, and returns the matrix directly **without storing it**. Never executes, replays, extracts, repairs, creates, or writes; records no operational activity; repeated queries are byte-identical. |
| `kalhas/api/routes_campaign_outcome.py` | Exactly one route/operation: `GET /v1/campaigns/{campaign_id}/outcome-distributions`. Reads the tenant-scoped recorded `RunPlan` tuple **first** (every plan must be exactly 3.0.0; empty plan tuples and any other recorded runtime raise the typed 409 `conflict` before the query service is invoked - no first-element dispatch). Required `X-Tenant-ID` header; no request body; no runtime selector. GET only; read-only; no activity; safe typed 404/409 mapping. |
| `kalhas/contracts/v1/campaign_outcome.py` | Three nested strict frozen models (Section 5). Declarative data only; no executable surface. |

## 5. Contract / schema / API surface

### 5.1 Contracts (`kalhas/contracts/v1/campaign_outcome.py`, additive)

- **`EmpiricalDistributionSummary`** - exact ordered samples (raw
  `int`/`float` types preserved), sample count, minimum, maximum,
  arithmetic mean, median, population standard deviation, Type-7
  p05/p25/p75/p95, `quantile_algorithm == "hyndman-fan-type-7-v1"`.
  Validates internal consistency: count == length; extrema equal the
  exact finite-float projections; mean/median within extrema;
  non-negative std dev; non-decreasing quantile chain; one-sample
  invariant (every derived value equals the projected sample; std dev
  exactly `0.0`); repeated-value invariant (std dev exactly `0.0`,
  mean/quantiles within one adjacent float step); deterministic
  one-adjacent-float-step structural-bound policy (never
  `math.isclose`, never a broad epsilon; two+ steps rejected).
- **`StrategyObjectiveOutcome`** - positions and identities; metric id
  and unit; direction/target/reach-tolerance/weight/normalization-scale
  snapshots; ordered observed values + empirical summary; targeted
  evidence (achievement count, empirical probability, exact seed-order
  normalized-violation distribution, worst normalized violation,
  `tail_alpha == 0.95`, `tail_algorithm == "empirical-fractional-tail-mean-v1"`,
  `target_violation_cvar`) or all-`null` for optimization-only
  objectives; mandatory direction-aware `adverse_tail_statistic`. The
  contract independently recomputes the violation tuple and the
  achievement count and requires exact equality with the recorded
  fields; CVaR must lie between the violation p95 and the worst
  violation; the adverse tail must lie in its direction-aware band.
- **`CampaignOutcomeDistributionMatrix`** - the only Phase 26
  top-level public contract (`VersionedContract`, `extra="forbid"`,
  frozen, self-hashing): campaign/scenario/world identity + content
  hashes; `runtime_version` literal `"3.0.0"`; `comparison_mode`
  `"identical_conditions"`; evaluation-profile id/hash; uncertainty
  model id/hash (both-or-neither); both source matrix references with
  content hashes; ordered strategy/seed/objective/metric identifiers;
  complete strategy-major/objective-minor outcome tuple with contiguous
  sequence positions and identity-vs-position agreement; self-covering
  `content_hash`; `derived_at`. Structural shape only: unique
  identifiers, strictly increasing metric ids, exactly one outcome per
  strategy x objective pair, per-outcome sample counts == seed count,
  identical binding snapshots across strategies of the same objective
  (evidence values may differ).

### 5.2 Registration

- `CampaignOutcomeDistributionMatrix` is **`PUBLIC_CONTRACTS` index 46**;
  **total public contracts: 47** (indexes 0-45 unchanged).
- **Total schema artifacts: 47**; the only new artifact is
  `schemas/v1/CampaignOutcomeDistributionMatrix.schema.json` (nested
  value objects embedded as `$defs`). All 46 historical artifacts
  unchanged.
- `EmpiricalDistributionSummary` and `StrategyObjectiveOutcome` are
  nested value objects and remain **unregistered** (no schema
  artifacts).

### 5.3 API surface

Exactly one new path/operation:

```text
GET /v1/campaigns/{campaign_id}/outcome-distributions
```

- required `X-Tenant-ID` header; no request body; no runtime selector;
- runtime derived exclusively from the recorded `RunPlan` tuple (every
  plan exactly 3.0.0; empty tuple or any other value -> typed 409
  `conflict` before the query service);
- direct `CampaignOutcomeDistributionMatrix` response;
- safe typed errors: 404 unknown/foreign campaign; 404 world without an
  embedded evaluation profile; 409 `invalid_state` non-COMPLETE; 409
  `conflict` unsupported/empty recorded runtime; 409 `integrity_error`
  missing/inconsistent/corrupted upstream artifacts - all with generic
  non-leaking bodies and the single `ApiErrorResponse` envelope;
- repeated byte-identical reads; no mutation methods; no operational
  activity;
- Phase 25's six paths / seven operations preserved unchanged;
  `API_VERSION == "1"` and `SCHEMA_VERSION == "1.0.0"` unchanged;
  runtime remains exactly 3.0.0; runtime 1.0.0/2.0.0 behavior
  preserved byte-identically (runtime-2 golden tests and the Phase
  17/20/22 OpenAPI `$ref` canaries pass unchanged).

## 6. Statistical definitions and numeric edge behavior

- **Exact-type finite numeric validation.** Samples must be a plain
  non-empty `tuple` (tuple subclasses rejected) of exact `int`/`float`
  values; `bool` is rejected even though it subclasses `int`; strings,
  `Decimal`, `None`, containers, NaN, and Infinity are rejected;
  integers and floats may mix; raw types are preserved; nothing is
  coerced, clipped, repaired, normalized, rounded, or mutated.
- **Full-domain finite-float conversion proof.** Every sample must be
  proven convertible to a finite float before any selection, sorting,
  or arithmetic begins (no partial selection). Huge positive/negative
  integers whose conversion raises `OverflowError` - or any impossible
  finite intermediate representation - fail with `OverflowError`;
  invalid shape/type/non-finite input fails with `ValueError`. A public
  function never returns NaN or Infinity.
- **Hyndman-Fan Type 7 quantiles.** Integer `index_numerator =
  (n - 1) * p`, `lower_index = numerator // 100`, `remainder =
  numerator % 100`, `upper_index = min(lower_index + 1, n - 1)`;
  remainder 0 returns `float(sorted[lower_index])`, otherwise
  deterministic `math.fsum` linear interpolation with weights
  `(100 - remainder)/100` and `remainder/100`. Only percentiles 5, 25,
  75, 95 are supported (booleans and floats like `5.0` rejected).
- **One-sample and finite-sample behavior.** One sample: every location
  and quantile value equals the projected sample exactly, population
  std dev exactly `0.0`. Repeated-value collections: population std dev
  exactly `0.0`; the deterministic mean/quantiles may land within one
  adjacent float step of the projected constant.
- **Arithmetic mean, median, population standard deviation** come from
  the frozen Phase 22 primitives unchanged.
- **p05 / p25 / p75 / p95** empirical quantiles under the explicit
  algorithm identifier `hyndman-fan-type-7-v1`.
- **Fixed CVaR alpha 0.95.** `EMPIRICAL_TAIL_ALPHA == 0.95`; callers
  cannot supply another alpha. Fractional empirical tail mean:
  `tail_units = 5 * n`, `full_count = tail_units // 100`, boundary
  weight `remainder / tail_units`; n=1 -> the only sample; n=20 -> the
  single worst sample; n=100 -> mean of the worst five; non-multiples
  -> full worst observations plus the exact fractional boundary mass.
  No `ceil(0.05 * n)`, no unweighted selection, no bootstrap, no
  resampling.
- **Target-violation semantics** (Phase 23, exact seed order):
  minimize `max(0, value - target) / normalization_scale`; maximize
  `max(0, target - value) / normalization_scale`; reach
  `max(0, abs(value - target) - reach_tolerance) / normalization_scale`.
  Achievement: `value <= target` / `value >= target` /
  `abs(value - target) <= reach_tolerance`.
- **Direction-aware adverse-tail semantics** in the metric's original
  unit: `minimize` -> upper-tail mean of observed values; `maximize` ->
  lower-tail mean of observed values; `reach` -> upper-tail mean of
  absolute deviation from target.
- **Optimization-only objectives** (no target): target probability,
  normalized violations, and target-violation CVaR remain `null` (no
  target is ever invented); the direction-aware adverse-tail statistic
  remains available.
- **One-ULP golden-test discipline.** Values the mandated `math.fsum`
  primitives can land ±1 ULP from the exact rational boundary are
  asserted with the established `_assert_within_one_ulp` convention;
  every exactly representable value is asserted with exact equality.
- Production uses plain `int`/`float` and `math.fsum` only; the
  implementation does **not** use `Decimal` or `Fraction` in
  production.

## 7. Integrity, identity, tenant, runtime, ordering, and read-only invariants

- **Integrity.** Every source artifact is strictly revalidated against
  its complete contract (serializer-based `model_dump(mode="python")` +
  `model_validate(..., strict=True)`, Pydantic serializer-warnings
  suppression); validator-bypassed instances are rejected before any
  field is trusted. Every identity and content hash is independently
  recomputed; self-consistently rehashed tampering fails.
- **Identity.** Matrix identifier from the canonical
  (campaign, world, runtime, evaluation profile, world-realization
  matrix, metric-observation matrix) identity; content hash covers the
  complete payload excluding itself; `derived_at` = observation-matrix
  `assembled_at` (recorded lineage, never wall clock).
- **Tenant.** Tenant ownership is enforced at every boundary: store
  lookups, profile verification, realization and observation sources,
  and the matrix itself; foreign tenants are indistinguishable typed
  404s; public messages never leak values, hashes, targets, reasons,
  or another tenant's existence.
- **Runtime.** Everything dispatches on recorded artifacts only:
  recorded `RunPlan.runtime_version` for the route gate; the
  observation matrix's recorded `runtime_version` for the builder; the
  campaign's recorded records for the query. No caller-provided
  selector exists. Runtime remains exactly 3.0.0; 1.0.0/2.0.0 modules
  are untouched and carry no Phase 26 dependency.
- **Ordering.** Exact strategy-major / objective-minor outcome order
  with contiguous sequence positions; exact strategy-major / seed-minor
  observation cells; exact shared-seed ordering of samples; bindings in
  exact profile order (never sorted); exact ordered identifier tuples.
- **Read-only.** The pure builders are store-free; the query service and
  the route never write, never record operational activity, never
  execute/replay/extract/repair/create upstream artifacts; the matrix is
  derived in memory and **never stored** (the store has no outcome
  collection at all - proven by the boundary suite); repeated queries
  return byte-identical matrices and leave the complete store state
  unchanged.
- **Fail-closed.** Missing, additional, reordered, duplicated,
  foreign, mixed-runtime, or self-consistently rehashed artifacts are
  rejected with zero partial results and zero writes; empty plan tuples
  fail closed; missing worlds/profiles inside an existing campaign are
  corruption (typed integrity error), never a generic 404.

## 8. Complete adversarial proof coverage

The dedicated suites prove, beyond the happy path:

- **Statistics** (`test_campaign_outcome_statistics.py`, 102 tests):
  golden Type-7 vectors for odd/even/two-sample/repeated/negative/mixed
  int-float/unsorted inputs; one-sample behavior; tail-mean goldens
  (n=1, n=2, n=20, n=100, n=21, n=41, upper/lower orientation);
  `ValueError` on invalid shape/type/non-finite/bool/tuple-subclass;
  `OverflowError` on huge integers and on the finite-float conversion
  proof (including negative huge integers and the guarantee that
  conversion failure is raised even when the sample would not
  participate in the requested percentile/tail); percentile literal
  validation; stdlib-only import boundary.
- **Contracts** (`test_campaign_outcome_contracts.py`, 307 tests):
  frozen/strict/JSON round-trip/exact field order; raw-strictness
  attacks (bool, strings, `Decimal`, NaN/Infinity, integral floats);
  summary consistency and tamper rejection (one-ULP tamper rejected,
  one-step accepted / two-step rejected); primitive-fed composability
  (Type-7 boundary overshoot, constant-vector noise); relaxed boundary
  families (mean/median/quantile/CVaR/adverse-tail bands); targeted vs
  optimization-only rules; exact target/tolerance boundaries;
  achievement count/probability mismatch rejection; violation-tuple
  recomputation equality; CVaR band; direction-aware tail bands;
  matrix Cartesian shape (missing/additional/duplicate/reordered
  outcomes, non-contiguous positions, identity mismatches, count
  mismatches, snapshot drift across strategies); schema/registry
  compatibility.
- **Runtime builder** (`test_campaign_outcome_runtime.py`, 150 tests):
  golden minimize/maximize/reach/optimization-only outcomes;
  achievement boundaries; seed-order violation preservation;
  primitive-generated CVaR and adverse tails; one-sample and short-tail
  cases; repeated vectors emit exact 0.0 std dev; legal finite-float
  projections (2**53+1, 10**100); unrepresentable integers raise
  `OverflowError` before any statistical work; binding revalidation
  (validator-bypassed bindings rejected; valid bypassed bindings match
  normal ones and are never mutated); position/strategy-identity rules;
  arithmetic overflow (`OverflowError`, never `ValueError`); snapshot
  copying; zero mutation; determinism.
- **Identity** (`test_campaign_outcome_identity.py`, 44 tests): golden
  identifier/hash; each identity input independently changes the
  identifier; caller-mapping-order independence; identifier never uses
  matrix fields; every top-level and nested field changes the hash;
  content-hash recomputation ignores the recorded hash; input never
  mutated; preserved-file byte-identity.
- **Matrix builder** (`test_campaign_outcome_matrix_runtime.py`, 82
  tests): wrong-object and wrong-model-type rejection; unsupported
  runtime; validator-bypassed profile/realization/observation matrices
  rejected; identity/hash tampering at every level (profile,
  realization matrix, nested realizations, observation matrix);
  cross-source mismatches (tenant, scenario, campaign, world version,
  world hash, seed order, timestamp lineage, realization tuples,
  comparison mode); observation-structure attacks (missing/additional/
  reordered cells, identity tamper, metric-collection
  missing/additional/reordered, binding-provenance drift, invalid raw
  values); binding-boundary failures; numeric overflow; error safety
  (generic message, no partial artifact, inputs unchanged on failure);
  module boundaries.
- **Query service** (`test_campaign_outcome_query_service.py`, 46
  tests): real-lifecycle proof with multi-strategy shared seeds; direct
  pure-builder lineage equality; byte-identical repeats; store digest
  unchanged; exact call counts (upstreams and builder exactly once);
  unknown/foreign campaigns indistinguishable and do no work;
  non-COMPLETE states rejected; world without embedded profile raises
  not-found and invents nothing; missing/validator-bypassed/tampered/
  self-consistently-rehashed/foreign stored profiles fail closed;
  missing world/manifest/corrupted world fail closed; upstream
  corruption (uncertainty model, missing first/middle/last observation
  sets, corrupted sets, unsupported recorded runtime) propagates
  typed; generic non-leaking messages; no writes on failure.
- **API** (`test_api_phase26.py`, 46 tests): OpenAPI surface (exactly
  one path/operation, required tenant header, no body, no runtime
  selector, Phase 25 paths unchanged); real-lifecycle 200 + exact
  response validation + direct-query equality + repeated-GET equality +
  no activity; 404/409 mapping (missing header 422; unknown/foreign
  404; missing profile 404; non-COMPLETE 409 `invalid_state`; empty
  plans 409; legacy and mixed runtimes 409 with no first-element
  dispatch; query parameters cannot alter dispatch); error bodies
  generic and non-leaking; route invokes the runtime gate and query
  exactly once; gate failure -> zero query calls; no other HTTP
  methods; registration counts; schema equality with model JSON
  schema.
- **Boundaries** (`test_phase26_boundaries.py`, 26 tests):
  domain-neutral kernel (no NEXUS/LEGION/adapters/domain packs, no new
  component, no domain vocabulary); determinism/purity (forbidden
  modules and call chains, minimal statistics import set, no
  clock/runtime-selector parameters); derived evidence (store-free
  builders, strictly read-only query + route with exact forbidden-call
  sets, matrices never stored, no activity); public/API surface
  (exactly one GET, recorded-runtime dispatch, X-Tenant-ID, index 46
  with exact 46-name prefix, 47 schemas, nested value objects
  unregistered, Phase 25 paths unchanged); statistical/decision
  boundary (no rank/winner/prefer/recommend/confidence/forecast/
  decision-brief symbols or fields, no executable/callback surface, no
  adaptive surface, no Phase 27 artifact names anywhere in the kernel);
  versioning (API/SCHEMA versions unchanged, runtime exactly 3.0.0, no
  legacy runtime literals, no Phase 26 dependency in runtime-2 or
  Phase-24 modules).
- **Acceptance** (`test_phase26_acceptance.py`, 28 tests): the causal
  100-seed proof (Section 9), including the fixed-ensemble assertions
  (never searched), the 81/19 split proof, attempt-record causality,
  golden statistics, replay of both branches, repeated-GET equality
  with full store-digest comparison, zero activity, no stored matrix,
  and no manufactured evidence.

## 9. The exact 100-seed acceptance chain and golden values

The fixture (`tests/phase26_helpers.py` + `tests/test_phase26_acceptance.py`)
drives one real end-to-end runtime-3.0.0 campaign through the public
services: declarations (state model `sm-1` with integer `level`;
guarded transitions `t-x` (level 5 -> 84) and `t-y` (level 9 -> 103);
metric-observation binding `m-1 -> level`; discrete uncertainty model
`{5, 9}` with equal weights and `nearest_ties_to_even` rounding;
evaluation profile `obj-1 -> m-1` (minimize, target 100.0,
normalization scale 100.0) declared **before** compilation), world
compilation, `prepare_realization_campaign` (with the single sanctioned
`EXPECTED_STRATEGY_SET_SIZE == 2` alignment inside the preparation
call), trajectory planning, start, full execution, and explicit per-run
extraction.

Chain and golden values (all verified against the production
primitives and the tests):

```text
100 fixed deterministic seeds            seed-000 ... seed-148 (authoring-time tuple:
                                         first 81 branch-X + first 19 branch-Y seeds)
100 realizations, never 200              exactly K realizations for K seeds
2 strategies                              mock-a [t-x, t-y]  |  mock-b [t-y, t-x]
200 runtime-3 executions                  strategy-major/seed-minor, exactly 2 x 100
200 explicit observation extractions       one immutable set per run
shared world per seed                     identical world_realization_id/content_hash
                                         for both strategies at every seed (100/100)
branch values 5 and 9                     realized levels; 81 x 5, 19 x 9
causal observed values 84 and 103         one applied guarded transition per run
                                         matching the branch; the other guard_not_satisfied;
                                         opposite attempt orders prove the distinct plans
target achievements                       exactly 81 achieved (84 <= 100), 19 missed (103 > 100)
empirical_target_achievement_probability  exactly 0.81
minimum / maximum                         84.0 / 103.0
arithmetic mean                           87.61
median                                    84.0
population standard deviation             7.453717193454551
Type-7 p05 / p25 / p75 / p95              84.0 / 84.0 / 84.0 / 103.0
worst normalized target violation         0.03
CVaR95 normalized target violation        0.03
adverse-tail statistic (minimize)         103.0
normalized-violation distribution         min 0.0, max 0.03, mean 0.005699999999999999,
                                         std 0.011769027147559818, p95 0.03
matrix identifier                         campaign-outcome-distribution-matrix-4c9a997c4f57df7d
matrix content hash                       a5717de324af501c937b8b87cd114006edda1311ff811bd64fe0893f8ec5c230
derived_at                                2026-01-01T12:00:00Z (= observation-matrix assembled_at)
exact replay                              seed-000 (branch X) and seed-002 (branch Y):
                                         manifest pair, replay_classification == "exact",
                                         expected == recomputed execution and observation-set
                                         hashes, idempotent, writes only the manifest pair
repeated GET equality                     three byte-identical responses; complete store
                                         digest unchanged; zero operational activity;
                                         no artifact creation; no outcome matrix stored
no manufactured evidence                  exactly 200 RunPlan records, 200 execution records,
                                         200 observation-set records, 2 StrategyTrajectoryPlan
                                         records (one per strategy) and 2 strategy candidates
                                         over 100 shared world realizations; every observed
                                         value matches the
                                         independent causal expectation function; the only
                                         test-side patch is the sanctioned EXPECTED_STRATEGY_SET_SIZE
                                         alignment inside the single preparation call
```

The fixed seed tuple was selected **at authoring time** (probed once
outside the repository against the final fixture world) and is
**never searched, retried, randomized, or adapted during test
execution** - the fixture asserts the constant ensemble and its exact
81/19 split.

## 10. Focused and full test/gate results (this documentation slice, exact)

| Gate | Result |
| --- | --- |
| `uv run pytest -q tests/test_phase26_acceptance.py` | exit 0 (28 tests) |
| `uv run pytest -q tests/test_phase26_boundaries.py` | exit 0 (26 tests) |
| `uv run pytest -q tests/test_api_phase26.py` | exit 0 (46 tests) |
| `uv run pytest -q tests/test_schema_sync.py` | exit 0 (5 tests) |
| `uv run pytest -q tests/test_phase25_boundaries.py` | exit 0 (27 tests) |
| Focused total (5 suites, run together) | exit 0 - **132 passed, 0 skipped, 0 failed** |
| `uv run pytest -q` (full suite) | exit 0 - **4049 passed, 1 skipped, 0 failed** |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 260 files already formatted |
| `uv run mypy kalhas tests` | Success: no issues in 247 source files |
| `uv run python scripts/export_schemas.py --check` | all schema artifacts are synchronized (check-only; no schema was written) |
| `git diff --check` | clean |

The single skip is the pre-existing approval-gated `test_boundaries.py`
AGENTS.md test. The full-suite total exactly matches the Phase 26
implementation baseline (4049 passed, 1 skipped) - the documentation
slice changed nothing behavioral. The known Phase 23 UUID-"91" flake
did **not** occur, so the flake rerun protocol (Section 11) was not
needed. The only expected warning is the benign
Starlette/TestClient deprecation warning.

## 11. Known pre-existing Phase 23 UUID-"91" flake protocol

`test_error_bodies_never_leak_values` (associated with an incidental
UUID substring `"91"`) is a known pre-existing Phase 23 flaky test.
Protocol when it is the **sole** full-suite failure:

1. Rerun that test isolated once.
2. Rerun the full suite once.
3. Report all results honestly.
4. Do not modify or weaken the flaky test merely to make the suite
   green; do not modify unrelated files.

It did not occur in this slice; the protocol is recorded for future
sessions.

## 12. Exact SHA-256 table (final, at this documentation snapshot)

All hashes below were recomputed after the documentation reached final
form and compared against the pre-edit preservation manifest (captured
externally at `%LOCALAPPDATA%\Temp\kalhas_phase26_preservation_manifest.txt`
on 2026-08-16T13:05:28Z). Every production/test/schema/handoff-history/
blueprint file is **byte-identical** to the pre-slice baseline. The only
changed files are the four documentation paths; their pre-edit and
post-edit hashes are both listed.

### Created Phase 26 files (19) + orchestrator handoff (1)

| File | SHA-256 |
| --- | --- |
| `kalhas/application/campaign_outcome_statistics.py` | `5e4d32f8346a543c3260a43e67df593d695e8e091d0592a46566f8e08ae0e3d2` |
| `kalhas/application/campaign_outcome_runtime.py` | `2829dffa57d45398265f831f704839e5a702853973a243c4d8d33b3c01ef3fd9` |
| `kalhas/application/campaign_outcome_identity.py` | `be673a606fb6308b1c1c88104bde44e10714ef5b95d5f469a0b2d1053f747a04` |
| `kalhas/application/campaign_outcome_errors.py` | `573e43376d794dae38f617007898a304da61e37ecd7da565ea02b90504f8a656` |
| `kalhas/application/campaign_outcome_matrix_runtime.py` | `ee22dd9cbb0e4c5b3863b85af4d649d9b326c2c28fdb2436ca58f61028b7015c` |
| `kalhas/application/campaign_outcome_query_service.py` | `a57f0d617db5e73e5d612f448ed0b189d6ae62bbc9957f89c001ef666763699e` |
| `kalhas/contracts/v1/campaign_outcome.py` | `0100c5e5be6a47483c340179be8a4ba733662b7a1d58d5866cc8f1720d66cdd4` |
| `kalhas/api/routes_campaign_outcome.py` | `dd90fcb15800a666806d2f19f7bd4dc30d62a5d0f34a62782ae0424adffb0f21` |
| `schemas/v1/CampaignOutcomeDistributionMatrix.schema.json` | `85e42a329ad7b85bf3833a7d3e12ef7ddbba6e3dbba2ec0a9217c8ccc65037e4` |
| `tests/phase26_helpers.py` | `aa0e5a4c8a4564110c286ff2f4ec66e5378c7f5a1afbbf1e317b6eef593938a1` |
| `tests/test_phase26_acceptance.py` | `0b5e0e3a52e580c6dc31349fc7bf321e6569d6708847b5127ac67727b0ed9910` |
| `tests/test_phase26_boundaries.py` | `323984aeccc3630333f41005df35382ef1ccd4b84e49978a0f38808899c6defd` |
| `tests/test_api_phase26.py` | `6de4d071c161760f2dab186233df2059bf0e43812dd671b0459a3a083171e505` |
| `tests/test_campaign_outcome_contracts.py` | `6315c5f118ca697042014c62dec8abf796d4f8246b224adb0b301354fe015169` |
| `tests/test_campaign_outcome_identity.py` | `41db11e7c6e6864b289379e1493b87aa36034682044466aaf4faa541ca795539` |
| `tests/test_campaign_outcome_matrix_runtime.py` | `53d6f0b73f40ee84543624bdc064a52c215ff8ebb71f6b8209343b424bfed0c6` |
| `tests/test_campaign_outcome_query_service.py` | `4e0891b611f0a8ef9189b37c0053fb27de61471093024d2c96feb169810c593f` |
| `tests/test_campaign_outcome_runtime.py` | `cf55a64ede5f2b12643f598e42db66741ce53e92326e41ca4e62615d2a289cac` |
| `tests/test_campaign_outcome_statistics.py` | `4f9dc8fd70e0a34cf20a91abc94df85600c5cb4fadb375c2f5450be02c9111bf` |
| `CODEX_HERMES_HANDOFF_PHASE_26_START.md` | `0ce6a46915666fb29ef7e4fe2b49d324e8e094187d78404f0b733db1fcda1f22` |

### Important modified integration files (21) - unchanged since the pre-edit manifest

| File | SHA-256 |
| --- | --- |
| `kalhas/api/app.py` | `ca0500ae830380ecd25677695965cacb5dc1b17bb21df54c2df9c2672a1d7b47` |
| `kalhas/api/errors.py` | `efef80e991a9fdaaf6d8fed618102d8061f68788132eae4cd82766988579d169` |
| `kalhas/contracts/v1/__init__.py` | `30ce1ee7c9d221a2a03d9cacfa32cdbf4e17518bf2e15b3046cf61d1d2792697` |
| `tests/test_contracts.py` | `0605c49c09e7ce92f96b3b84597ba1bc97c2453e5b3f733b536e399a198005bf` |
| `tests/test_campaign_metric_observation_contracts.py` | `ed17f991d339f84ff8997360d9e3a7e68ccfe1aef0d0ad412c5a609f8c72d4d5` |
| `tests/test_campaign_metric_statistics_contracts.py` | `b1f343a097de0fc1a28fbcd130add4141908fd833d9a86576a67d6702b2e439a` |
| `tests/test_campaign_trajectory_contracts.py` | `6dd127aba89a1cc089a5b9afb531f46f1341a2879a4b5db1151d0ab9efe8793d` |
| `tests/test_domain_metric_observation_contracts.py` | `1f37f234c329e2644caf91faa2ebae9c1851416f52b663907cdafb720d9b4979` |
| `tests/test_objective_evaluation_contracts.py` | `0a8945498e45b0e78c34506e2a30ddbeab81dd0467796bd4e9d7bf23e4f54b2f` |
| `tests/test_trajectory_execution_contracts.py` | `a7edd336f3b63bd115bf37f8b9133005ccd0bb12df8ad48b83f60d58f7b63ef2` |
| `tests/test_phase17_boundaries.py` | `c271d51a50838fe4fe1f260f43a6c745df7e5ea2df62e2a24f1abb666c9afe0c` |
| `tests/test_phase18_boundaries.py` | `23c16830c817d328615ac2237d5a8b039c4ba02c8dd45d093a6f14f9cec10b94` |
| `tests/test_phase19_boundaries.py` | `8e9b9cb0705bf9c73149b8097b73dc7c58bb07492774358e0a780ffa71008736` |
| `tests/test_phase20_boundaries.py` | `30d659d1c11f67e0bff2cfc0cde5b2448e720a408f8de343a463ce11187930e1` |
| `tests/test_phase21_boundaries.py` | `994dfe4b5ba829ffe26be4aef9d90602a6324ed7bdb7a548dad3c822062cf743` |
| `tests/test_phase22_boundaries.py` | `476c9e17182f572ad4caeeb87879f78f670b99a144e95a10b1aad036ced0bba2` |
| `tests/test_phase23_boundaries.py` | `6bd9e73096d4e2548fe500435baebc86bb31bd15d73cc72fac530244bbcc7e2f` |
| `tests/test_phase24_boundaries.py` | `ce89cecda1874b879bcbe2e877bd1666a03ca02f5f21c97df09def29e90c04fc` |
| `tests/test_phase25_boundaries.py` | `0d731abc6dd0c3c784c8ad39b45f131dd62776681e2514d75ea6647fedc99158` |
| `tests/test_realization_contracts.py` | `9490126f3aaf700a1665eded676f9014915799f962a11f58f644d8627159ff7c` |
| `tests/test_run_metric_observation_contracts.py` | `38d97feceedd0d6bf9320c6dbea06643c07d6db90072dd592bb9e52d4b1b3587` |

### Protected historical/integrity anchors (unchanged)

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `130d0067330ece8d6947e1c478e5dd529973abcbdad0f5b9b95454ab06c26348` |
| `KALHAS_HANDOFF_PHASE_25.md` | `f316560ae215ca697219a6ea45372de2ef707ed8966e79be9d792f2871f9695f` |
| `KALHAS_HANDOFF_PHASE_24.md` | `8616d45e0c4727cbf027b7a3f133e749c33d2a6a328c6d6668c2e5f1108ea652` |
| External blueprint `C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md` | `bbcb793be70e063cc57f1e74f2dc4f3dbf3a78237f3d84859a1bb393f19b0678` |

### Documentation files (the only changed paths; pre-edit -> post-edit)

| File | Pre-edit SHA-256 | Post-edit SHA-256 |
| --- | --- | --- |
| `README.md` | `dd78ac303fa004913cefe2165107f3c5ec68dc77b3cd2a69184d32e8a7dbb9da` | `2ba1776ded992df027e1df5eb892be4831d9db39041857c1b104bf3e2836c537` |
| `docs/architecture/README.md` | `5c249a402ada24229d25bab895791148dba4d013cb4bcd74591d67fd70e20792` | `5288e422a9a7140d4eb583810c7298387164fbb93b229ab525833ed25140fbaf` |
| `docs/architecture/contracts-and-lifecycle.md` | `3861bc5d25daeb1ba5bc7e6440ef0a1a41b0a247b58e0accafa0a8e36f5a7043` | `6de69be4e43f7db77533716a5010ab44d0e22717104d7738997b6d46d89a1670` |
| `KALHAS_HANDOFF_PHASE_26.md` | (new) | recorded in the closure session report (self-reference is impossible) |

## 13. Explicit non-changes and non-goals

**Non-changes.** No production file, test, schema, `AGENTS.md`,
handoff-history file (`KALHAS_HANDOFF_PHASE_22/24/25.md`,
`CODEX_HERMES_HANDOFF_PHASE_26_START.md`), the external blueprint,
NEXUS/LEGION/Colony-UI surface, adapter, profile, memory, skill, or
configuration file was changed by this documentation slice. No
stage/commit/push/branch/amend/rebase/history rewrite occurred. No
schema was written (`export_schemas.py` ran with `--check` only).

**Non-goals (unchanged through Phase 26).** No paired strategy
comparison; no feasibility policy; no Pareto analysis; no
regret/minimax selection; no ranking or campaign decision brief; no
adaptive policy runtime; no KALHAS-PAN; no historical benchmark; no
real LEGION/NEXUS integration; no production database, queue, auth,
deployment, or command-center expansion; no confidence intervals, no
forecast certainty, no universal real-world probability, no
reality-prediction or true-causality claims. 0.81 is an empirical
target-achievement rate over the declared 100-seed ensemble, not a
calibrated real-world probability.

## 14. Exact local Git / publication state

```text
branch:                main
HEAD:                  e6a39e7bd51e7cf60d7eaeea8d710f6cdf4ad9e5
origin/main:           f40e83de468ca14100d011454d15eb3dd561c810
divergence:            0 1
git diff --cached:     empty (index untouched)
git status --short:    21 M + 20 ?? (exactly the Phase 26 change set)
git diff --check:      clean
```

No Phase 26 commit exists. The next Git operation on this tree is a
closure commit **only after** Codex audit and explicit user
authorization (Section 15).

## 15. Closure protocol

1. **Codex independent audit** - Codex reads this handoff, re-reads the
   changed production files, inspects `git status`/diff/HEAD/origin/
   divergence directly, and runs the relevant gates independently.
2. **Explicit user authorization** - the user authorizes the Phase 26
   local closure commit in a separate explicit instruction.
3. **One normal local Phase 26 closure commit** - a single normal
   `git add` (exactly the 21 M + 20 ?? Phase 26 paths, plus the four
   documentation paths) and one normal commit on `main` with a
   descriptive message. No amend, no squash, no rebase, no force.
4. **No push** - the commit stays local; `origin/main` remains at
   `f40e83de...` until Phases 26 and 27 are both complete and the user
   separately authorizes the push.
5. **Phase 27 begins only after the local Phase 26 commit is verified**
   (HEAD advanced, tree/index clean, divergence `0 1`, full gates
   re-confirmed). Do not begin Phase 27 in the same session as the
   Phase 26 closure commit.

## 16. Phase 27 starting scope (authoritative design present - implementation not begun)

Phase 27 - **robust paired strategy comparison and campaign decision
brief** - is the next authorized implementation target. Its authoritative
design is recorded in the external blueprint and the Phase 26 start
handoff; its scope is:

- immutable declarative `CampaignDecisionPolicy` (no arbitrary
  expressions, scripts, callbacks, provider references, or executable
  templates); one policy per campaign, declared before brief
  generation; deterministic id/hash/timestamp; algorithm identifier
  `feasibility-pareto-minimax-regret-v1`;
- evidence sufficiency and feasibility (hard targeted-objective
  thresholds; `insufficient_evidence` is a valid result - never guess);
- paired same-seed deltas (positive always means the first strategy is
  worse; win/tie/loss counts and rates under the declared tie
  tolerance; median/p05/p95/worst paired delta);
- Pareto dominance (no worse everywhere, strictly better in at least
  one required measure);
- per-seed weighted regret and minimax selection (regret is
  comparative and distinct from target violation; the robust candidate
  minimizes maximum total weighted regret among feasible,
  non-dominated strategies);
- deterministic auditable campaign decision brief (factual templates
  only; no chain-of-thought, hidden reasoning, fabricated prose, or
  unexplained scalar score);
- `inconclusive` is a valid successful result (a tie never
  manufactures a winner);
- no adaptive policy runtime and no Phase 28 work.

## 17. Mandatory reads and first actions for the next session

The next Codex/Hermes session must, in order:

1. Read completely: `AGENTS.md`; `CODEX_HERMES_HANDOFF_PHASE_26_START.md`;
   the external blueprint
   `C:\Users\xampos\Desktop\KALHAS_PHASES_23_27_CODEX_IMPLEMENTATION_BLUEPRINT.md`
   (SHA-256 `bbcb793be70e063cc57f1e74f2dc4f3dbf3a78237f3d84859a1bb393f19b0678`);
   `KALHAS_HANDOFF_PHASE_25.md`; **this handoff**; and (if the closure
   commit exists by then) the Phase 26 closure commit message and diff.
2. Inspect the repository directly, never trusting prose:
   `git status --short`, `git diff --cached`, `git rev-parse HEAD`,
   `git rev-parse origin/main`,
   `git rev-list --left-right --count origin/main...HEAD`,
   `git log -5 --oneline --decorate`.
3. Confirm the Phase 26 closure state: if the closure commit exists,
   verify HEAD == the closure commit, the tree/index are clean, and
   divergence is still `0 1`; if it does not exist, verify the change
   set is still exactly the Section 3 inventory and the index is still
   empty.
4. Re-verify the Section 12 hashes against the repository (production,
   tests, schemas, handoff history, blueprint) and against the
   external preservation manifest.
5. Only then begin Phase 27 implementation work - and only with the user's
   explicit Phase 27 go-ahead after the Phase 26 closure commit is
   verified.

---

## Final checkpoint

- Phase 26: implementation-complete, gate-green locally (4049 passed /
  1 skipped), **not yet committed**, index empty.
- Documentation: truthful Phase 26 status sections added to all three
  documentation surfaces; all stale Phase-25-checkpoint statements
  explicitly superseded.
- Handoff: this file (SHA-256 recorded in the closure session report).
- Push: deferred until Phases 26 and 27 are both complete.
- Phase 27: **authoritative design exists; implementation has not begun**.
- Codex: orchestrator/reviewer. Hermes: external implementer receiving
  bounded copy-paste prompts. Max two substantive prompts per Hermes
  session.

---

## 18. Phase 27 kickoff erratum (append-only, 2026-08-16)

Appended at the start of Phase 27 implementation. All historical text
above remains preserved unchanged as checkpoint history; where this
erratum states a later fact, it supersedes the earlier statement.

- Phase 26 was subsequently committed locally.
- Phase 26 closure commit:
  `886f398c288971d612fa57bd1d1e731113a69f72`.
- `origin/main` remains:
  `f40e83de468ca14100d011454d15eb3dd561c810`.
- Divergence at Phase 27 start: `0 2`.
- Phase 27's corrected design freeze is complete and accepted.
- This slice begins Phase 27 implementation.
- No push has occurred.
- Push remains forbidden until Phase 27 completion, the final audit,
  and a separate explicit user authorization.
- Historical pre-commit statements remain preserved as checkpoint
  history.
