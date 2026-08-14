# KALHAS Handoff — Phase 25 Closure Complete (Local Commit, Not Pushed)

Date: 2026-08-14  \
Repository: `C:\Users\xampos\Desktop\Encomm-Kalhas`  \
Branch: `main`  \
Current HEAD: the local Phase 25 closure commit containing this handoff  \
(subject `Phase 25: complete realization-aware runtime 3.0.0 closure`;  \
parent `f40e83de468ca14100d011454d15eb3dd561c810`)  \
Remote: `origin/main == f40e83de468ca14100d011454d15eb3dd561c810`  \
Push status: **not pushed** - local `main` is exactly one commit ahead  \
of `origin/main`. Push is intentionally deferred until Phases 26 and 27  \
are complete. Working tree and index are clean.

> **Correction notice.** This handoff replaces the previous premature
> `KALHAS_HANDOFF_PHASE_25.md`, which falsely claimed Phase 25 was fully
> committed and pushed at `58a7b71`. The truth: `58a7b71` committed the
> bulk of the runtime-3 subsystem, `f40e83d` added only the stale handoff
> document, and the Phase 25 **tail** (mock differentiation, API
> assembly, observation/statistics matrices, acceptance fixture,
> boundary tests, documentation, and this handoff correction) is
> complete and is incorporated by the local Phase 25 closure commit
> containing this handoff (**not pushed**).

## 1. Read this first

Phase 25 (the deterministic realization-aware trajectory runtime 3.0.0)
is **implementation-complete and gate-green**, and the complete Phase 25
change set is included in one local closure commit - the local Phase 25
closure commit containing this handoff. Every slice was reviewed and
accepted by Codex, including the seven corrective micro-slices listed in
Section 5. This closure slice added the causal 84/103 acceptance
fixture, the Phase 25 boundary suite, the runtime-3 documentation, and
the truthful handoff. The commit is **not pushed**; `origin/main` remains
at `f40e83de468ca14100d011454d15eb3dd561c810` and local `main` is
exactly one commit ahead.

## 2. Committed change set (exact)

**Pre-commit Phase 25 closure change set incorporated by this commit**
(17 paths - 9 modified, 8 untracked - exactly the paths staged and
committed by this commit):

```text
 M KALHAS_HANDOFF_PHASE_25.md
 M README.md
 M docs/architecture/README.md
 M docs/architecture/contracts-and-lifecycle.md
 M kalhas/adapters/mocks/legion.py
 M kalhas/api/app.py
 M kalhas/api/routes.py
 M tests/phase25_helpers.py
 M tests/test_realization_campaign_matrices.py
?? kalhas/api/routes_realization.py
?? kalhas/application/realization_campaign_metric_observation_query_service.py
?? kalhas/application/realization_campaign_metric_observation_runtime.py
?? kalhas/application/realization_campaign_metric_statistics_query_service.py
?? kalhas/application/realization_campaign_metric_statistics_runtime.py
?? tests/test_api_phase25.py
?? tests/test_phase25_boundaries.py
?? tests/test_realization_strategy_declarations.py
```

- HEAD is the local Phase 25 closure commit containing this handoff;
  `origin/main` remains at `f40e83de468ca14100d011454d15eb3dd561c810`
  (local `main` is exactly one commit ahead).
- The working tree and index are clean (post-commit `git status --short`
  is empty and `git diff --cached` is empty).
- `KALHAS_HANDOFF_PHASE_22.md` MD5 `d6a857f091bcf7ab596583054b55659e`
  and `KALHAS_HANDOFF_PHASE_24.md` SHA-256
  `8616d45e0c4727cbf027b7a3f133e749c33d2a6a328c6d6668c2e5f1108ea652`
  are preserved byte-for-byte (unmodified by every Phase 25 slice).
- **No production file was changed by this closure slice.** The eight
  production paths (`kalhas/adapters/mocks/legion.py`,
  `kalhas/api/app.py`, `kalhas/api/routes.py`,
  `kalhas/api/routes_realization.py`,
  `kalhas/application/realization_campaign_metric_observation_query_service.py`,
  `kalhas/application/realization_campaign_metric_observation_runtime.py`,
  `kalhas/application/realization_campaign_metric_statistics_query_service.py`,
  `kalhas/application/realization_campaign_metric_statistics_runtime.py`)
  were delivered by the earlier accepted slices and are listed here
  only for completeness; none of these eight production files was
  changed by the final closure session - it touched tests and
  documentation only.
