# KALHAS handoff — completed through Phase 22

Date: 2026-08-11 (updated after the explicit push request)  
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`  
Branch: `main`  
Current HEAD: `215729d` (`KALHAS: domain-neutral decision-world kernel through Phase 22`)

## Read this first

This repository is complete and independently verified through **Phase 22**, and the
complete Phase 20, 21, and 22 implementation is **committed and pushed** to
`https://github.com/Xamposs/Encomm_Kalhas` (branch `main`) at commit `215729d`.
There are no uncommitted production or test changes. The only working-tree change is
this handoff file, updated locally so that it records the final pushed commit hash;
preserve it when moving into the next chat.

The committed state is the authoritative current implementation. Do not reset, revert,
discard, overwrite, or selectively reconstruct history.

Before doing any work:

1. Read `AGENTS.md` completely.
2. Read this handoff completely.
3. Inspect `git status --short` and preserve every existing change.
4. Run the baseline gates listed below.
5. Commit or push only when the user explicitly asks.
6. Phase 23 has not started.

## What the project is

KALHAS is the domain-neutral deterministic decision-world kernel of Encomm.

- **NEXUS** owns natural-language dialogue, organizational context, memory, and
  presentation.
- **LEGION** owns strategy and agent exploration.
- **KALHAS** owns versioned world models, uncertainty, deterministic simulation
  campaigns, evidence, replay, and the future living-simulation experience.

Only these three component roles exist. KALHAS core must never import NEXUS or LEGION
internals. Coupling is allowed only through the placeholder protocols under
`kalhas/adapters/`.

The current MVP is intentionally local-only:

- no real NEXUS or LEGION connection;
- no providers or network calls from the application;
- no live actions;
- no filesystem/database persistence;
- the FastAPI application uses `MockNexusAdapter`, `MockLegionAdapter`, and an
  in-memory store;
- all runtime data disappears when the application process reloads or restarts.

## Non-negotiable architecture rules

- The `kalhas/` kernel remains domain-neutral.
- Domain concerns enter only through declarative domain packs and the `DomainPack`
  protocol.
- Deterministic replay and fair strategy comparison are mandatory.
- Versioned public v1 contracts are frozen. Never mutate an existing v1 wire
  contract in place; append a compatible new contract or create a future v2 when a
  breaking change is genuinely required.
- Every behavioral change ships with tests.
- No real company or personal data belongs in code, fixtures, tests, or docs.
- No new component or integration surface beyond NEXUS, LEGION, and KALHAS.

## Current completed flow

The implemented deterministic flow is now:

```text
ScenarioSpec
  -> immutable compiled WorldVersion
  -> fair strategy x shared-seed RunPlan campaign
  -> runtime 2.0.0 trajectory plans
  -> verified RunTrajectoryExecution per run
  -> verified CampaignTrajectoryMatrix (Phase 18)
  -> declarative metric-to-final-state bindings (Phase 19)
  -> verified RunMetricObservationSet per run (Phase 20)
  -> verified CampaignMetricObservationMatrix (Phase 21)
  -> deterministic CampaignMetricStatisticsMatrix (Phase 22)
```

The pipeline currently reaches deterministic descriptive statistics. It does **not**
yet produce semantic outcomes, evidence, rankings, winners, recommendations, or
decision briefs.

## Phase 20 — verified run metric observations

Phase 20 connects each declared scenario metric to the numeric final-state field
selected by its Phase 19 `DomainMetricObservationBinding`.

Main artifact:

- `RunMetricObservationSet`, the 33rd registered public contract.

Main behavior:

- explicit post-execution extraction from a fully verified runtime 2.0.0
  `RunTrajectoryExecution`;
- bindings are taken only from the exact compiled world of the run;
- values are read only from the verified `final_state`;
- strict numeric typing: booleans are not integers, strings are not coerced, and
  NaN/Infinity are rejected;
- integer raw values remain integers and float raw values remain floats;
- immutable per-tenant/per-run storage with strict revalidation and deep copies;
- deterministic regeneration verifies stored artifacts;
- extraction is never automatic.

API:

- `POST /v1/runs/{run_id}/metric-observations`
- `GET /v1/runs/{run_id}/metric-observations`

Important correctness fix: verification compares canonical JSON rather than ordinary
Python equality, preventing a tampered boolean from passing because `True == 1`.

## Phase 21 — campaign metric-observation matrix

