# KALHAS Handoff — Phase 27 Implementation Complete (Pre-Commit Snapshot, Not Yet Committed)

Date: 2026-08-18
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`
Branch: `main`
Local HEAD at this snapshot:
`886f398c288971d612fa57bd1d1e731113a69f72`
(Phase 26 closure commit, subject `Phase 26: ... closure`; the Phase 26
handoff erratum records the commit and the `0 2` divergence)
Remote: `origin/main == f40e83de468ca14100d011454d15eb3dd561c810`
Divergence `origin/main...HEAD`: `0 2`
Push status: **not pushed** - push remains forbidden until Phase 27
completion, the final audit, and a separate explicit user authorization.
Phase 27 status: **implementation-complete and gate-green locally; NOT
yet committed; Git index empty.**

> **Read this handoff completely, then audit the repository directly.**
> This handoff is the authoritative pre-commit record of Phase 27. The
> repository, not this prose, is always the final source of truth.
> Every claim below was verified against code and tests at this
> snapshot; verify again after any later change.

---

## 1. Purpose and status

Phase 27 - **robust paired strategy comparison and campaign decision
brief** - transforms the verified empirical campaign outcome evidence
of a COMPLETE runtime-3.0.0 campaign into a deterministic, auditable
campaign decision surface under one immutable declared policy
(evidence sufficiency and target feasibility, same-seed paired
comparisons, Pareto dominance among feasible strategies, per-seed
weighted regret and minimax robustness, and a deterministic
preferred/inconclusive brief). It is **implementation-complete and
gate-green locally**:

- the complete Phase 27 change set (Sections 3-4) is present in the
  working tree, **uncommitted**;
- the Git index is **empty** (`git diff --cached` shows nothing);
- a local closure commit requires a **separate explicit user
  authorization** and has **not** been made;
- **no GitHub push has occurred** and none occurs until the final
  audit and a separate explicit user authorization;
- **Phase 28 and KALHAS-PAN are not implemented** anywhere in the
  repository - no future-phase production module, contract, schema,
  route, or test exists.

This handoff supersedes the Phase-26-checkpoint statements in
`README.md`, `docs/architecture/README.md`, and
`docs/architecture/contracts-and-lifecycle.md` that Phase 27 "has not
begun" / "is not implemented" (the three documentation files now carry
a Phase 27 status section that explicitly supersedes those historical
statements; the historical statements in the Phase 26 handoff and its
erratum remain as checkpoint history and were not rewritten).

## 2. Baseline Git lineage (this snapshot)

```text
branch:                main
HEAD:                  886f398c288971d612fa57bd1d1e731113a69f72
origin/main:           f40e83de468ca14100d011454d15eb3dd561c810
divergence:            0 2
git diff --cached:     empty (index untouched)
git status --short:    37 modified (M) + 31 untracked (??) paths
                       (exactly the Phase 27 change set)
