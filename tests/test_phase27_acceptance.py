"""Phase 27 final acceptance part A: frozen 100-seed causal decision proof.

One deterministic, domain-neutral, end-to-end runtime-3.0.0 campaign over
exactly 100 fixed shared seeds (``seed-000`` through ``seed-099``, the
first 100 identifiers in ascending order - never searched), built
exclusively through the real public services: declarations (state model
``sm-1`` with integer level/reserve, seven guarded causal transitions,
two metric-observation bindings, the discrete uncertainty model over
both fields, and the two-objective evaluation profile declared before
world compilation), world compilation, runtime-3 preparation with the
sanctioned three-candidate LEGION adapter, trajectory planning, start,
300 real executions, and 300 explicit observation extractions. The real
decision policy is declared through the real policy service and the
comparison/brief are obtained only through the real verified query
services. No observed value, realization, matrix, hash, outcome, policy,
comparison, brief, or expected artifact is ever patched, injected, or
manufactured; every decision golden below is a frozen constant derived
once at authoring time from the real final fixture.

Proves:

- exactly 100 unique fixed seeds in authoritative ascending order, the
  exact realized world-type split (22/24/27/27), three genuinely
  distinct declared plans, and every run bound to its strategy plan;
- exactly 100 shared realizations (never 300) with identical per-seed
  realization identity/hash across all three strategies; exactly 300
  plans/executions/observation sets; every observed value of all 300
  runs equals the independent causal expectation reconstructed from the
  realized world type and the declared transition semantics; every
  attempt sequence matches the declared plan;
- the frozen observed-value distributions, ordinary means, and
  target-achievement probabilities (mock-a (1.0, 0.46), mock-b (0.46,
  1.0), mock-c (0.46, 0.51)) with all three strategies feasible at the
  0.40 hard gates;
- the complete ordered paired matrix through
  ``get_verified_campaign_strategy_comparison``: both directions of
  every pair, exact win/tie/loss counts, mock-b dominates mock-c and no
  other dominance, shared-seed alignment, non-dominated feasible order
  (mock-a, mock-b);
- the frozen per-world-type total weighted regrets and aggregates,
  minimax best 2.24 with the unique tie set {mock-b} under tolerance
  0.05 (mock-a and mock-c excluded, no lexicographic fallback);
- the preferred brief through ``get_verified_campaign_decision_brief``:
  status preferred, preferred mock-b, terminal reason
  ``unique_minimax_preference`` (2.24, 0.05), nearest competitor mock-a
  with the one-ULP gap, the exact decisive/blocking factor trails, and
  the exact gate-aware summary;
- hard-coded (never recomputed) policy/comparison/brief identifiers and
  content hashes and the complete cross-artifact lineage;
- read-only determinism: repeated comparison/brief queries are
  byte-identical, the complete store digest is unchanged, zero activity
  events, no execution/replay/extraction triggered, comparison and brief
  are never stored, and no wall-clock dependency exists;
- best ordinary mean is not the robust winner: mock-a's 32.46 primary
  mean is best but its maximum total weighted regret is the worst (4.0)
  because its reserve collapses to 5 in all 54 level-9 worlds, while
  mock-b (94.26 mean, 2.24 max regret) is the robust preferred strategy;
- the Phase 26 two-strategy tie/inconclusive control proof through its
  own helper: identical per-seed outcomes, zero paired deltas, no
  dominance, identical regret, the minimax tie set containing both
  strategies, status inconclusive, preferred None, and no identifier-
  order winner.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

import pytest
from kalhas.application.campaign_decision_query_service import (
    get_verified_campaign_decision_brief,
    get_verified_campaign_strategy_comparison,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignStrategyComparison,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix
from kalhas.contracts.v1.run_plan import RunPlan

from tests.phase4_helpers import NOW, TENANT, build_request
from tests.phase20_helpers import DECLARED_AT
from tests.phase26_helpers import build_seed_ensemble as phase26_build_seed_ensemble
from tests.phase26_helpers import (
    complete_100_seed_store as phase26_complete_100_seed_store,
)
from tests.phase27_helpers import (
    BEST_MAXIMUM_TOTAL_REGRET,
    EXPECTED_BLOCKING_FACTORS,
    EXPECTED_DECISIVE_FACTORS,
    EXPECTED_DISTRIBUTIONS,
    EXPECTED_MEANS,
    EXPECTED_PAIR_COUNTS,
    EXPECTED_REGRET_AGGREGATES,
    EXPECTED_TARGET_PROBABILITIES,
    EXPECTED_WORLD_TYPE_COUNTS,
    EXPECTED_WORLD_TYPE_TOTAL_REGRET,
    GOLDEN_BRIEF_CONTENT_HASH,
    GOLDEN_BRIEF_ID,
    GOLDEN_BRIEF_SUMMARY,
    GOLDEN_COMPARISON_CONTENT_HASH,
    GOLDEN_COMPARISON_ID,
    GOLDEN_CONTROL_BRIEF_CONTENT_HASH,
    GOLDEN_CONTROL_BRIEF_ID,
    GOLDEN_CONTROL_BRIEF_SUMMARY,
    GOLDEN_CONTROL_COMPARISON_CONTENT_HASH,
    GOLDEN_CONTROL_COMPARISON_ID,
    GOLDEN_CONTROL_POLICY_CONTENT_HASH,
    GOLDEN_CONTROL_POLICY_ID,
    GOLDEN_POLICY_CONTENT_HASH,
    GOLDEN_POLICY_ID,
    MINIMAX_TIE_SET,
    MINIMUM_SAMPLE_COUNT,
    NEAREST_COMPETITOR,
    OBJECTIVE_IDS,
    REGRET_GAP,
    SEED_IDENTIFIERS,
    STORE_COLLECTIONS,
    STRATEGIES,
    STRATEGY_PLANS,
    THRESHOLDS,
    TIE_TOLERANCE,
    build_seed_ensemble,
    complete_100_seed_store,
    declare_acceptance_policy,
    declare_control_policy,
    expected_attempt_sequence,
    expected_observed,
    is_within_one_ulp,
    phase27_legion,
    realized_world_type,
    store_state,
)

CONTROL_STRATEGIES = ("mock-a", "mock-b")

#: The frozen per-order dominance statuses of the acceptance campaign.
EXPECTED_DOMINANCE_STATUSES: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("mock-a", "mock-b"): (("obj-1", "better"), ("obj-2", "worse")),
    ("mock-a", "mock-c"): (("obj-1", "better"), ("obj-2", "worse")),
    ("mock-b", "mock-a"): (("obj-1", "worse"), ("obj-2", "worse")),
    ("mock-b", "mock-c"): (("obj-1", "tied"), ("obj-2", "better")),
    ("mock-c", "mock-a"): (("obj-1", "worse"), ("obj-2", "worse")),
    ("mock-c", "mock-b"): (("obj-1", "tied"), ("obj-2", "worse")),
}

#: The only frozen dominance relation of the acceptance campaign.
EXPECTED_DOMINATING_PAIRS: set[tuple[str, str]] = {("mock-b", "mock-c")}

#: The world types in which mock-b wins obj-2 against mock-c (frozen
#: causal cross-check of the 49 wins).
MOCK_B_WINS_OBJ2_WORLD_TYPES: frozenset[tuple[int, int]] = frozenset({(5, 20), (9, 20)})

#: The frozen tie-control decisive factor trail.
EXPECTED_CONTROL_DECISIVE_FACTORS: tuple[
    tuple[str, str | None, str | None, tuple[float, ...], tuple[str, ...]], ...
] = (
    ("feasible_candidate", "mock-a", None, (), ()),
    ("feasible_candidate", "mock-b", None, (), ()),
    ("target_feasibility_passed", "mock-a", "obj-1", (0.4, 0.81), ()),
    ("target_feasibility_passed", "mock-b", "obj-1", (0.4, 0.81), ()),
    ("pareto_non_dominated", "mock-a", None, (), ()),
    ("pareto_non_dominated", "mock-b", None, (), ()),
)

#: The frozen tie-control blocking factor trail.
EXPECTED_CONTROL_BLOCKING_FACTORS: tuple[
    tuple[str, str | None, str | None, tuple[float, ...], tuple[str, ...]], ...
] = (("minimax_regret_tie", None, None, (0.0, 0.05), ("mock-a", "mock-b")),)


def _factor_tuple(
    factor: Any,
) -> tuple[str, str | None, str | None, tuple[Any, ...], tuple[Any, ...]]:
    """One frozen factor-trail tuple of one decision factor record."""
    return (
        factor.code,
        factor.strategy_id,
        factor.objective_id,
        tuple(factor.values),
        tuple(factor.related_strategy_ids),
    )


def _observed_by_metric(store: InMemoryScenarioStore, run_id: str) -> dict[str, int]:
    """The extracted raw observations of one run keyed by metric id."""
    observation_set = store.get_realization_run_metric_observation_set(TENANT, run_id)
    by_metric: dict[str, int] = {}
    for observation in observation_set.observations:
        value = observation.raw_value
        assert isinstance(value, int)
        by_metric[observation.metric_id] = value
    return by_metric


def _attempt_sequence(store: InMemoryScenarioStore, run_id: str) -> tuple[tuple[str, str], ...]:
    """The flattened (transition_id, outcome) attempt tuple of one run."""
    execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
    attempts: list[tuple[str, str]] = []
    for result in execution.results:
        for attempt in result.attempts:
            attempts.append((attempt.transition_id, attempt.outcome))
    return tuple(attempts)


def _run_plan_by_key(store: InMemoryScenarioStore) -> dict[tuple[str, str], RunPlan]:
    """The (strategy, seed) -> run plan lookup of the acceptance campaign."""
    return {
        (plan.strategy_candidate_id, plan.scenario_seed_id): plan
        for plan in store.get_run_plans(TENANT, "campaign-1")
    }


def _outcome_by_strategy_objective(
    matrix: CampaignOutcomeDistributionMatrix,
) -> dict[tuple[str, str], Any]:
    """The strategy-major/objective-minor outcome lookup of the matrix."""
    return {
        (outcome.strategy_candidate_id, outcome.objective_id): outcome
        for outcome in matrix.outcomes
    }


def _profile_by_strategy(comparison: CampaignStrategyComparison) -> dict[str, Any]:
    """The robustness profile lookup of the comparison by strategy id."""
    return {profile.strategy_candidate_id: profile for profile in comparison.robustness_profiles}


def _stored_artifact_scan(store: InMemoryScenarioStore) -> list[str]:
    """The collections holding any derived artifact instance (raw scan)."""
    derived_types = (
        CampaignStrategyComparison,
        CampaignDecisionBrief,
        CampaignOutcomeDistributionMatrix,
    )
    found: list[str] = []
    for name in STORE_COLLECTIONS:
        collection = getattr(store, name)
        for value in collection.values():
            items = value if isinstance(value, tuple) else (value,)
            if any(isinstance(item, derived_types) for item in items):
                found.append(name)
    return found


@pytest.fixture(scope="module")
def acceptance_store() -> InMemoryScenarioStore:
    """The real COMPLETE 300-run 100-seed acceptance campaign with policy declared."""
    store = complete_100_seed_store(build_seed_ensemble())
    declare_acceptance_policy(store)
    return store


@pytest.fixture(scope="module")
def world_types(acceptance_store: InMemoryScenarioStore) -> dict[str, tuple[int, int]]:
    """The realized ``(level, reserve)`` world type of every fixed seed."""
    return {
        seed.identifier: realized_world_type(acceptance_store, seed)
        for seed in build_seed_ensemble()
    }


@pytest.fixture(scope="module")
def control_store() -> InMemoryScenarioStore:
    """The real Phase 26 200-run tie-control campaign with its policy declared."""
    store = phase26_complete_100_seed_store(phase26_build_seed_ensemble())
    declare_control_policy(store)
    return store


class TestFixedSeedEnsemble:
    """Requirement 1: exactly 100 fixed seeds, ascending, never searched."""

    def test_exactly_100_unique_fixed_seeds_in_ascending_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        seeds = build_seed_ensemble()
        assert len(seeds) == 100
        assert [seed.identifier for seed in seeds] == list(SEED_IDENTIFIERS)
        assert len({seed.identifier for seed in seeds}) == 100
        assert tuple(sorted(SEED_IDENTIFIERS)) == SEED_IDENTIFIERS
        assert SEED_IDENTIFIERS[0] == "seed-000"
        assert SEED_IDENTIFIERS[-1] == "seed-099"
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_scenario_seed_ids == SEED_IDENTIFIERS

    def test_ensemble_is_fixed_before_execution_and_never_searched(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        # The ensemble is the immutable constant tuple of the first 100
        # identifiers; the fixture only maps identifiers to records.
        # There is no scan, retry, re-roll, filter, or adaptive
        # selection anywhere in the fixture.
        seeds = build_seed_ensemble()
        assert tuple(seed.identifier for seed in seeds) == SEED_IDENTIFIERS
        assert all(seed.algorithm == "deterministic" for seed in seeds)
        assert all(seed.tenant_id == TENANT for seed in seeds)
        counts: dict[tuple[int, int], int] = {}
        for seed in seeds:
            world_type = world_types[seed.identifier]
            counts[world_type] = counts.get(world_type, 0) + 1
        assert counts == EXPECTED_WORLD_TYPE_COUNTS


class TestDistinctDeclaredPlans:
    """Requirement 2: three genuinely distinct declared strategy plans."""

    def test_three_genuinely_distinct_declared_plans(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        assert len(plans) == 3
        assert {plan.strategy_candidate_id for plan in plans} == set(STRATEGIES)
        sequences = {
            tuple(reference.transition_id for reference in plan.transition_references)
            for plan in plans
        }
        assert sequences == {
            ("t-z", "t-z2", "t-v", "t-u"),
            ("t-x", "t-w", "t-y", "t-u"),
            ("t-x", "t-u", "t-y"),
        }

    def test_every_run_binds_its_strategy_plan_reference_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        plan_identifiers = {plan.strategy_candidate_id: plan.identifier for plan in plans}
        for plan in plans:
            assert (
                tuple(reference.transition_id for reference in plan.transition_references)
                == STRATEGY_PLANS[plan.strategy_candidate_id]
            )
        plans_by_key = _run_plan_by_key(acceptance_store)
        for strategy_id in STRATEGIES:
            for seed_id in SEED_IDENTIFIERS:
                run_id = run_identifier(plans_by_key[(strategy_id, seed_id)])
                execution = acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_id
                )
                assert execution.results
                for result in execution.results:
                    assert result.trajectory_plan_id == plan_identifiers[strategy_id]


class TestSharedWorldPerSeed:
    """Requirement 3: the exact same realized world per seed for every strategy."""

    def test_realization_matrix_holds_exactly_100_realizations_never_300(
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
        plans_by_key = _run_plan_by_key(acceptance_store)
        for seed_position, seed_id in enumerate(SEED_IDENTIFIERS):
            executions = [
                acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_identifier(plans_by_key[(strategy_id, seed_id)])
                )
                for strategy_id in STRATEGIES
            ]
            identifiers = {execution.world_realization_id for execution in executions}
            hashes = {execution.world_realization_content_hash for execution in executions}
            assert len(identifiers) == 1
            assert len(hashes) == 1
            assert identifiers == {realization_matrix.realizations[seed_position].identifier}
            assert hashes == {realization_matrix.realizations[seed_position].content_hash}

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


class TestCausalExecutionProofs:
    """Requirements 4-6: 300 real runs, causal values, plan-ordered attempts."""

    def test_exactly_300_plans_executions_and_observation_sets(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        assert len(acceptance_store.get_run_plans(TENANT, "campaign-1")) == 300
        assert len(acceptance_store._realization_run_trajectory_executions) == 300
        assert len(acceptance_store._realization_run_metric_observation_sets) == 300
        plans_by_key = _run_plan_by_key(acceptance_store)
        assert len(plans_by_key) == 300

    def test_all_300_observed_values_equal_the_causal_expectation(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        plans_by_key = _run_plan_by_key(acceptance_store)
        for strategy_id in STRATEGIES:
            for seed_id in SEED_IDENTIFIERS:
                run_id = run_identifier(plans_by_key[(strategy_id, seed_id)])
                observed = _observed_by_metric(acceptance_store, run_id)
                expected = expected_observed(strategy_id, world_types[seed_id])
                assert (observed["m-1"], observed["m-2"]) == expected, (strategy_id, seed_id)

    def test_attempt_order_matches_each_declared_strategy_plan(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        plans_by_key = _run_plan_by_key(acceptance_store)
        for strategy_id in STRATEGIES:
            for seed_id in SEED_IDENTIFIERS:
                run_id = run_identifier(plans_by_key[(strategy_id, seed_id)])
                attempts = _attempt_sequence(acceptance_store, run_id)
                expected = expected_attempt_sequence(
                    STRATEGY_PLANS[strategy_id], world_types[seed_id]
                )
                assert attempts == expected, (strategy_id, seed_id)
                applied = [t for t, outcome in attempts if outcome == "applied"]
                assert applied, (strategy_id, seed_id)


class TestFrozenDistributions:
    """Requirement 7: exact distributions, means, and target probabilities."""

    def test_exact_observed_value_distributions(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcomes = _outcome_by_strategy_objective(matrix)
        for strategy_id in STRATEGIES:
            for objective_id in OBJECTIVE_IDS:
                outcome = outcomes[(strategy_id, objective_id)]
                assert len(outcome.ordered_observed_values) == 100
                distribution = Counter(float(value) for value in outcome.ordered_observed_values)
                assert dict(distribution) == EXPECTED_DISTRIBUTIONS[strategy_id][objective_id]

    def test_ordinary_arithmetic_means(self, acceptance_store: InMemoryScenarioStore) -> None:
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcomes = _outcome_by_strategy_objective(matrix)
        for strategy_id in STRATEGIES:
            means = tuple(
                math.fsum(outcomes[(strategy_id, objective_id)].ordered_observed_values) / 100
                for objective_id in OBJECTIVE_IDS
            )
            assert means == EXPECTED_MEANS[strategy_id], strategy_id

    def test_exact_target_achievement_probabilities(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcomes = _outcome_by_strategy_objective(matrix)
        for strategy_id in STRATEGIES:
            probabilities = tuple(
                outcomes[(strategy_id, objective_id)].empirical_target_achievement_probability
                for objective_id in OBJECTIVE_IDS
            )
            assert probabilities == EXPECTED_TARGET_PROBABILITIES[strategy_id], strategy_id

    def test_all_three_strategies_feasible_at_the_hard_gates(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        for strategy_id in STRATEGIES:
            profile = profiles[strategy_id]
            assert profile.feasible is True, strategy_id
            for record, objective_id in zip(profile.target_feasibility, OBJECTIVE_IDS, strict=True):
                assert record.objective_id == objective_id
                assert record.threshold == THRESHOLDS[objective_id]
                assert (
                    record.observed_probability
                    == EXPECTED_TARGET_PROBABILITIES[strategy_id][OBJECTIVE_IDS.index(objective_id)]
                )
                assert record.passed is True


class TestComparisonGoldens:
    """Requirement 8: the complete ordered paired matrix through the real query."""

    def test_complete_ordered_paired_matrix_both_directions(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert comparison.ordered_strategy_candidate_ids == STRATEGIES
        assert comparison.ordered_objective_ids == OBJECTIVE_IDS
        assert comparison.ordered_scenario_seed_ids == SEED_IDENTIFIERS
        assert comparison.tie_tolerance == TIE_TOLERANCE
        assert comparison.minimum_sample_count == MINIMUM_SAMPLE_COUNT
        assert len(comparison.paired_comparisons) == 12
        assert len(comparison.dominance_relations) == 6
        assert len(comparison.robustness_profiles) == 3
        keys = {
            (pair.first_strategy_candidate_id, pair.second_strategy_candidate_id, pair.objective_id)
            for pair in comparison.paired_comparisons
        }
        assert keys == set(EXPECTED_PAIR_COUNTS)
        for pair in comparison.paired_comparisons:
            assert len(pair.ordered_paired_deltas) == 100
            assert pair.metric_id == ("m-1" if pair.objective_id == "obj-1" else "m-2")

    def test_exact_paired_win_tie_loss_counts(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for pair in comparison.paired_comparisons:
            key = (
                pair.first_strategy_candidate_id,
                pair.second_strategy_candidate_id,
                pair.objective_id,
            )
            assert (pair.win_count, pair.tie_count, pair.loss_count) == EXPECTED_PAIR_COUNTS[key], (
                key
            )

    def test_shared_seed_alignment_of_paired_deltas(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        by_key = {
            (
                pair.first_strategy_candidate_id,
                pair.second_strategy_candidate_id,
                pair.objective_id,
            ): pair
            for pair in comparison.paired_comparisons
        }
        pair = by_key[("mock-b", "mock-c", "obj-2")]
        # Every seed where the causal expectations imply a mock-b win on
        # obj-2 is exactly a win position of the recorded delta vector:
        # both strategies realize identical values per seed, so the
        # deltas align 1:1 with the shared seed order.
        win_positions = [
            position
            for position, delta in enumerate(pair.ordered_paired_deltas)
            if delta < -TIE_TOLERANCE
        ]
        expected_win_positions = [
            position
            for position, seed_id in enumerate(SEED_IDENTIFIERS)
            if world_types[seed_id] in MOCK_B_WINS_OBJ2_WORLD_TYPES
        ]
        assert win_positions == expected_win_positions
        assert len(win_positions) == 49
        # mock-b and mock-c realize identical obj-1 values per seed: the
        # obj-1 delta vector is exactly all ties.
        tied_pair = by_key[("mock-b", "mock-c", "obj-1")]
        assert all(delta == 0.0 for delta in tied_pair.ordered_paired_deltas)

    def test_dominance_relations_only_mock_b_dominates_mock_c(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        dominating = set()
        for relation in comparison.dominance_relations:
            key = (
                relation.first_strategy_candidate_id,
                relation.second_strategy_candidate_id,
            )
            statuses = tuple(
                (status.objective_id, status.status) for status in relation.per_objective_status
            )
            assert statuses == EXPECTED_DOMINANCE_STATUSES[key], key
            if relation.dominates:
                dominating.add(key)
        assert dominating == EXPECTED_DOMINATING_PAIRS

    def test_non_dominated_feasible_order(self, acceptance_store: InMemoryScenarioStore) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        assert profiles["mock-a"].dominated_by == ()
        assert profiles["mock-b"].dominated_by == ()
        assert profiles["mock-c"].dominated_by == ("mock-b",)
        assert profiles["mock-a"].dominates == ()
        assert profiles["mock-b"].dominates == ("mock-c",)
        assert profiles["mock-c"].dominates == ()
        # The non-dominated feasible order comes from the decisive factor
        # trail of the real brief (authoritative strategy order).
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        non_dominated = [
            factor.strategy_id
            for factor in brief.decisive_factors
            if factor.code == "pareto_non_dominated"
        ]
        assert non_dominated == ["mock-a", "mock-b"]


class TestRegretMinimaxGoldens:
    """Requirement 9: frozen per-world-type regrets, aggregates, minimax."""

    def test_per_world_type_total_weighted_regret(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        for strategy_id in STRATEGIES:
            totals = profiles[strategy_id].per_seed_total_weighted_regrets
            assert len(totals) == 100
            for position, seed_id in enumerate(SEED_IDENTIFIERS):
                assert (
                    totals[position]
                    == EXPECTED_WORLD_TYPE_TOTAL_REGRET[strategy_id][world_types[seed_id]]
                ), (strategy_id, seed_id)

    def test_total_regret_aggregates(self, acceptance_store: InMemoryScenarioStore) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        expected_per_objective: dict[str, tuple[float, float]] = {
            "mock-a": (0.0, 1.89),
            "mock-b": (0.618, 0.44),
            "mock-c": (0.618, 1.175),
        }
        for strategy_id in STRATEGIES:
            profile = profiles[strategy_id]
            aggregates = (
                profile.maximum_total_weighted_regret,
                profile.median_total_weighted_regret,
                profile.p95_total_weighted_regret,
            )
            assert aggregates == EXPECTED_REGRET_AGGREGATES[strategy_id], strategy_id
            assert (
                tuple(record.weighted_regret for record in profile.per_objective_weighted_regret)
                == expected_per_objective[strategy_id]
            ), strategy_id

    def test_minimax_unique_tie_set_without_identifier_fallback(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert brief.terminal_reason.values == (
            BEST_MAXIMUM_TOTAL_REGRET,
            TIE_TOLERANCE,
        )
        # The unique tie set is exactly the frozen singleton {mock-b}:
        # both other candidates exceed best + tolerance and are excluded.
        assert MINIMAX_TIE_SET == ("mock-b",)
        assert profiles["mock-a"].maximum_total_weighted_regret > (
            BEST_MAXIMUM_TOTAL_REGRET + TIE_TOLERANCE
        )
        assert profiles["mock-c"].maximum_total_weighted_regret > (
            BEST_MAXIMUM_TOTAL_REGRET + TIE_TOLERANCE
        )
        assert profiles["mock-b"].maximum_total_weighted_regret == BEST_MAXIMUM_TOTAL_REGRET
        assert not any(factor.code == "minimax_regret_tie" for factor in brief.blocking_factors)
        # No lexicographic or identifier fallback: mock-a precedes
        # mock-b in the considered order, yet mock-b is the unique
        # minimax preference.
        assert brief.considered_strategy_ids == STRATEGIES
        assert brief.preferred_strategy_id == "mock-b"
        assert brief.preferred_strategy_id != brief.considered_strategy_ids[0]


class TestBriefGoldens:
    """Requirement 10: the preferred brief through the real query."""

    def test_brief_identity_status_and_terminal_reason(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert brief.identifier == GOLDEN_BRIEF_ID
        assert brief.content_hash == GOLDEN_BRIEF_CONTENT_HASH
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "mock-b"
        assert brief.terminal_reason.code == "unique_minimax_preference"
        assert brief.terminal_reason.values == (2.24, 0.05)
        assert brief.terminal_reason.related_strategy_ids == ()

    def test_nearest_competitor_and_regret_gap_within_one_ulp(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        minimax_factor = next(
            factor for factor in brief.decisive_factors if factor.code == "unique_minimax_regret"
        )
        assert minimax_factor.strategy_id == "mock-b"
        assert minimax_factor.related_strategy_ids == (NEAREST_COMPETITOR,)
        assert len(minimax_factor.values) == 3
        winner = float(minimax_factor.values[0])
        nearest = float(minimax_factor.values[1])
        gap = float(minimax_factor.values[2])
        assert winner == BEST_MAXIMUM_TOTAL_REGRET
        assert nearest == 4.0
        assert gap == REGRET_GAP
        assert is_within_one_ulp(gap, 1.76)
        assert gap == nearest - winner

    def test_exact_decisive_factor_ordering(self, acceptance_store: InMemoryScenarioStore) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        trail = tuple(_factor_tuple(factor) for factor in brief.decisive_factors)
        assert trail == EXPECTED_DECISIVE_FACTORS
        codes = [factor.code for factor in brief.decisive_factors]
        assert codes == [
            "feasible_candidate",
            "feasible_candidate",
            "feasible_candidate",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "target_feasibility_passed",
            "pareto_non_dominated",
            "pareto_non_dominated",
            "unique_minimax_regret",
        ]

    def test_exact_blocking_factor(self, acceptance_store: InMemoryScenarioStore) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        trail = tuple(_factor_tuple(factor) for factor in brief.blocking_factors)
        assert trail == EXPECTED_BLOCKING_FACTORS
        assert brief.blocking_factors[0].code == "dominated_strategy"
        assert brief.blocking_factors[0].strategy_id == "mock-c"
        assert brief.blocking_factors[0].related_strategy_ids == ("mock-b",)

    def test_exact_gate_aware_summary_and_considered_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert brief.summary == GOLDEN_BRIEF_SUMMARY
        assert brief.considered_strategy_ids == STRATEGIES
        assert brief.produced_at == NOW


class TestBestMeanIsNotRobustWinner:
    """Requirement 11: best ordinary mean is not the robust preference."""

    def test_mock_a_best_mean_but_worst_regret_mock_b_preferred(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        matrix = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcomes = _outcome_by_strategy_objective(matrix)
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        profiles = _profile_by_strategy(comparison)
        primary_means = {
            strategy_id: math.fsum(outcomes[(strategy_id, "obj-1")].ordered_observed_values) / 100
            for strategy_id in STRATEGIES
        }
        max_regrets = {
            strategy_id: profiles[strategy_id].maximum_total_weighted_regret
            for strategy_id in STRATEGIES
        }
        # mock-a has the best ordinary primary-objective mean (32.46)...
        assert primary_means["mock-a"] == 32.46
        assert primary_means["mock-a"] == min(primary_means.values())
        # ...and the worst maximum total weighted regret (4.0).
        assert max_regrets["mock-a"] == 4.0
        assert max_regrets["mock-a"] == max(max_regrets.values())
        # mock-b has a worse primary mean (94.26)...
        assert primary_means["mock-b"] == 94.26
        assert primary_means["mock-b"] > primary_means["mock-a"]
        # ...yet is the robust preferred strategy with max regret 2.24.
        assert max_regrets["mock-b"] == 2.24
        assert max_regrets["mock-b"] == min(max_regrets.values())
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "mock-b"

    def test_mock_a_reserve_collapse_is_the_causal_reason(
        self, world_types: dict[str, tuple[int, int]]
    ) -> None:
        # In all 54 level-9 worlds mock-a's reserve collapses to 5
        # (t-z2 applies before any reserve-raising transition): the
        # obj-2 regret of 3.0/4.0 in those worlds is a causal
        # consequence of the declared transitions, not a manufactured
        # ranking.
        level_nine_seeds = [
            seed_id for seed_id, world_type in world_types.items() if world_type[0] == 9
        ]
        assert len(level_nine_seeds) == 54
        for seed_id in level_nine_seeds:
            assert expected_observed("mock-a", world_types[seed_id]) == (9, 5)


class TestTieControlProof:
    """Requirement 12: the Phase 26 two-strategy tie/inconclusive control."""

    def _comparison(self, store: InMemoryScenarioStore) -> CampaignStrategyComparison:
        return get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )

    def _brief(self, store: InMemoryScenarioStore) -> CampaignDecisionBrief:
        return get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )

    def test_identical_per_seed_outcomes_across_strategies(
        self, control_store: InMemoryScenarioStore
    ) -> None:
        matrix = get_verified_campaign_outcome_distributions(
            store=control_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_strategy_candidate_ids == CONTROL_STRATEGIES
        first, second = matrix.outcomes
        assert first.ordered_observed_values == second.ordered_observed_values
        assert len(first.ordered_observed_values) == 100
        assert set(first.ordered_observed_values) == {84, 103}
        assert first.empirical_target_achievement_probability == 0.81
        assert second.empirical_target_achievement_probability == 0.81

    def test_all_paired_deltas_zero_and_no_dominance(
        self, control_store: InMemoryScenarioStore
    ) -> None:
        comparison = self._comparison(control_store)
        for pair in comparison.paired_comparisons:
            assert pair.win_count == 0
            assert pair.tie_count == 100
            assert pair.loss_count == 0
            assert all(delta == 0.0 for delta in pair.ordered_paired_deltas)
        for relation in comparison.dominance_relations:
            assert relation.dominates is False

    def test_identical_regret_across_strategies(self, control_store: InMemoryScenarioStore) -> None:
        comparison = self._comparison(control_store)
        profiles = _profile_by_strategy(comparison)
        assert profiles["mock-a"].per_seed_total_weighted_regrets == (
            profiles["mock-b"].per_seed_total_weighted_regrets
        )
        for strategy_id in CONTROL_STRATEGIES:
            profile = profiles[strategy_id]
            assert profile.feasible is True
            assert profile.maximum_total_weighted_regret == 0.0
            assert profile.median_total_weighted_regret == 0.0
            assert profile.p95_total_weighted_regret == 0.0
            assert all(total == 0.0 for total in profile.per_seed_total_weighted_regrets)
            assert profile.per_objective_weighted_regret[0].weighted_regret == 0.0

    def test_minimax_tie_set_contains_both_and_status_inconclusive(
        self, control_store: InMemoryScenarioStore
    ) -> None:
        brief = self._brief(control_store)
        assert brief.status == "inconclusive"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.code == "regret_tie_within_tolerance"
        assert brief.terminal_reason.values == (0.0, TIE_TOLERANCE)
        assert brief.terminal_reason.related_strategy_ids == CONTROL_STRATEGIES
        tie_factor = next(
            factor for factor in brief.blocking_factors if factor.code == "minimax_regret_tie"
        )
        assert tie_factor.related_strategy_ids == CONTROL_STRATEGIES
        assert tie_factor.values == (0.0, TIE_TOLERANCE)
        # No identifier-order or lexicographic winner is manufactured.
        assert brief.considered_strategy_ids == CONTROL_STRATEGIES
        assert brief.preferred_strategy_id is None

    def test_control_brief_factors_and_summary(self, control_store: InMemoryScenarioStore) -> None:
        brief = self._brief(control_store)
        assert tuple(_factor_tuple(factor) for factor in brief.decisive_factors) == (
            EXPECTED_CONTROL_DECISIVE_FACTORS
        )
        assert tuple(_factor_tuple(factor) for factor in brief.blocking_factors) == (
            EXPECTED_CONTROL_BLOCKING_FACTORS
        )
        assert brief.summary == GOLDEN_CONTROL_BRIEF_SUMMARY

    def test_control_hard_coded_identifiers(self, control_store: InMemoryScenarioStore) -> None:
        policy = control_store.get_campaign_decision_policy(TENANT, "campaign-1")
        comparison = self._comparison(control_store)
        brief = self._brief(control_store)
        assert policy.identifier == GOLDEN_CONTROL_POLICY_ID
        assert policy.content_hash == GOLDEN_CONTROL_POLICY_CONTENT_HASH
        assert comparison.identifier == GOLDEN_CONTROL_COMPARISON_ID
        assert comparison.content_hash == GOLDEN_CONTROL_COMPARISON_CONTENT_HASH
        assert brief.identifier == GOLDEN_CONTROL_BRIEF_ID
        assert brief.content_hash == GOLDEN_CONTROL_BRIEF_CONTENT_HASH


class TestHardCodedIdentifiersAndLineage:
    """Requirement 13: frozen identifiers and the complete artifact lineage."""

    def test_hard_coded_policy_comparison_brief_identifiers(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        policy = acceptance_store.get_campaign_decision_policy(TENANT, "campaign-1")
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        # Frozen authoring-time goldens - never recomputed through the
        # identity functions inside these assertions.
        assert policy.identifier == GOLDEN_POLICY_ID
        assert policy.content_hash == GOLDEN_POLICY_CONTENT_HASH
        assert comparison.identifier == GOLDEN_COMPARISON_ID
        assert comparison.content_hash == GOLDEN_COMPARISON_CONTENT_HASH
        assert brief.identifier == GOLDEN_BRIEF_ID
        assert brief.content_hash == GOLDEN_BRIEF_CONTENT_HASH

    def test_policy_declaration_field_goldens(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        policy = acceptance_store.get_campaign_decision_policy(TENANT, "campaign-1")
        assert policy.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"
        assert policy.target_requirement_mode == "per_objective"
        assert policy.minimum_target_achievement_probability is None
        assert [r.objective_id for r in policy.objective_target_requirements] == [
            "obj-1",
            "obj-2",
        ]
        assert all(
            r.minimum_target_achievement_probability == 0.40
            for r in policy.objective_target_requirements
        )
        assert [s.objective_id for s in policy.objective_weight_snapshots] == [
            "obj-1",
            "obj-2",
        ]
        assert all(s.weight == 1.0 for s in policy.objective_weight_snapshots)
        assert policy.minimum_sample_count == MINIMUM_SAMPLE_COUNT
        assert policy.tie_tolerance == TIE_TOLERANCE
        assert policy.all_targeted_objectives_are_hard_gates is True
        assert policy.tail_alpha == 0.95
        assert policy.declared_at == DECLARED_AT
        assert policy.metadata == {}

    def test_complete_lineage_across_all_artifacts(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        policy = acceptance_store.get_campaign_decision_policy(TENANT, "campaign-1")
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcome = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = acceptance_store.get_campaign(TENANT, "campaign-1")
        world = acceptance_store.get_world(TENANT, campaign.world_version_id)
        profile = acceptance_store.get_evaluation_profile(TENANT, "scenario-1")
        # Comparison lineage: policy and outcome-matrix references.
        assert comparison.policy_id == policy.identifier
        assert comparison.policy_content_hash == policy.content_hash
        assert comparison.source_outcome_matrix_id == outcome.identifier
        assert comparison.source_outcome_matrix_content_hash == outcome.content_hash
        # Brief lineage: policy, comparison, and outcome-matrix references.
        assert brief.policy_id == policy.identifier
        assert brief.policy_content_hash == policy.content_hash
        assert brief.comparison_id == comparison.identifier
        assert brief.comparison_content_hash == comparison.content_hash
        assert brief.source_outcome_matrix_id == outcome.identifier
        assert brief.source_outcome_matrix_content_hash == outcome.content_hash
        assert brief.evaluation_profile_id == profile.identifier
        assert brief.evaluation_profile_content_hash == profile.content_hash
        # Outcome-matrix lineage: campaign/scenario/world/profile and the
        # realization/observation matrices.
        assert outcome.campaign_id == campaign.identifier
        assert outcome.scenario_id == campaign.scenario_id
        assert outcome.scenario_content_hash == policy.scenario_content_hash
        assert outcome.world_version_id == world.identifier
        assert outcome.world_content_hash == world.content_hash
        assert outcome.evaluation_profile_id == profile.identifier
        assert outcome.evaluation_profile_content_hash == profile.content_hash
        assert outcome.uncertainty_model_id == realization_matrix.uncertainty_model_id
        assert outcome.uncertainty_model_content_hash == (
            realization_matrix.uncertainty_model_content_hash
        )
        assert outcome.source_world_realization_matrix_id == realization_matrix.identifier
        assert outcome.source_world_realization_matrix_content_hash == (
            realization_matrix.content_hash
        )
        assert outcome.source_metric_observation_matrix_id == observation_matrix.identifier
        assert outcome.source_metric_observation_matrix_content_hash == (
            observation_matrix.content_hash
        )
        # Derived timestamps are the frozen fixture instant - no wall clock.
        assert outcome.derived_at == NOW
        assert observation_matrix.assembled_at == NOW
        assert comparison.derived_at == NOW
        assert brief.produced_at == NOW


class TestReadOnlyAndDeterminism:
    """Requirement 14: byte-identical repeated queries, zero store mutation."""

    def test_repeated_comparison_and_brief_queries_byte_identical_and_read_only(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        before = store_state(acceptance_store)
        comparisons = [
            get_verified_campaign_strategy_comparison(
                store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
            )
            for _ in range(3)
        ]
        briefs = [
            get_verified_campaign_decision_brief(
                store=acceptance_store, tenant_id=TENANT, campaign_id="campaign-1"
            )
            for _ in range(3)
        ]
        for later_comparison in comparisons[1:]:
            assert canonical_json(later_comparison.model_dump(mode="json")) == canonical_json(
                comparisons[0].model_dump(mode="json")
            )
        for later_brief in briefs[1:]:
            assert canonical_json(later_brief.model_dump(mode="json")) == canonical_json(
                briefs[0].model_dump(mode="json")
            )
        assert comparisons[0].identifier == GOLDEN_COMPARISON_ID
        assert briefs[0].identifier == GOLDEN_BRIEF_ID
        # The complete store digest is unchanged: no writes, no activity,
        # no execution/replay/extraction/repair triggered by any query.
        assert store_state(acceptance_store) == before
        assert acceptance_store.list_operational_activity(TENANT) == ()
        assert len(acceptance_store.get_run_plans(TENANT, "campaign-1")) == 300
        assert len(acceptance_store._realization_run_trajectory_executions) == 300
        assert len(acceptance_store._realization_run_metric_observation_sets) == 300
        assert len(acceptance_store._realization_run_trajectory_replay_manifests) == 0

    def test_comparison_and_brief_are_never_stored(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        assert _stored_artifact_scan(acceptance_store) == []
        assert not hasattr(acceptance_store, "put_campaign_strategy_comparison")
        assert not hasattr(acceptance_store, "put_campaign_decision_brief")
        # Exactly one stored decision policy remains.
        assert len(acceptance_store._campaign_decision_policies) == 1
        stored = acceptance_store.get_campaign_decision_policy(TENANT, "campaign-1")
        assert stored.identifier == GOLDEN_POLICY_ID


class TestNoManufacturedEvidence:
    """Requirement 15: every record is lifecycle-produced; nothing injected."""

    def test_lifecycle_produced_exactly_the_real_records(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        assert len(acceptance_store.get_run_plans(TENANT, "campaign-1")) == 300
        assert len(acceptance_store._realization_run_trajectory_executions) == 300
        assert len(acceptance_store._realization_run_metric_observation_sets) == 300
        assert len(acceptance_store._realization_run_trajectory_replay_manifests) == 0
        candidates = acceptance_store.get_strategy_candidates(TENANT, "campaign-1")
        assert {candidate.identifier for candidate in candidates} == set(STRATEGIES)
        transitions = acceptance_store.list_domain_state_transitions(TENANT, "scenario-1")
        assert {transition.transition_id for transition in transitions} == {
            "t-x",
            "t-y",
            "t-z",
            "t-z2",
            "t-v",
            "t-w",
            "t-u",
        }
        observation_bindings = acceptance_store.list_domain_metric_observations(
            TENANT, "scenario-1"
        )
        assert {binding.metric_id for binding in observation_bindings} == {"m-1", "m-2"}
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        assert len(plans) == 3
        assert len(acceptance_store._campaign_decision_policies) == 1
        # The prepared campaign carries exactly the three strategy
        # candidates through the real LEGION boundary.
        candidates = phase27_legion().request_strategies(build_request(TENANT))
        assert tuple(candidate.identifier for candidate in candidates) == STRATEGIES

    def test_no_expected_artifact_was_injected_into_the_fixture(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        # Every stored observation set is engine-produced: its values
        # match the independent causal expectation function, and the
        # store holds no derived decision artifact.
        plans_by_key = _run_plan_by_key(acceptance_store)
        for strategy_id in STRATEGIES:
            for seed_id in SEED_IDENTIFIERS:
                run_id = run_identifier(plans_by_key[(strategy_id, seed_id)])
                observed = _observed_by_metric(acceptance_store, run_id)
                expected = expected_observed(strategy_id, world_types[seed_id])
                assert (observed["m-1"], observed["m-2"]) == expected
        assert _stored_artifact_scan(acceptance_store) == []