- `PUBLIC_CONTRACTS == 46`; `schemas/v1/` == exactly 46 `.schema.json`
  artifacts.

## 3. Delivered architecture (every layer)

- **Contracts** (`kalhas/contracts/v1/`): six new public contracts
  appended at `PUBLIC_CONTRACTS` indexes 40-45 in this exact order -
  `RealizationRunTrajectoryExecution`,
  `RealizationRunTrajectoryReplayManifest`,
  `RealizationCampaignTrajectoryMatrix`,
  `RealizationRunMetricObservationSet`,
  `RealizationCampaignMetricObservationMatrix`,
  `RealizationCampaignMetricStatisticsMatrix`; three nested unregistered
  value objects; six new schema artifacts (46 total); indexes 0-39 and
  all 40 historical schema artifacts unchanged.
- **Planner** (`run_planner.py`, additive): `REALIZATION_TRAJECTORY_RUNTIME_VERSION
  == "3.0.0"`, `run_realization_input_hash` (world/strategy/seed/
  world-realization-content-hash payload), `plan_realization_runs`
  (strategy-major/seed-minor, identical plan identifiers, per-seed
  realization binding). Runtime-2 `run_input_hash`/`plan_runs` have
  zero source-line changes.
- **Identity / errors / store** (`realization_identity.py`,
  `realization_errors.py`, `in_memory_store.py`, `api/errors.py`):
  deterministic runtime-3 identifiers and self-covering content hashes,
  twelve typed errors (404/409/422 mapped), three strict revalidating
  store collections (execution, replay manifest, observation set;
  identical writes idempotent, differing writes rejected), and
  `verify_realization_provenance`.
- **Integrity** (`input_integrity.py`, `run_trajectory_inputs.py`):
  single-pass, version-dispatched verification - load and verify every
  authoritative record, then recompute only the input hash on the
  recorded version; for 3.0.0 the Phase 24 realization is reconstructed
  exactly once at `run_plan.created_at` (never resampled) and the
  runtime-3 digest is recomputed. 1.0.0/2.0.0 branches execute the
  historical statements byte-identically. `VerifiedRunTrajectoryInputs`
  is the single runtime-3 verification entry with realization
  provenance re-derivation.
- **Preparation / preflight** (`realization_campaign_service.py`,
  `campaign_service.py`, `strategy_trajectory_service.py`):
  `prepare_realization_campaign` gates on exactly 3.0.0 before any
  store read, verifies world integrity and stored-vs-embedded model
  consistency, builds the `CampaignWorldRealizationMatrix` exactly once
  (K realizations, never K x S, derived never stored), and plans the
  run matrix. `preflight_realization_run_plan_matrix` is the read-only
  complete-matrix proof (exact tuple equality + per-run verification);
  trajectory planning dispatches its preflight from the recorded
  runtime.
- **Execution** (`realization_trajectory_runtime.py`,
  `realization_integrity.py`, `realization_execution.py`): pure
  `build_realization_run_trajectory_execution` evaluates the exact plan
  tuple from the realized initial state through the real engine;
  `execute_realization_campaign` preflights the complete stored matrix
  exactly once, then executes every run in exact stored order with
  deterministic write order and build-then-write atomicity; attempt
  records are bound position-by-position to the authoritative plan
  references; `executed_at` = `run_plan.created_at`.
- **Observations** (`realization_run_metric_observation_service.py`):
  explicit extraction (one immutable set per run, second extraction
  rejected even when byte-identical), final-state-only
  numeric-kind-strict raw values, unit from the embedded scenario,
  `observed_at` = `execution.executed_at`; verified read-only query;
  extraction records no activity.
- **Replay** (`realization_replay.py`): observation-aware exact replay
  that **requires prior extraction** (typed 404 with zero writes
  otherwise), independently regenerates execution + observation set +
  structural events, requires canonical-JSON equality, and writes the
  manifest pair (version-agnostic `ReplayManifest` + self-covering
  `RealizationRunTrajectoryReplayManifest` with expected/recomputed
  execution and observation-set hashes); idempotent on repetition;
  sequential two-manifest write limitation with idempotent recovery
  (missing manifest completed with identical bytes; corrupted manifest
  blocks replay, never overwritten).