git diff --check:      clean
```

No Phase 27 commit exists. Do not invent one. The closure commit, once
authorized, must be independently verified post-commit (Section 15).

## 3. Exact created-file inventory (31 untracked paths)

### 3.1 Production - application (10)

```text
kalhas/application/campaign_decision_statistics.py
kalhas/application/campaign_decision_evidence.py
kalhas/application/campaign_decision_paired_comparison.py
kalhas/application/campaign_decision_selection.py
kalhas/application/campaign_decision_comparison_runtime.py
kalhas/application/campaign_decision_brief_runtime.py
kalhas/application/campaign_decision_identity.py
kalhas/application/campaign_decision_errors.py
kalhas/application/campaign_decision_policy_service.py
kalhas/application/campaign_decision_query_service.py
```

### 3.2 Production - contract (1)

```text
kalhas/contracts/v1/campaign_decision.py
```

### 3.3 Production - API (2)

```text
kalhas/api/routes_campaign_decision.py
kalhas/api/requests_campaign_decision.py
```

### 3.4 Schemas (3)

```text
schemas/v1/CampaignDecisionPolicy.schema.json
schemas/v1/CampaignStrategyComparison.schema.json
schemas/v1/CampaignDecisionBrief.schema.json
```

### 3.5 Tests (15)

```text
tests/phase27_helpers.py
tests/test_phase27_acceptance.py
tests/test_phase27_boundaries.py
tests/test_api_phase27.py
tests/test_campaign_decision_contracts.py
tests/test_campaign_decision_requests.py
tests/test_campaign_decision_policy_service.py
tests/test_campaign_decision_query_service.py
tests/test_campaign_decision_identity.py
tests/test_campaign_decision_statistics.py
tests/test_campaign_decision_evidence.py
tests/test_campaign_decision_paired_comparison.py
tests/test_campaign_decision_selection.py
tests/test_campaign_decision_comparison_runtime.py
tests/test_campaign_decision_brief_runtime.py
```

## 4. Exact modified-file inventory (37 paths), including mechanical 47 -> 50 migrations

### 4.1 Production integration seams (5)

```text
kalhas/api/app.py                        (+2: import + include_router of the decision router)
kalhas/api/errors.py                     (+14: import + registration of the six decision
                                         errors in the 404 / 409 conflict / 422 / 409
                                         integrity_error buckets)
kalhas/api/routes.py                     (Colony serving docstring: two-surface description;
                                         no route or behavior change)
kalhas/application/in_memory_store.py    (+175: _campaign_decision_policies collection,
                                         put/get methods with strict revalidation +
                                         deep-copy, verify/revalidate helpers, imports)
kalhas/contracts/v1/__init__.py          (+11: imports + PUBLIC_CONTRACTS tail entries
                                         47-49 + __all__ entries)
```

### 4.2 Primary contract test (1)

```text
tests/test_contracts.py                  (+639: complete fixture entries for the three
                                         new contracts in the contract round-trip /
                                         VALID_PAYLOADS registry)
```

### 4.3 Mechanically migrated historical tests (17): the public-contract and
schema counts moved from 47 to 50, so every historical suite that
asserted the old count or the old tail was migrated mechanically. The
changes are count literal updates (47 -> 50) and tail-index updates
(decision contracts at 47-49) only; no historical behavior, assertion,
or golden value was weakened:

```text
tests/test_api_phase26.py                        (47 -> 50; decision tail; schema count)
tests/test_campaign_metric_observation_contracts.py   (count update)
tests/test_campaign_metric_statistics_contracts.py    (count update)
tests/test_campaign_outcome_contracts.py         (count update + tail)
tests/test_campaign_outcome_identity.py          (count update)
tests/test_campaign_outcome_matrix_runtime.py    (count update)
tests/test_campaign_outcome_query_service.py     (count update)
tests/test_campaign_trajectory_contracts.py      (count update)
tests/test_domain_metric_observation_contracts.py     (count update)
tests/test_objective_evaluation_contracts.py     (count update)
tests/test_phase17_boundaries.py                 (count update)
tests/test_phase18_boundaries.py                 (count update)
tests/test_phase19_boundaries.py                 (count update)
tests/test_phase20_boundaries.py                 (count update)
tests/test_phase21_boundaries.py                 (count update)
tests/test_phase22_boundaries.py                 (count update)
tests/test_phase23_boundaries.py                 (count update)
tests/test_phase24_boundaries.py                 (count update)
tests/test_phase25_boundaries.py                 (47 -> 50; decision tail; schema count;
                                                 decision-surface scan supersession)
tests/test_phase26_boundaries.py                 (50 contracts; decision tail 47-49;
                                                 50 schemas; scoped Phase 26 module scan
                                                 superseding the global Phase 27 absence
                                                 scan)
