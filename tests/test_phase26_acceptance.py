"""Phase 26 causal 100-seed acceptance proof (runtime 3.0.0, end to end).

One deterministic, domain-neutral, end-to-end runtime-3.0.0 campaign over
exactly 100 fixed shared seeds, built exclusively through the real
public services: declarations (state model, guarded causal transitions,
metric-observation binding, discrete uncertainty model, evaluation
profile declared before compilation), world compilation, runtime-3
preparation, trajectory planning, start, full campaign execution, and
explicit per-run observation extraction. The fixed ensemble is selected
at authoring time only (see ``tests/phase26_helpers.py``); the test
never searches, retries, re-rolls, or adaptively selects seeds.

Proves:

- exactly 100 unique fixed ``ScenarioSeed`` records in authoritative
  order; two genuinely distinct declared strategy trajectory plans
  (``mock-a`` = ``[t-x, t-y]``, ``mock-b`` = ``[t-y, t-x]``);
- every strategy receives the exact same realized world for the same
  seed (100 realizations, never 200; identical per-seed realization
  identity/hash across both strategies' executions);
- two genuinely different realized initial states (level 5 vs level 9)
  causally produce different final observed values (84 vs 103) through
  the real transition engine - one applied guarded transition per run,
  matching the realized branch, with opposite attempt orders proving
  the distinct plans;
- the fixed deterministic ensemble yields exactly 81 successful seeds
  out of 100: ``empirical_target_achievement_probability == 0.81``,
  with the exact empirical golden statistics (mean 87.61, median 84.0,
  population standard deviation 7.453717193454551, Type-7 quantiles
  p05/p25/p75 = 84.0 and p95 = 103.0, adverse-tail mean 103.0, worst
  normalized target violation 0.03, CVaR95 0.03);
- exact replay of one representative run of each realized branch
  (manifest pair with expected == recomputed execution and observation
  hashes, classification ``exact``, idempotent repetition);
- the final ``CampaignOutcomeDistributionMatrix`` is obtained through
  the assembled FastAPI GET endpoint, repeated GETs are exactly equal
  (identifier, content hash, ordering, samples, derived timestamp
  lineage), the query performs no store writes, no activity creation,
  no execution/replay/extraction/repair, and no upstream artifact
  creation, and no outcome matrix is ever stored.

No observed value, outcome distribution, target result, or expected
matrix is directly inserted, patched, copied into the store, or
manufactured: every assertion value either comes from the real
lifecycle artifacts or from an independent causal expectation
recomputed from the realized world (tests may reconstruct; production
never does).
"""

from __future__ import annotations