Phase 21 assembles every verified Phase 20 run observation set into the exact fair
strategy × identical-shared-seed layout already proven by Phase 18.

Main artifact:

- `CampaignMetricObservationMatrix`, the 34th registered public contract.

Main behavior:

- the Phase 18 `CampaignTrajectoryMatrix` is the authoritative cell layout;
- one already-existing, fully verified Phase 20 set is required for every run;
- missing sets are never extracted automatically;
- exact raw values and binding/run provenance are preserved;
- the matrix is complete or rejected — partial matrices are never returned;
- assembled in memory, read-only, and never stored.

API:

- `GET /v1/campaigns/{campaign_id}/metric-observation-matrix`

No aggregation, outcomes, rankings, or recommendations are produced here.

## Phase 22 — deterministic campaign metric statistics

Phase 22 derives fixed descriptive statistics per strategy and metric from the
verified Phase 21 raw observation matrix.

Main artifact:

- `CampaignMetricStatisticsMatrix`, the 35th and latest registered public contract.

Nested summary:

- `CampaignStrategyMetricStatistics` remains nested and is not independently
  registered.

The fixed standard-library-only algorithm is:

- minimum/maximum: extrema of the finite observations, represented only when the
  exact extrema are safely representable by the contract;
- arithmetic mean: `math.fsum(float(value) for value in values) / N`;
- median: numeric sort; middle value for odd N, arithmetic midpoint for even N;
- population standard deviation: denominator N, never N−1;
- one observation has population standard deviation exactly `0.0`.

Exact raw observations remain separately preserved in seed order. If an integer is
too large for a finite/safe derived-float representation, or any statistic becomes
non-finite, the complete calculation is rejected. Values are never silently clamped,
rounded, repaired, or partially returned.

The implementation intentionally does not interpret `MetricDefinition.aggregation`.
Phase 22 has one fixed descriptive-statistics definition.

API:

- `GET /v1/campaigns/{campaign_id}/metric-statistics`

The statistics matrix is built in memory from the verified Phase 21 query. It is
GET-only, read-only, all-or-nothing, and never stored.

## Public-contract tail

`PUBLIC_CONTRACTS` currently contains exactly 35 contracts. The tail ordering is
important and is covered by regression tests:

```text
CampaignTrajectoryMatrix
DomainMetricObservationBinding
RunMetricObservationSet
CampaignMetricObservationMatrix
CampaignMetricStatisticsMatrix
```

Do not reorder these or mutate their existing fields.

## Important files added in Phases 20–22

Contracts:

- `kalhas/contracts/v1/run_metric_observation.py`
- `kalhas/contracts/v1/campaign_metric_observation.py`
- `kalhas/contracts/v1/campaign_metric_statistics.py`

Application services/runtimes:

- `kalhas/application/run_metric_observation_service.py`
- `kalhas/application/campaign_metric_observation_runtime.py`
- `kalhas/application/campaign_metric_observation_query_service.py`
- `kalhas/application/campaign_metric_statistics_runtime.py`
- `kalhas/application/campaign_metric_statistics_query_service.py`

Schemas:

- `schemas/v1/RunMetricObservationSet.schema.json`
- `schemas/v1/CampaignMetricObservationMatrix.schema.json`
- `schemas/v1/CampaignMetricStatisticsMatrix.schema.json`

Focused tests and helpers:

- `tests/phase20_helpers.py`
- `tests/phase21_helpers.py`
- `tests/phase22_helpers.py`
- `tests/test_run_metric_observation_contracts.py`
- `tests/test_run_metric_observation_service.py`
- `tests/test_run_metric_observation_store.py`
- `tests/test_run_metric_observation_integrity.py`
- `tests/test_api_phase20.py`
- `tests/test_phase20_boundaries.py`
- `tests/test_campaign_metric_observation_contracts.py`
- `tests/test_campaign_metric_observation_runtime.py`
- `tests/test_campaign_metric_observation_query_service.py`
- `tests/test_api_phase21.py`
- `tests/test_phase21_boundaries.py`
- `tests/test_campaign_metric_statistics_contracts.py`
- `tests/test_campaign_metric_statistics_runtime.py`
- `tests/test_campaign_metric_statistics_query_service.py`
- `tests/test_api_phase22.py`
- `tests/test_phase22_boundaries.py`

Tracked files also contain required Phase 20–22 changes, including API routes/error
mapping, domain errors, store support for Phase 20, public-contract registration,
schema payload tests, historical contract-count assertions, README, and architecture
documentation.