tests/test_realization_contracts.py              (count update)
tests/test_run_metric_observation_contracts.py   (count update)
tests/test_trajectory_execution_contracts.py     (count update)
```

(That is 23 mechanically migrated test paths; the remaining modified
paths are listed in 4.4-4.6. Every file in this section was migrated
for the same reason: the registry/schema cardinality moved 47 -> 50 in
one step in the registration slice so no intermediate state was
contradictory.)

### 4.4 Colony UI demo (3) + its test (1)

```text
kalhas/colony_ui/app.js       (synthetic living-colony visual prototype: fixed 24-day
                               deterministic client-side demo, no network request;
                               observatory unchanged, read-only, manual-pull)
kalhas/colony_ui/index.html   (two-surface layout: clearly labeled synthetic demo +
                               KALHAS activity observatory)
kalhas/colony_ui/styles.css   (demo styling; observatory styling preserved)
tests/test_colony_ui.py       (updated truthfulness/labeling assertions for the
                               synthetic demo separation)
```

These Colony UI changes are **intentional synthetic local
visualization work** (Section 12), not simulation evidence.

### 4.5 Documentation (4)

```text
README.md                                      (Colony two-surface rewrite [Part A] +
                                               Phase 27 status section [Part B])
docs/architecture/README.md                    (Phase 27 section [Part B])
docs/architecture/contracts-and-lifecycle.md   (Phase 27 section [Part B])
KALHAS_HANDOFF_PHASE_26.md                      (Phase 27 kickoff erratum [Part A])
```

### 4.6 This handoff (1, new)

```text
KALHAS_HANDOFF_PHASE_27.md   (this file)
```

Nothing else changed. Every production file, test, schema, historical
handoff, `AGENTS.md`, the external blueprint, profile, memory, skill,
and configuration file outside the lists above is byte-identical to
the Phase 26 baseline.

## 5. Exact schemas and tests

- `PUBLIC_CONTRACTS` is exactly **50**; indexes 0-46 are unchanged
  (the campaign outcome-distribution matrix remains at index 46); the
  exact tail is 47 `CampaignDecisionPolicy`, 48
  `CampaignStrategyComparison`, 49 `CampaignDecisionBrief`.
- `schemas/v1/` holds exactly **50** `.schema.json` artifacts; the
  three new artifacts match `model_json_schema()` byte-for-byte and
  all **47 historical schema artifacts retain their accepted SHA-256
  byte hashes** (the accepted hash table lives in
  `tests/test_api_phase27.py` and is re-verified by
  `tests/test_phase27_boundaries.py`).
- The 12 nested decision value objects (`ObjectiveWeightSnapshot`,
  `ObjectiveTargetRequirement`, `ObjectivePairedComparison`,
  `ObjectiveFeasibilityEvidence`, `ObjectiveRegretEvidence`,
  `ObjectiveProbabilityEvidence`, `ObjectiveDownsideEvidence`,
  `ObjectiveDominanceStatus`, `DominanceRelation`,
  `StrategyRobustnessProfile`, `DecisionReasonRecord`,
  `DecisionFactorRecord`) remain **unregistered** and have **no
  standalone schema files** (embedded as `$defs` only).
- `API_VERSION == "1"` and `SCHEMA_VERSION == "1.0.0"` unchanged; the
  runtime remains exactly `3.0.0`.
- Test inventory: 15 Phase 27 test paths (Section 3.5), of which
  `tests/test_phase27_acceptance.py` (42 tests) is the frozen
  100-seed causal decision proof and `tests/test_phase27_boundaries.py`
  (Section 8 of the Part B prompt) is the architectural boundary
  suite.

## 6. Policy / comparison / brief responsibilities

| Module | Responsibility |
| --- | --- |
| `campaign_decision_statistics.py` | Pure stdlib-only numeric primitives: direction-normalized `paired_delta` (positive always means the first strategy is worse), `paired_delta_vector` (identical authoritative shared-seed order), `paired_delta_statistics` (win/tie/loss counts and rates under the exact declared tolerance; median/p05/p95/worst/best), `same_seed_regret`, `objective_weighted_mean_regret`, `per_seed_total_weighted_regret`, `total_regret_vector`, `total_regret_statistics` (median/p95/maximum) - reusing the accepted Phase 22 median and Phase 26 Type-7 quantile primitives; `math.fsum` everywhere; no clock, randomness, store, or network. |
| `campaign_decision_evidence.py` | Pure `build_campaign_decision_evidence`: strict detached revalidation of policy + outcome matrix, cross-source agreement, seed-count sufficiency fact (`sufficient` when `K >= minimum_sample_count`, inclusive), per-strategy hard-gate feasibility with per-targeted-objective threshold evidence and copied target-achievement probabilities/downside evidence. Below-minimum is a successful factual assessment, never an exception. |
| `campaign_decision_paired_comparison.py` | Pure `build_ordered_objective_paired_comparisons`: exactly `S * (S - 1) * O` `ObjectivePairedComparison` records - no self-pairs, both directions of every pair, contiguous pair-major/objective-minor positions - with canonical lower-position direction computed once and exact mirror rules for the reverse record (negated deltas, swapped win/loss, preserved ties, Type-7 p05/p95 sign-flip, worst reverse = negated forward best). |
| `campaign_decision_selection.py` | Pure `build_campaign_pareto_dominance` (evidence -> dominance relations from stored paired comparisons -> non-dominated set among **feasible** strategies only; `feasible_by_position` gate before any dominance test) and `build_campaign_minimax_regret` (same-seed regret over all strategies, authoritative weights, per-seed totals, median/p95/maximum, exact inclusive minimax tie set `<= best + tolerance`; unique minimax identity only for a singleton tie set). |
| `campaign_decision_comparison_runtime.py` | Pure `build_campaign_strategy_comparison`: strict revalidation of both inputs, identity/hash verification, cross-source agreement, the paired-comparison and minimax pipeline, per-strategy `StrategyRobustnessProfile` assembly, deterministic comparison identifier/content hash, `derived_at` = outcome-matrix `derived_at` (never wall clock). |
| `campaign_decision_brief_runtime.py` | Pure `build_campaign_decision_brief`: `_derive_decision` (sufficiency gate -> hard-gate feasibility -> feasible non-dominated candidates -> best maximum total weighted regret -> inclusive tie set -> `preferred` iff singleton, else `inconclusive`; `insufficient_evidence` and `no_feasible_strategy` are successful statuses), terminal reason record, ordered decisive/blocking factor trails, and the four fixed `_SUMMARY_*` templates - no chain-of-thought, no hidden reasoning, no arbitrary scripts. |
| `campaign_decision_identity.py` | Deterministic identifiers (`campaign-decision-policy-`, `campaign-strategy-comparison-`, `campaign-decision-brief-` prefixes) and self-covering content hashes from canonical identity payloads; never from content hashes, timestamps, or the tenant. |
| `campaign_decision_errors.py` | Six safe typed errors (policy NotFound/AlreadyExists/Validation/Integrity; comparison Integrity; brief Integrity) with generic non-leaking public messages and internal `reason`. |
| `campaign_decision_policy_service.py` | `declare_campaign_decision_policy` (draft validation incl. exact objective coverage of the profile's targeted objectives, world/scenario/profile context verification, strict revalidation, deterministic construction, store write; duplicate -> typed 409, zero writes on any failure) and `get_verified_campaign_decision_policy` (strict revalidation + identity/hash verification + deep defensive copy on every read). |
| `campaign_decision_query_service.py` | Verified read-only queries `get_verified_campaign_strategy_comparison` / `get_verified_campaign_decision_brief`: campaign -> exactly COMPLETE -> **verified policy first (404 before any derivation when absent)** -> verified outcome query exactly once -> comparison builder exactly once -> (brief) scenario load + brief builder exactly once reusing the same policy/outcome/comparison chain. Comparison and brief are derived in memory and **never stored**; builder failures translate to the typed integrity errors; no execution/replay/extraction/activity/write. |
| `kalhas/contracts/v1/campaign_decision.py` | The three frozen `VersionedContract` models plus 12 nested value objects; structural shape and internal-consistency validators only (never identity/hash recomputation). |
| `kalhas/api/routes_campaign_decision.py` | Exactly four operations on three paths; recorded-runtime gate before any service call; request-to-draft conversion copying caller-owned fields only; each GET calls its verified query exactly once; direct contract responses. |
| `kalhas/api/requests_campaign_decision.py` | `CampaignDecisionPolicyDeclarationRequest` + `ObjectiveTargetRequirementRequest`: strict caller-owned validation boundary (XOR modes, probability band, exact-int minimum count, finite tolerance, finite metadata). |

## 7. API operations and error mappings

Exactly four operations on three paths (all require `X-Tenant-ID`; the
recorded `RunPlan` tuple is read first and every recorded runtime must
be exactly `3.0.0` - empty or mixed/legacy tuples fail closed with the
typed 409 before any service call; no caller runtime selector exists):

```text
POST /v1/campaigns/{campaign_id}/decision-policy       -> 201
GET  /v1/campaigns/{campaign_id}/decision-policy       -> 200
GET  /v1/campaigns/{campaign_id}/strategy-comparison   -> 200
GET  /v1/campaigns/{campaign_id}/decision-brief        -> 200
```

Typed error mappings (single `ApiErrorResponse` envelope, generic
non-leaking bodies):

- 404: unknown/foreign campaign; missing/foreign policy (comparison
  and brief return 404 **before** any outcome derivation when the
  policy is absent);
- 409 `invalid_state`: campaign not exactly COMPLETE (declaration,
  comparison, brief);
- 409 `conflict`: duplicate policy declaration; unsupported/empty
  recorded runtime;
- 422: invalid policy drafts (mode XOR, coverage, thresholds, count,
  tolerance, metadata, forged authoritative fields);
- 409 `integrity_error`: corrupted/forged/validator-bypassed stored
  policy, outcome matrix, comparison, or brief.

Read-only guarantees: the three GETs never execute, replay, extract,
evaluate, repair, write, or record operational activity; repeated GETs
are byte-identical and leave the complete store state unchanged; the
comparison and brief are never stored (the store has no collection and
no put method for them). A verified stored policy GET remains
available even after the campaign state changes away from COMPLETE.

## 8. Fixed 100-seed acceptance fixture and golden values

`tests/phase27_helpers.py` + `tests/test_phase27_acceptance.py` drive
one real end-to-end runtime-3.0.0 campaign exclusively through the
real public services: declarations (state model `sm-1` with integer
`level`/`reserve`, seven guarded causal transitions, bindings m-1 ->
level and m-2 -> reserve, discrete uncertainty `{5, 9}`/`{20, 30}` with
equal weights, two-objective evaluation profile declared **before**
compilation), world compilation, `prepare_realization_campaign` (with
the single sanctioned `EXPECTED_STRATEGY_SET_SIZE == 3` alignment for
the three-candidate acceptance LEGION adapter, scoped to the
preparation call), trajectory planning, start, 300 real executions,
and 300 explicit observation extractions; the real policy is declared
through the real policy service and the comparison/brief come only
from the real verified query services.

```text
100 fixed deterministic seeds            seed-000 ... seed-099 (first 100 identifiers
                                         in ascending order, statically present, never
                                         searched/retried/randomized/adapted)