- **Three matrices** (`realization_campaign_trajectory_runtime.py` +
  query, `realization_campaign_metric_observation_runtime.py` + query,
  `realization_campaign_metric_statistics_runtime.py` + query): pure
  derived builders + strictly read-only verified queries - trajectory
  matrix (strategy-major/seed-minor cells, seed-aligned realization
  tuples, cell<->tuple agreement), observation matrix (per-cell
  verified observation sets, preserved raw values), statistics matrix
  (descriptive statistics only through the frozen Phase 22 functions).
  All derived, never stored; zero writes, zero activity, byte-identical
  repeats.
- **Mock differentiation** (`kalhas/adapters/mocks/legion.py`): the
  fail-closed `MockLegionAdapter(declared_transition_sequences=...)`
  declaration seam - logical transition ids resolved to the
  deterministic identifiers of the request's closed catalog in exact
  declared order (repetitions preserved); unknown or ambiguous ids
  raise `InvalidTrajectoryDraftError` (never a canonical fallback,
  never a partial draft); canonical default only for undeclared
  strategies; KALHAS re-validates every draft.
- **API assembly** (`kalhas/api/routes_realization.py`, `routes.py`,
  `app.py`, `errors.py`): exactly 6 new paths / 7 operations; recorded-
  runtime dispatch on preparation/execute/replay; seven runtime-2
  artifact gates (recorded 3.0.0 -> 409 before the service); empty-plan
  tuples fail closed; GETs read-only with no activity; extraction
  records no activity; single `ApiErrorResponse` envelope unchanged;
  `InvalidTrajectoryDraftError` mapped to 422.
- **Acceptance fixture** (`tests/phase25_helpers.py` +
  `TestAcceptanceFixtureCausal84_103` in
  `test_realization_campaign_matrices.py`): the causal 84/103 proof
  (Section 6) through the real lifecycle with a test-only
  two-candidate `AcceptanceLegionAdapter` (the preparation service's
  `EXPECTED_STRATEGY_SET_SIZE` is aligned to 2 only inside the single
  preparation call and is proven fully restored to 5 afterwards).
- **Boundaries** (`tests/test_phase25_boundaries.py`, 27 tests):
  AST/symbol-precise architectural scans - domain-neutral kernel, no
  NEXUS/LEGION internals, LEGION only at planning boundaries, no
  network/provider/database/filesystem/wall-clock/randomness surface,
  derived realizations and matrices never stored, query services
  strictly read-only, runtime-2/Phase-24 modules carry no runtime-3
  dependency, 46 contracts with exact 0-39 prefix and exact runtime-3
  tail, 46 schemas, exactly 6 paths / 7 operations, no Phase 26/27
  surface, no outcome/ranking/score/evidence/recommendation surface,
  typed errors all mapped, routes record no activity.
- **Documentation**: README.md, docs/architecture/README.md, and
  docs/architecture/contracts-and-lifecycle.md each gained a Phase 25
  section that explicitly supersedes the historical "Phase 25 has not
  started" statements.

## 4. Final gate results (this run, exact)

| Gate | Result |
|---|---|
| 1. `pytest -q tests/test_realization_campaign_matrices.py` | exit 0 (217 tests) |
| 2. `pytest -q tests/test_phase25_boundaries.py` | exit 0 (27 tests) |
| 3. `pytest -q tests/test_api_phase25.py` | exit 0 (36 tests) |
| 4. Complete focused Phase 25 suite (16 files) | exit 0 (806 tests) |
| 5. `ruff check .` | All checks passed |
| 6. `ruff format --check .` | 241 files already formatted |
| 7. `mypy kalhas tests` | Success: no issues in 229 source files |
| 8. `python scripts/export_schemas.py --check` | all schema artifacts are synchronized |
| 9. Full `pytest -q` | exit 0 - **3214 passed, 1 skipped** (the single skip is the pre-existing approval-gated `test_boundaries.py` AGENTS.md test; the known Phase-23 uuid-"91" flake did not occur, so no rerun protocol was needed) |
| 10. `git diff --check` | clean |

Additional verifications (at the time of that run): `git diff --cached`
empty; HEAD == `origin/main` ==
`f40e83de468ca14100d011454d15eb3dd561c810`; Phase 22 MD5 and Phase 24
SHA-256 as listed in Section 2; 46 public contracts; 46 schema
artifacts. (HEAD has since advanced to the local Phase 25 closure commit
containing this handoff; `origin/main` is unchanged.)

## 5. Corrective micro-slices (all accepted)