## Verified final gates

The Phase 22 final state was independently verified on 2026-08-11:

```powershell
uv run python scripts/export_schemas.py --check
# all schema artifacts are synchronized

uv run pytest
# 1982 passed, 1 skipped, 2 warnings; exit 0

uv run ruff check .
# All checks passed!

uv run ruff format --check .
# 170 files already formatted

uv run mypy kalhas tests
# Success: no issues found in 161 source files

git diff --check
# clean
```

Focused Phase 22 suites: 166 passed.

Known non-blocking baseline diagnostics:

- one pre-existing conditional skip concerning the historical `AGENTS.md` statement;
- one pre-existing Starlette/httpx TestClient deprecation warning;
- one intentional Pydantic serializer warning from a validator-bypass adversarial
  test. The malformed value is correctly rejected.

Always rerun the full gates after any future change. Do not rely only on this recorded
result.

## Local application and UI

Start the local in-memory application with:

```powershell
uv run uvicorn kalhas.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Open:

- Swagger: `http://127.0.0.1:8000/docs`
- Encomm Colony: `http://127.0.0.1:8000/colony/`

Operational notes:

- Use the same `X-Tenant-ID` in headers, request bodies where applicable, and the
  Colony tenant field.
- Colony is pull-based observability, not a live streaming simulator. Press Refresh.
- A successful API operation is required before a relevant Colony event can appear.
- Restarting/reloading the application clears all in-memory data.
- Colony remains read-only and does not affect deterministic hashes or replay.

## Phase 23 — not started

The next logical phase is deterministic **outcome interpretation** built on the
verified Phase 22 statistics, without ranking or recommendations.

Before designing or implementing Phase 23, audit the existing frozen v1 contracts:

- `MetricOutcome`
- `OutcomeVector`
- `DistributionSummary`
- scenario metric direction, target, unit, and declared aggregation fields

Do not mutate those frozen contracts. Decide explicitly whether they can express the
required provenance and exact numeric semantics. If they cannot, append a compatible
new artifact rather than changing an existing contract.

A safe Phase 23 boundary should initially remain:

- deterministic and read-only;
- based only on the fully verified Phase 22 statistics artifact;
- no strategy ranking or winner selection;
- no recommendations or DecisionBrief;
- no evidence fabrication;
- no domain-specific rules;
- no NEXUS/LEGION integration;
- no operational-activity or Colony changes;
- no new runtime version;
- no automatic execution, replay, or observation extraction;
- no persistence or external providers.

Do not begin Phase 23 implementation until its exact contract and semantic rules have
been reviewed against the frozen v1 surface.

## Recommended working protocol for the next chat

1. Read `AGENTS.md` and this handoff.
2. Confirm `HEAD == 215729d` and that the complete Phase 20–22 implementation is
   committed and pushed to `origin/main`.
3. Run all baseline gates.
4. Inspect the Phase 22 implementation and final documentation.
5. Define the exact Phase 23 contract and non-goals before editing.
6. Implement in a focused phase with adversarial tests.
7. Run schema, full pytest, ruff, format, mypy, and diff gates.
8. Produce an honest final report.
9. Do not commit or push unless explicitly authorized.

## Copy/paste starter for a new chat

```text
Work in C:\Users\xampos\Desktop\Encomm-Kalhas.

Read AGENTS.md and KALHAS_HANDOFF_PHASE_22.md completely before taking action.
The repository is complete and independently verified through Phase 22 and the
complete Phase 20–22 implementation is committed and pushed to origin/main at
HEAD 215729d. The only expected local working-tree change is the updated handoff
file itself. Preserve every existing change: do not reset, revert, or discard.
Commit or push only when the user explicitly asks.

First confirm the current baseline with schema export, full pytest, ruff check, ruff
format check, mypy, and git diff --check. Then inspect the frozen v1 outcome-related
contracts and propose the precise Phase 23 deterministic outcome-interpretation
scope, contract, invariants, tests, API, and non-goals before implementing anything.
Phase 23 must not introduce ranking, winner selection, recommendations, DecisionBrief,
real NEXUS/LEGION integration, live actions, providers, persistence, operational
activity, Colony changes, or a new runtime version.
```

## External skill note

An external `kalhas-project` skill was updated by a previous session. That skill is
not part of this repository and is not authoritative over `AGENTS.md`, repository
code, tests, or this handoff. Do not modify external skills as part of future KALHAS
phases unless the user explicitly requests it.