3 genuinely distinct strategies          mock-a [t-z, t-z2, t-v, t-u]
                                         mock-b [t-x, t-w, t-y, t-u]
                                         mock-c [t-x, t-u, t-y]
300 runs / 300 executions / 300 extractions  3 strategies x 100 seeds, strategy-major
world-type split                        (5,20)=22, (5,30)=24, (9,20)=27, (9,30)=27
policy gates                             per-objective 0.40/0.40, minimum 100,
                                         tolerance 0.05, hard gates on
objective means (obj-1, obj-2)           mock-a (32.46, 25.6) | mock-b (94.26, 40.1)
                                         | mock-c (94.26, 32.75)
target-achievement probabilities         mock-a (1.0, 0.46) | mock-b (0.46, 1.0)
                                         | mock-c (0.46, 0.51) - all feasible
paired win/tie/loss counts (tol 0.05)    full 12-record matrix both directions; e.g.
                                         mock-a vs mock-b obj-1 (100,0,0), obj-2
                                         (22,24,54); mock-b vs mock-c obj-1 (0,100,0)
dominance                                only mock-b dominates mock-c; non-dominated
                                         feasible order [mock-a, mock-b]
per-world-type total weighted regret     mock-a {(5,20):0.0,(5,30):0.0,(9,20):3.0,
                                         (9,30):4.0}; mock-b {(5,20):2.24,(5,30):0.24,
                                         (9,20):0.94,(9,30):0.94}; mock-c
                                         {(5,20):3.74,(5,30):0.24,(9,20):2.44,
                                         (9,30):0.94}