1. **Exact attempt<->plan binding** - fully-rehashed alternate-
   transition attack closed by position-by-position reference equality
   (sequence position, transition identifier, logical id, content
   hash) against `plan.transition_references`.
2. **Complete campaign matrix preflight** - truncated/reordered/tampered
   run-plan matrices fail before any write; `execute_realization_campaign`
   calls the read-only matrix preflight exactly once before the first run.
3. **Observation execution provenance** - the pure observation builder
   binds execution tenant, world version, strategy content hash (and
   every aggregate provenance field) before any catalog/final-state work.
4. **Replay tenant ownership** - the replay-manifest verifier enforces
   `manifest.tenant_id == inputs.run_plan.tenant_id` independently of
   hashes.
5. **World-tenant/seed-content matrix binding** - the trajectory-matrix
   builder rejects foreign-tenant worlds and alternate seed material via
   exact canonical checks before any plan-hash work.
6. **Observation-matrix strict trust boundary** - the observation-matrix
   builder strictly revalidates every supplied artifact and rejects
   missing/foreign/reordered observation sets with zero tolerance.
7. **Empty-plan API fail-closed behavior** - execute and the three
   realization campaign GETs reject empty run-plan tuples with the
   typed 409 before any service call, artifact read, or write.

## 6. Causal 84/103 acceptance proof

The fixture declares a discrete uncertainty binding on the integer
`level` field with branch values X=5 / Y=9 and two guarded transitions:
`t-x` (guard `level == 5`, target `level -> 84`) and `t-y`
(guard `level == 9`, target `level -> 103`). The test-only
`AcceptanceLegionAdapter` returns exactly two strategies -
`mock-a` declaring the plan `[t-x, t-y]` and `mock-b` declaring
`[t-y, t-x]` (genuinely different authoritative reference orders) -
and exactly two fixed seeds are used: `seed-0` deterministically
realizes branch X (level 5), `seed-2` branch Y (level 9), proven by the
fixture itself.

Under both strategies, exactly one guard succeeds per seed, and the
real state-transition engine produces:

- `seed-0` -> realized level 5 -> `t-x` applied (guard matched) ->
  final observed value **84**; `t-y` then `guard_not_satisfied`.
- `seed-2` -> realized level 9 -> `t-y` applied (guard matched) ->
  final observed value **103**; `t-x` then `guard_not_satisfied`.

Attempt records prove the correct guarded transition produced each
value (`applied` / `guard_not_satisfied` per position, differing per
strategy: `mock-a` = X-then-Y, `mock-b` = Y-then-X). The campaign has
exactly 2 strategies, 2 seeds, 2 aggregate realizations (never 2 x 2),
and 4 run plans/executions/observation cells in exact
strategy-major/seed-minor order; the same seed binds the identical
realization id/content hash across both strategies. Observation matrix
values per strategy are exactly `[84, 103]` in seed order; per-strategy
statistics are minimum 84.0, maximum 103.0, arithmetic mean 93.5,
median 93.5, population standard deviation 9.5. Replay regenerates the
same execution and observation hashes (manifest pair attests
expected == recomputed); repeated preparation and queries are
byte-deterministic; no input contract is mutated; no
rankings/scores/outcomes/evidence/recommendations/domain-pack execution
occur. Every value is produced by the real lifecycle - nothing is
copied into expected artifacts.

## 7. Exact API surface (6 paths / 7 operations)

1. GET `/v1/runs/{run_id}/realization-trajectory-execution`
2. GET `/v1/runs/{run_id}/realization-trajectory-replay-manifest`
3. POST `/v1/runs/{run_id}/realization-metric-observations` (201)
4. GET `/v1/runs/{run_id}/realization-metric-observations`
5. GET `/v1/campaigns/{campaign_id}/realization-trajectory-matrix`
6. GET `/v1/campaigns/{campaign_id}/realization-metric-observation-matrix`
7. GET `/v1/campaigns/{campaign_id}/realization-metric-statistics`

All operations reject recorded runtime != 3.0.0 with 409 before any
downstream call; the runtime-2 artifact endpoints reject recorded 3.0.0
with 409; the six GETs are read-only and record no operational
activity; extraction records no activity.

## 8. Remaining work

- **Push the local Phase 25 closure commit to `origin/main`** - push is
  intentionally deferred until Phases 26 and 27 are complete
  (orchestrator/maintainer action on explicit request; intentionally
  not done here).
- **Phase 26 / Phase 27** have **not** begun and are not implemented or
  designed anywhere in this repository.