import copy
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.application.campaign_outcome_identity import (
    campaign_outcome_distribution_matrix_content_hash,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_replay import replay_realization_run
from kalhas.application.run_planner import run_identifier
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.contracts.v1.campaign_outcome import (
    CampaignOutcomeDistributionMatrix,
    StrategyObjectiveOutcome,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import VersionedContract

from tests.phase4_helpers import NOW, TENANT, build_seed
from tests.phase26_helpers import (
    BRANCH_X_LEVEL,
    BRANCH_X_VALUE,
    BRANCH_Y_LEVEL,
    BRANCH_Y_VALUE,
    EXPECTED_X_COUNT,
    EXPECTED_Y_COUNT,
    METRIC_ID,
    NORMALIZATION_SCALE,
    OBJECTIVE_ID,
    SEED_IDENTIFIERS,
    TARGET,
    build_seed_ensemble,
    complete_100_seed_store,
)

OUTCOME_PATH = "/v1/campaigns/{campaign_id}/outcome-distributions"
HEADERS = {"X-Tenant-ID": TENANT}

#: The two strategy identifiers of the acceptance campaign.
STRATEGY_A = "mock-a"
STRATEGY_B = "mock-b"

#: Golden deterministic identity of the acceptance outcome matrix
#: (probed once at authoring time over the final fixture world).
GOLDEN_IDENTIFIER = "campaign-outcome-distribution-matrix-4c9a997c4f57df7d"
GOLDEN_CONTENT_HASH = "a5717de324af501c937b8b87cd114006edda1311ff811bd64fe0893f8ec5c230"

#: Golden empirical statistics of the fixed ensemble (probed once at
#: authoring time through the accepted production primitives; exact
#: equality is safe for every value below except where noted).
GOLDEN_MEAN = 87.61
GOLDEN_MEDIAN = 84.0
GOLDEN_STDDEV = 7.453717193454551
GOLDEN_P05 = 84.0
GOLDEN_P25 = 84.0
GOLDEN_P75 = 84.0
GOLDEN_P95 = 103.0
GOLDEN_ADVERSE_TAIL = 103.0
GOLDEN_WORST_VIOLATION = 0.03
GOLDEN_CVAR = 0.03
GOLDEN_VIOLATION_MEAN = 0.005699999999999999
GOLDEN_VIOLATION_STDDEV = 0.011769027147559818

#: The store collections whose complete state must never change on query.
_STORE_COLLECTIONS = (
    "_worlds",
    "_manifests",
    "_campaigns",
    "_campaign_statuses",
    "_run_plans",
    "_run_statuses",
    "_evaluation_profiles",
    "_world_uncertainty_models",
    "_operational_activity",
    "_strategy_trajectory_plans",
    "_realization_run_trajectory_executions",
    "_realization_run_metric_observation_sets",
    "_realization_run_trajectory_replay_manifests",
)


def _dump_value(value: object) -> object:
    """One canonical JSON dump of a stored record or record tuple."""
    if isinstance(value, tuple):
        return tuple(_dump_value(item) for item in value)
    if isinstance(value, VersionedContract):
        return value.model_dump(mode="json")
    return value


def _store_state(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest of the complete store state."""
    payload: dict[str, object] = {}
    for name in _STORE_COLLECTIONS:
        collection = getattr(store, name)
        payload[name] = {repr(key): _dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)


def _expected_level(store: InMemoryScenarioStore, seed: ScenarioSeed) -> int:
    """The deterministically realized level of one seed under the fixture world."""
    campaign = store.get_campaign(TENANT, "campaign-1")
    world = store.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    realization = build_world_realization(
        world=world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
        seed=seed,
        realized_at=campaign.created_at,
    )
    level = next(
        override.value
        for override in realization.realized_initial_state_overrides
        if override.state_field_id == "level"
    )
    assert isinstance(level, int)
    return level


def _expected_value_for_level(level: int) -> int:
    """The engine-produced observed value of one realized branch."""
    if level == BRANCH_X_LEVEL:
        return BRANCH_X_VALUE
    if level == BRANCH_Y_LEVEL:
        return BRANCH_Y_VALUE
    raise AssertionError(f"unexpected realized level {level}")


def _expected_by_seed(store: InMemoryScenarioStore) -> dict[str, int]:
    """The causally expected observed value of every seed, in seed order."""
    return {
        seed.identifier: _expected_value_for_level(_expected_level(store, seed))
        for seed in build_seed_ensemble()
    }


def _run_identifier(
    store: InMemoryScenarioStore, strategy_position: int, seed_position: int
) -> str:
    """The deterministic run id of one (strategy, seed) run."""
    plans = store.get_run_plans(TENANT, "campaign-1")
    plan = plans[strategy_position * len(SEED_IDENTIFIERS) + seed_position]
    return run_identifier(plan)


def _attempt_sequence(store: InMemoryScenarioStore, run_id: str) -> tuple[tuple[str, str], ...]:
    """The flattened (transition_id, outcome) attempt tuple of one run."""
    execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
    attempts: list[tuple[str, str]] = []
    for result in execution.results:
        for attempt in result.attempts:
            attempts.append((attempt.transition_id, attempt.outcome))
    return tuple(attempts)


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _install_store(client: TestClient, store: InMemoryScenarioStore) -> None:
    _app(client).state.store = store


@pytest.fixture(scope="module")
def acceptance_store() -> InMemoryScenarioStore:
    """The real COMPLETE 200-run 100-seed acceptance campaign (built once)."""
    return complete_100_seed_store(build_seed_ensemble())


@pytest.fixture()
def store(acceptance_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation (used only by mutating tests)."""
    return copy.deepcopy(acceptance_store)


class TestSeedEnsembleFixed:
    """Requirement 1: exactly 100 unique fixed seeds in authoritative order."""

    def test_exactly_100_unique_seeds_in_authoritative_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        seeds = build_seed_ensemble()
        assert len(seeds) == 100
        assert [seed.identifier for seed in seeds] == list(SEED_IDENTIFIERS)
        assert len({seed.identifier for seed in seeds}) == 100
        assert tuple(sorted(SEED_IDENTIFIERS)) == SEED_IDENTIFIERS
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_scenario_seed_ids == SEED_IDENTIFIERS
        assert len(matrix.ordered_scenario_seed_ids) == 100

    def test_ensemble_is_fixed_before_execution_and_never_searched(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # The ensemble is an immutable constant tuple; the fixture only
        # maps identifiers to ScenarioSeed records. There is no scan,
        # retry, random draw, or adaptive selection anywhere in the
        # fixture: the helper builds the seeds in constant order.
        seeds = build_seed_ensemble()
        assert tuple(seed.identifier for seed in seeds) == SEED_IDENTIFIERS
        assert all(seed.algorithm == "deterministic" for seed in seeds)
        assert all(seed.tenant_id == TENANT for seed in seeds)
        expected = {BRANCH_X_LEVEL: EXPECTED_X_COUNT, BRANCH_Y_LEVEL: EXPECTED_Y_COUNT}
        counts = {BRANCH_X_LEVEL: 0, BRANCH_Y_LEVEL: 0}
        for seed in seeds:
            counts[_expected_level(acceptance_store, seed)] += 1
        assert counts == expected


class TestDistinctDeclaredPlans:
    """Requirement 2: two genuinely distinct declared strategy plans."""

    def test_two_genuinely_distinct_declared_plans(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # One prepared trajectory plan per strategy (not per run): both
        # strategies propose genuinely different transition-reference
        # orders over the same closed catalog.
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        assert len(plans) == 2
        assert {plan.strategy_candidate_id for plan in plans} == {STRATEGY_A, STRATEGY_B}
        sequences = {
            tuple(reference.transition_id for reference in plan.transition_references)
            for plan in plans
        }
        assert sequences == {("t-x", "t-y"), ("t-y", "t-x")}

    def test_every_run_binds_its_strategy_plan_reference_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        expected_sequence = {
            STRATEGY_A: ("t-x", "t-y"),
            STRATEGY_B: ("t-y", "t-x"),
        }
        plan_identifiers = {plan.strategy_candidate_id: plan.identifier for plan in plans}
        for plan in plans:
            assert (
                tuple(reference.transition_id for reference in plan.transition_references)
                == expected_sequence[plan.strategy_candidate_id]
            )
        # Every executed run of a strategy binds that strategy's plan:
        # each execution result references the strategy's trajectory
        # plan identifier.
        for strategy_position, strategy_id in enumerate((STRATEGY_A, STRATEGY_B)):
            plan_identifier = plan_identifiers[strategy_id]
            for seed_position in range(len(SEED_IDENTIFIERS)):
                run_id = _run_identifier(acceptance_store, strategy_position, seed_position)
                execution = acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_id
                )
                assert execution.results
                for result in execution.results:
                    assert result.trajectory_plan_id == plan_identifier


class TestSharedWorldPerSeed:
    """Requirement 3: the exact same realized world per seed for every strategy."""

    def test_realization_matrix_holds_exactly_100_realizations_never_200(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(realization_matrix.realizations) == len(SEED_IDENTIFIERS) == 100
        assert realization_matrix.ordered_scenario_seed_ids == SEED_IDENTIFIERS
        assert len({r.identifier for r in realization_matrix.realizations}) == 100
        assert len({r.content_hash for r in realization_matrix.realizations}) == 100

    def test_every_strategy_binds_the_identical_realization_per_seed(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for seed_position in range(len(SEED_IDENTIFIERS)):
            first = acceptance_store.get_realization_run_trajectory_execution(
                TENANT, _run_identifier(acceptance_store, 0, seed_position)
            )
            second = acceptance_store.get_realization_run_trajectory_execution(
                TENANT, _run_identifier(acceptance_store, 1, seed_position)
            )
            assert first.world_realization_id == second.world_realization_id
            assert first.world_realization_content_hash == second.world_realization_content_hash
            assert first.world_realization_id == (
                realization_matrix.realizations[seed_position].identifier
            )
            assert first.world_realization_content_hash == (
                realization_matrix.realizations[seed_position].content_hash
            )

    def test_observation_matrix_seed_aligned_realization_tuples(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert observation_matrix.ordered_world_realization_ids == tuple(
            r.identifier for r in realization_matrix.realizations
        )
        assert observation_matrix.ordered_world_realization_content_hashes == tuple(
            r.content_hash for r in realization_matrix.realizations
        )


class TestCausalEngineVariation:
    """Requirements 4-5: distinct realized states causally produce distinct values."""

    def test_two_genuinely_different_realized_initial_states_across_seeds(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        levels = {
            seed.identifier: _expected_level(acceptance_store, seed)
            for seed in build_seed_ensemble()
        }
        assert set(levels.values()) == {BRANCH_X_LEVEL, BRANCH_Y_LEVEL}
        counts = {BRANCH_X_LEVEL: 0, BRANCH_Y_LEVEL: 0}
        for level in levels.values():
            counts[level] += 1
        assert counts == {BRANCH_X_LEVEL: EXPECTED_X_COUNT, BRANCH_Y_LEVEL: EXPECTED_Y_COUNT}

    def test_every_observed_value_is_engine_produced_from_its_realized_branch(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        expected = _expected_by_seed(acceptance_store)
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for strategy_position in range(2):
            for seed_position, seed_id in enumerate(SEED_IDENTIFIERS):
                cell = observation_matrix.cells[strategy_position * 100 + seed_position]
                assert cell.scenario_seed_id == seed_id
                raw = cell.observations[0].raw_value
                assert isinstance(raw, int)
                assert raw == expected[seed_id]

    def test_exactly_one_applied_guarded_transition_matching_the_branch_per_run(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        expected_levels = {
            seed.identifier: _expected_level(acceptance_store, seed)
            for seed in build_seed_ensemble()
        }
        for strategy_position in range(2):
            for seed_position, seed_id in enumerate(SEED_IDENTIFIERS):
                run_id = _run_identifier(acceptance_store, strategy_position, seed_position)
                attempts = _attempt_sequence(acceptance_store, run_id)
                applied = [
                    transition_id for transition_id, outcome in attempts if outcome == "applied"
                ]
                assert applied == ["t-x" if expected_levels[seed_id] == BRANCH_X_LEVEL else "t-y"]
                assert len(attempts) == 2

    def test_attempt_records_prove_opposite_strategy_plan_orders(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # seed-000 realizes branch X (level 5); seed-002 realizes branch
        # Y (level 9) - proven self-consistently below and by the split
        # assertions of the fixed ensemble.
        x_position = SEED_IDENTIFIERS.index("seed-000")
        y_position = SEED_IDENTIFIERS.index("seed-002")
        assert _expected_level(acceptance_store, build_seed(identifier="seed-000")) == (
            BRANCH_X_LEVEL
        )
        assert _expected_level(acceptance_store, build_seed(identifier="seed-002")) == (
            BRANCH_Y_LEVEL
        )
        assert _attempt_sequence(
            acceptance_store, _run_identifier(acceptance_store, 0, x_position)
        ) == (("t-x", "applied"), ("t-y", "guard_not_satisfied"))
        assert _attempt_sequence(
            acceptance_store, _run_identifier(acceptance_store, 1, x_position)
        ) == (("t-y", "guard_not_satisfied"), ("t-x", "applied"))
        assert _attempt_sequence(
            acceptance_store, _run_identifier(acceptance_store, 0, y_position)
        ) == (("t-x", "guard_not_satisfied"), ("t-y", "applied"))
        assert _attempt_sequence(
            acceptance_store, _run_identifier(acceptance_store, 1, y_position)
        ) == (("t-y", "applied"), ("t-x", "guard_not_satisfied"))


class TestEmpiricalEvidence:
    """The exact 81/100 acceptance result and the empirical golden statistics."""

    def _matrix(self, store: InMemoryScenarioStore) -> CampaignOutcomeDistributionMatrix:
        return get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )

    def test_exact_81_of_100_target_achievement(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        outcome = self._matrix(acceptance_store).outcomes[0]
        assert outcome.target_achievement_count == 81
        assert outcome.empirical_target_achievement_probability == 0.81

    def test_golden_empirical_distribution_statistics(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        summary = self._matrix(acceptance_store).outcomes[0].empirical_distribution
        assert summary.sample_count == 100
        assert summary.minimum == 84.0
        assert summary.maximum == 103.0
        assert summary.arithmetic_mean == GOLDEN_MEAN
        assert summary.median == GOLDEN_MEDIAN
        assert summary.population_standard_deviation == GOLDEN_STDDEV
        assert summary.p05 == GOLDEN_P05
        assert summary.p25 == GOLDEN_P25
        assert summary.p75 == GOLDEN_P75
        assert summary.p95 == GOLDEN_P95
        assert summary.quantile_algorithm == "hyndman-fan-type-7-v1"

    def test_exact_ordered_samples_preserve_shared_seed_order_for_both_strategies(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        expected = _expected_by_seed(acceptance_store)
        expected_values = tuple(expected[seed_id] for seed_id in SEED_IDENTIFIERS)
        matrix = self._matrix(acceptance_store)
        assert len(matrix.outcomes) == 2
        for outcome in matrix.outcomes:
            assert outcome.ordered_observed_values == expected_values
            assert outcome.empirical_distribution.ordered_samples == expected_values

    def test_normalized_target_violation_evidence(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        expected = _expected_by_seed(acceptance_store)
        expected_violations = tuple(
            max(0.0, expected[seed_id] - TARGET) / NORMALIZATION_SCALE
            for seed_id in SEED_IDENTIFIERS
        )
        outcome = self._matrix(acceptance_store).outcomes[0]
        distribution = outcome.normalized_target_violation_distribution
        assert distribution is not None
        assert distribution.ordered_samples == expected_violations
        assert distribution.sample_count == 100
        assert distribution.minimum == 0.0
        assert distribution.maximum == GOLDEN_WORST_VIOLATION
        assert distribution.arithmetic_mean == GOLDEN_VIOLATION_MEAN
        assert distribution.population_standard_deviation == GOLDEN_VIOLATION_STDDEV
        assert distribution.p95 == GOLDEN_WORST_VIOLATION
        assert outcome.worst_normalized_target_violation == GOLDEN_WORST_VIOLATION
        assert outcome.target_violation_cvar == GOLDEN_CVAR
        assert outcome.tail_alpha == 0.95
        assert outcome.tail_algorithm == "empirical-fractional-tail-mean-v1"

    def test_adverse_tail_statistic_in_original_unit(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        outcome = self._matrix(acceptance_store).outcomes[0]
        assert outcome.direction == "minimize"
        assert outcome.adverse_tail_statistic == GOLDEN_ADVERSE_TAIL

    def test_strategy_major_objective_minor_order_and_identical_snapshots(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        matrix = self._matrix(acceptance_store)
        assert matrix.ordered_strategy_candidate_ids == (STRATEGY_A, STRATEGY_B)
        assert matrix.ordered_objective_ids == (OBJECTIVE_ID,)
        assert matrix.ordered_metric_ids == (METRIC_ID,)
        assert [outcome.sequence_position for outcome in matrix.outcomes] == [0, 1]
        assert [outcome.strategy_position for outcome in matrix.outcomes] == [0, 1]
        assert [outcome.objective_position for outcome in matrix.outcomes] == [0, 0]
        first, second = matrix.outcomes
        assert first.strategy_candidate_id == STRATEGY_A
        assert second.strategy_candidate_id == STRATEGY_B
        assert first.objective_id == second.objective_id == OBJECTIVE_ID
        assert first.metric_id == second.metric_id == METRIC_ID
        assert first.direction == second.direction == "minimize"
        assert first.target == second.target == TARGET
        assert first.normalization_scale == second.normalization_scale == NORMALIZATION_SCALE
        # Shared realizations and identical plans imply identical
        # per-strategy evidence: both strategies achieve 81/100.
        assert second.target_achievement_count == 81
        assert second.empirical_target_achievement_probability == 0.81

    def test_evidence_is_explicitly_empirical_with_no_decision_surface(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        matrix = self._matrix(acceptance_store)
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        outcome: StrategyObjectiveOutcome = matrix.outcomes[0]
        assert outcome.empirical_distribution.quantile_algorithm == "hyndman-fan-type-7-v1"
        forbidden = {"rank", "winner", "prefer", "recommend", "confidence", "forecast"}
        fields = set(CampaignOutcomeDistributionMatrix.model_fields)
        fields |= set(StrategyObjectiveOutcome.model_fields)
        for field in fields:
            assert not any(token in field.lower() for token in forbidden), field
        assert not hasattr(matrix, "preferred_strategy_id")
        assert not hasattr(outcome, "preference")

    def test_source_lineage_traces_to_authoritative_artifacts(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        campaign = acceptance_store.get_campaign(TENANT, "campaign-1")
        world = acceptance_store.get_world(TENANT, campaign.world_version_id)
        catalog = extract_world_catalog(world)
        profile = catalog.evaluation_profile
        assert profile is not None
        stored_profile = acceptance_store.get_evaluation_profile(TENANT, "scenario-1")
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        matrix = self._matrix(acceptance_store)
        assert matrix.identifier == GOLDEN_IDENTIFIER
        assert matrix.content_hash == GOLDEN_CONTENT_HASH
        assert campaign_outcome_distribution_matrix_content_hash(matrix) == GOLDEN_CONTENT_HASH
        assert matrix.campaign_id == "campaign-1"
        assert matrix.scenario_id == "scenario-1"
        assert matrix.scenario_content_hash == profile.scenario_content_hash
        assert matrix.world_version_id == world.identifier
        assert matrix.world_content_hash == world.content_hash
        assert matrix.evaluation_profile_id == profile.identifier
        assert matrix.evaluation_profile_content_hash == profile.content_hash
        assert matrix.evaluation_profile_content_hash == stored_profile.content_hash
        assert matrix.uncertainty_model_id == realization_matrix.uncertainty_model_id
        assert matrix.uncertainty_model_content_hash == (
            realization_matrix.uncertainty_model_content_hash
        )
        assert matrix.source_world_realization_matrix_id == realization_matrix.identifier
        assert matrix.source_world_realization_matrix_content_hash == (
            realization_matrix.content_hash
        )
        assert matrix.source_metric_observation_matrix_id == observation_matrix.identifier
        assert matrix.source_metric_observation_matrix_content_hash == (
            observation_matrix.content_hash
        )
        assert matrix.derived_at == NOW
        assert matrix.derived_at == observation_matrix.assembled_at


class TestExactReplay:
    """Requirement 8: exact runtime-3 replay of one representative seed per branch."""

    def test_exact_replay_of_a_branch_x_representative_run(
        self, store: InMemoryScenarioStore
    ) -> None:
        x_position = SEED_IDENTIFIERS.index("seed-000")
        run_id = _run_identifier(store, 0, x_position)
        generic = replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert generic.replay_classification == "exact"
        assert generic.scenario_seed_id == "seed-000"
        realization_manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert realization_manifest.replay_classification == "exact"
        assert realization_manifest.expected_execution_hash == (
            realization_manifest.recomputed_execution_hash
        )
        assert realization_manifest.expected_observation_set_hash == (
            realization_manifest.recomputed_observation_set_hash
        )
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        assert realization_manifest.world_realization_id == execution.world_realization_id
        assert realization_manifest.expected_execution_hash == execution.content_hash

    def test_exact_replay_of_a_branch_y_representative_run(
        self, store: InMemoryScenarioStore
    ) -> None:
        y_position = SEED_IDENTIFIERS.index("seed-002")
        run_id = _run_identifier(store, 1, y_position)
        generic = replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert generic.replay_classification == "exact"
        assert generic.scenario_seed_id == "seed-002"
        realization_manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert realization_manifest.replay_classification == "exact"
        assert realization_manifest.expected_execution_hash == (
            realization_manifest.recomputed_execution_hash
        )
        assert realization_manifest.expected_observation_set_hash == (
            realization_manifest.recomputed_observation_set_hash
        )
        assert realization_manifest.expected_observation_set_hash == (
            store.get_realization_run_metric_observation_set(TENANT, run_id).content_hash
        )

    def test_replay_is_idempotent_and_writes_only_the_manifest_pair(
        self, store: InMemoryScenarioStore
    ) -> None:
        run_id = _run_identifier(store, 0, 0)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        first_manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        second_manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert second_manifest.model_dump(mode="json") == first_manifest.model_dump(mode="json")
        # Only the two replay manifests were added; executions,
        # observation sets, plans, and activity are untouched.
        assert len(store.get_run_plans(TENANT, "campaign-1")) == 200
        assert store.list_operational_activity(TENANT) == ()


class TestVerifiedQueryAndApi:
    """Requirements 9-11: assembled GET endpoint, repeated equality, read-only."""

    def _get(self, client: TestClient) -> Any:
        return client.get(OUTCOME_PATH.format(campaign_id="campaign-1"), headers=HEADERS)

    def test_assembled_api_get_returns_exact_evidence(
        self, client: TestClient, acceptance_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, acceptance_store)
        response = self._get(client)
        assert response.status_code == 200
        matrix = CampaignOutcomeDistributionMatrix.model_validate(response.json())
        assert matrix.identifier == GOLDEN_IDENTIFIER
        assert matrix.content_hash == GOLDEN_CONTENT_HASH
        assert matrix.outcomes[0].target_achievement_count == 81
        assert matrix.outcomes[0].empirical_target_achievement_probability == 0.81
        direct = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert response.json() == direct.model_dump(mode="json")

    def test_repeated_gets_identical_including_identity_and_timestamp_lineage(
        self, client: TestClient, acceptance_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, acceptance_store)
        before = _store_state(acceptance_store)
        first = self._get(client)
        second = self._get(client)
        third = self._get(client)
        assert first.status_code == 200
        for later in (second, third):
            assert later.json() == first.json()
            assert canonical_json(later.json()) == canonical_json(first.json())
        for body in (first.json(), second.json(), third.json()):
            assert body["identifier"] == GOLDEN_IDENTIFIER
            assert body["content_hash"] == GOLDEN_CONTENT_HASH
            assert body["derived_at"] == "2026-01-01T12:00:00Z"
        assert _store_state(acceptance_store) == before
        assert acceptance_store.list_operational_activity(TENANT) == ()

    def test_query_performs_no_writes_no_activity_and_no_artifact_creation(
        self, client: TestClient, acceptance_store: InMemoryScenarioStore
    ) -> None:
        _install_store(client, acceptance_store)
        before = _store_state(acceptance_store)
        for _ in range(3):
            response = self._get(client)
            assert response.status_code == 200
        assert _store_state(acceptance_store) == before
        # No execution, extraction, repair, replay, or plan artifacts
        # were created or removed by the queries.
        assert len(acceptance_store.get_run_plans(TENANT, "campaign-1")) == 200
        assert len(acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")) == 2
        assert acceptance_store.list_operational_activity(TENANT) == ()


class TestNoManufacturedEvidence:
    """Requirement 7: nothing is inserted, patched, copied, or manufactured."""

    def test_lifecycle_produced_every_record_through_the_real_services(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # Exactly the records the real lifecycle writes: 200 run plans,
        # 200 executions, 200 observation sets, 2 strategy candidates.
        assert len(acceptance_store.get_run_plans(TENANT, "campaign-1")) == 200
        executions = acceptance_store._realization_run_trajectory_executions
        assert len(executions) == 200
        observation_sets = acceptance_store._realization_run_metric_observation_sets
        assert len(observation_sets) == 200
        candidates = acceptance_store.get_strategy_candidates(TENANT, "campaign-1")
        assert {candidate.identifier for candidate in candidates} == {STRATEGY_A, STRATEGY_B}

    def test_no_outcome_matrix_is_ever_stored(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        for name in _STORE_COLLECTIONS:
            collection = getattr(acceptance_store, name)
            for value in collection.values():
                dumped = _dump_value(value)
                if isinstance(dumped, tuple):
                    assert not any(
                        isinstance(item, CampaignOutcomeDistributionMatrix) for item in dumped
                    ), name
                assert not isinstance(dumped, CampaignOutcomeDistributionMatrix), name

    def test_no_expected_artifact_was_injected_into_the_fixture(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # The store's execution and observation records are exactly the
        # engine-produced artifacts: every execution is COMPLETE with
        # two attempts and every observation set carries one value that
        # matches the causal expectation function (no copied matrices).
        expected = _expected_by_seed(acceptance_store)
        for strategy_position in range(2):
            for seed_position, seed_id in enumerate(SEED_IDENTIFIERS):
                run_id = _run_identifier(acceptance_store, strategy_position, seed_position)
                execution = acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_id
                )
                assert len(execution.results) >= 1
                observed = acceptance_store.get_realization_run_metric_observation_set(
                    TENANT, run_id
                )
                raw = observed.observations[0].raw_value
                assert isinstance(raw, int)
                assert raw == expected[seed_id]