total-regret aggregates (max,med,p95)    mock-a (4.0, 3.0, 4.0) | mock-b (2.24, 0.94,
                                         2.24) | mock-c (3.74, 0.94, 3.7399999999999998)
minimax                                  best maximum total weighted regret 2.24;
                                         unique tie set (mock-b); nearest competitor
                                         mock-a (4.0); gap 1.7599999999999998
brief                                    status preferred, preferred mock-b, terminal
                                         reason unique_minimax_preference (2.24, 0.05),
                                         decisive trail (feasible_candidate x3,
                                         target_feasibility_passed x6,
                                         pareto_non_dominated x2,
                                         unique_minimax_regret), blocking trail
                                         (dominated_strategy mock-c by mock-b),
                                         summary "Strategy mock-b is preferred under
                                         policy campaign-decision-policy-9caab5493c904b86:
                                         feasible, non-dominated, unique minimum
                                         maximum total weighted regret (2.24)."
golden identifiers/hashes                policy campaign-decision-policy-9caab5493c904b86
                                         / 460506bcb428aa37b60cfddbd2298d72b12d54840f4c4c9d8f2e7d14bfc017ea;
                                         comparison campaign-strategy-comparison-0538c7e968c25a5c
                                         / 8953b853eacad92a9facdd533c5162dab5d94c0a4dc883a50049626eae4fbcdd;
                                         brief campaign-decision-brief-9ac779fc1df02f5a
                                         / 141986a4e53ff769fa5dd8ea0728ad8e150113c623f9d2579174b26791fde596
```

The goldens were derived once at authoring time through the real
policy service and the real verified queries against this exact final
fixture world and are embedded as immutable constants - the acceptance
test never recomputes a decision golden through an identity or
decision function, and the fixture helper contains no comparison,
dominance, regret, minimax, or brief algorithm (its only
reconstruction logic is the independent causal transition simulation).

## 9. Tie/inconclusive control

The Phase 26 two-strategy fixture (identical per-seed outcomes, 200
runs) with the real control policy (single 0.40 gate, minimum 100,
tolerance 0.05) proves: every paired delta exactly 0.0, no dominance,
identical per-world-type regrets, minimax tie set containing **both**
strategies, brief status **inconclusive**, `preferred_strategy_id`
None, terminal blocking factor `minimax_regret_tie (0.0, 0.05)`, and
the summary "No preferred strategy is issued: 2 feasible non-dominated
strategies remain tied within the declared tolerance (0.05)." A tie
never manufactures a winner; `inconclusive` is a successful 200
result.

Control goldens: policy
`campaign-decision-policy-cc0e04078fb8d995` /
`548e7662b12f9ce635aa63d5a9954001461d204bb534b91d9b301fb3e0058921`;
comparison `campaign-strategy-comparison-58f430374f298749` /
`91ae09283299c8df3208b9d2f174d3e6b70a04493afc668d090657986ffe92f3`;
brief `campaign-decision-brief-40f80552fcaf5543` /
`89ad112839f4d9b02f044519807dfa9aa51763a919dc9d6e08e5420d7ee0a03d`.

## 10. Determinism, tenant isolation, read-only and no-persistence guarantees

- **Determinism.** No Phase 27 module uses wall clocks, randomness,
  UUIDs, process-hash dependence, network, providers, filesystem, or
  database (`datetime` appears only as the type guard for the
  caller-supplied timezone-aware `declared_at`); every timestamp
  copies a recorded lineage value; identifiers and content hashes are
  deterministic canonical derivations; repeated comparison/brief
  queries are byte-identical and the complete store digest is
  unchanged; the acceptance fixture's fixed seed tuple and all
  goldens are immutable constants, never searched or recomputed.
- **Tenant isolation.** Every store lookup, service verification, and
  route is tenant-scoped; unknown and foreign campaigns and policies
  are indistinguishable typed 404s; public error messages never leak
  hashes, identities, values, thresholds, metadata, or internal
  reasons.
- **Read-only.** The pure builders are store-free; the verified
  queries and the three GETs never execute, replay, extract,
  evaluate, repair, create, write, or record operational activity;
  the policy GET strictly revalidates and deep-copies.
- **No persistence of derived artifacts.** Only the immutable policy
  is stored (one per `(tenant_id, campaign_id)`, no
  update/delete/replace surface); the comparison and the brief have
  no collection, no put method, and are never written.

## 11. Non-goals and honest limitations

Phase 27 adds no adaptive decision-policy runtime, no Phase 28
implementation, no KALHAS-PAN, no historical benchmark, no real
LEGION/NEXUS integration, no production database/queue/auth/deployment/
command-center expansion, no live providers/network/database, and no
autonomous live action. The decision output is **evidence-based under
the declared models and policies**: it is **not calibrated**, **not
certainty**, **not a real-world prediction**, and **not a guarantee of
any outcome**; no real-world causality is claimed. The preferred
strategy is a deterministic summary of recorded evidence under the
declared policy - best ordinary mean (mock-a) is deliberately not the
robust winner in the acceptance proof. The 100-seed ensemble is an
authoring-time fixed fixture, not a sample-size justification for any
real-world claim.

## 12. Colony UI modifications (separate, intentional synthetic local visualization)

The Colony UI changes (`kalhas/colony_ui/app.js`, `index.html`,
`styles.css`, plus `tests/test_colony_ui.py`) are **intentional
synthetic local visualization work**, listed separately: they add a
clearly labeled deterministic client-side living-colony visual
prototype (fixed 24-day timeline, presentation-only animated markers,
mock metrics/signals, deterministic mock result) that performs **no
network request** and is **not simulation evidence, not decision
evidence, and not a real forecast**. The separate KALHAS operational
observatory remains strictly read-only, manual-pull, `textContent`-
only, and truthful. Nothing in the demo is produced by, or claims to
be, the KALHAS decision surface.

## 13. Final gate results (this session, exact)

All gates green after the Phase 27 boundary-test mechanical correction
(Part C); the former ruff/format/mypy blocker rows below are replaced
with the exact final results. Historical Part A/B rows are preserved
where they remain informative.

| Gate | Result |
| --- | --- |
| Part A gate: `uv run pytest -q tests/test_phase26_acceptance.py tests/test_phase27_acceptance.py` | exit 0 - **70 passed, 0 skipped, 0 failed** (28 Phase 26 + 42 Phase 27) |
| `uv run pytest -q tests/test_phase27_boundaries.py` | exit 0 - **54 passed, 0 skipped, 0 failed** (Part B collection; first run failed only on the README `calibrated forecast` overclaim phrase, fixed by the permitted Part B README edit `calibrated forecasts` -> `calibrated predictions`, then green) |
| `uv run pytest -q tests/test_phase27_acceptance.py` | not rerun separately (Part B: already proven by the Part A 70-passed gate; included in the full suite below) |
| `uv run pytest -q tests/test_api_phase27.py tests/test_phase27_boundaries.py tests/test_phase27_acceptance.py` | Part B ran `uv run pytest -q tests/test_api_phase27.py tests/test_phase27_boundaries.py` (acceptance excluded as redundant): exit 0 - **136 passed, 0 skipped, 0 failed** |
| `uv run pytest -q tests/test_phase25_boundaries.py tests/test_phase26_boundaries.py tests/test_phase27_boundaries.py` | exit 0 - **107 passed, 0 skipped, 0 failed** |
| `uv run ruff check .` | exit 0 - **All checks passed!** Final state (replaces the Part B 20-error blocker, all in `tests/test_phase27_boundaries.py`; corrected mechanically in this session: 18x E501 reflowed by `ruff format`, 1x SIM300 yoda-condition flipped by `ruff check --fix`, 1x I001 import block sorted by `ruff check --fix`). |
| `uv run ruff format --check .` | exit 0 - **290 files already formatted** (replaces the Part B `1 file would be reformatted` blocker; `tests/test_phase27_boundaries.py` is now formatted). |
| `uv run mypy kalhas tests` | exit 0 - **Success: no issues found in 275 source files** (replaces the Part B line-734 comparison-overlap error; fixed with an introspection-safe `typing.get_args` proof of the `Literal[0.95]` annotation and removal of the now-unused `Literal` import - same contract proof, no weakening). |
| `uv run python scripts/export_schemas.py --check` | exit 0 - **all schema artifacts are synchronized** |
| `git diff --check` | exit 0 - clean (also clean after the README/handoff edits) |
| `uv run pytest -q` (full suite) | exit 0 - **5411 collected: 5410 passed, 0 failed, 0 errors, 1 skipped** (the only skip is the documented AGENTS.md approval-gated `tests/test_boundaries.py::test_agents_md_contains_corrected_architecture_guidance`, expected under Part B scope); independently rerun by Codex in 724.4 s |

## 14. Known single AGENTS.md approval-gated skip

`tests/test_boundaries.py` contains the pre-existing AGENTS.md
approval-gated test. `AGENTS.md` is a protected agent-instruction file
and this session was explicitly forbidden from modifying it (Part B
prompt: "Do not modify ... AGENTS.md"). The test is therefore expected
to skip in the full suite - the only expected skip, with zero
failures/errors. No retry was attempted after the approval gate did
not produce a write (per the established protocol, the enforcement
test skips conditionally while the statement is outdated and the exact
replacement content would be delivered for user approval; none is
needed here because the Part B prompt explicitly excludes AGENTS.md
from the permitted file scope).

## 15. Closure protocol

1. **Codex independent audit** - Codex reads this handoff, re-reads
   the changed production files, inspects `git status`/diff/HEAD/
   origin/divergence directly, and runs the relevant gates
   independently.
2. **Explicit user authorization** - the user authorizes the Phase 27
   local closure commit in a separate explicit instruction.
3. **One normal local Phase 27 closure commit** - a single normal
   `git add` of exactly the Phase 27 change set (Sections 3-4) and
   one normal commit on `main` with a descriptive message. No amend,
   no squash, no rebase, no force.
4. **No push** - the commit stays local; `origin/main` remains at
   `f40e83de...` until the user separately authorizes a normal
   non-force push.
5. **Post-commit verification** - HEAD advanced to the new closure
   commit, tree/index clean, divergence `0 2`, and the full gates
   re-confirmed before any further work.

## 16. No future commit hash

No Phase 27 commit hash exists. Do not invent one. The repository
remains the final source of truth; this handoff is a pre-commit
snapshot and every claim must be re-verified against the repository at
audit time.

---

## Final checkpoint

- Phase 27: implementation-complete, gate-green locally, **not yet
  committed**, index empty, **not pushed**.
- Phase 26: committed at `886f398c...`; `origin/main` unchanged at
  `f40e83de...`; divergence `0 2`.
- Documentation: truthful Phase 27 status sections added to all three
  documentation surfaces; all stale Phase-26-checkpoint statements
  explicitly superseded; no overclaim introduced.
- Handoff: this file (SHA-256 recorded in the closure session report).
- Phase 28 and KALHAS-PAN: **not implemented**.
- Codex: orchestrator/reviewer. Hermes: external implementer
  receiving bounded prompts.
