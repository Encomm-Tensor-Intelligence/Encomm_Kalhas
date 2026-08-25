"""Gate 27.1 final acceptance: the unpatched exact-five causal proof.

One deterministic, domain-neutral, end-to-end runtime-3.0.0 campaign
over exactly four immutable shared seeds (``seed-000``, ``seed-001``,
``seed-003``, ``seed-004`` - constructed directly from their identifiers,
never searched or adaptively chosen), built exclusively through the real
public services: declarations (state model ``sm-1`` with integer
level/reserve, seven guarded causal transitions, two metric-observation
bindings, the discrete uncertainty model over both fields, and the
two-objective evaluation profile declared before world compilation),
world compilation, runtime-3 preparation through the real
``prepare_realization_campaign`` under the **unmodified** production
``EXPECTED_STRATEGY_SET_SIZE == 5`` invariant with the **real**
``MockLegionAdapter`` and explicit per-strategy
``declared_transition_sequences``, real trajectory planning, start, 20
real executions (5 strategies x 4 seeds), and 20 explicit observation
extractions. No cardinality monkeypatch, no production monkeypatch, no
replacement ``request_strategies``, no injected execution/observation/
outcome/comparison/brief, and no copied decision algorithm exist
anywhere in this suite.

Proves:

- the real adapter returns exactly its five default candidates in the
  exact production order; the prepared campaign holds exactly 5
  candidates, 4 shared seeds, 20 run plans, 5 authoritative strategy
  trajectory plans, 20 runtime-3 executions, and 20 extracted
  metric-observation sets;
- every stored plan carries its declared logical transition order;
  every execution attempt sequence equals an independent guard/state-
  update reconstruction over the declared transition table; every
  extracted observation equals the engine-produced final state; the
  five complete trajectory/outcome signatures are pairwise distinct,
  and the distinctness is causal - it follows from the distinct
  declared plans applied to shared realized worlds;
- shared-seed fairness: exactly 4 realizations (never 20) with the
  identical realization ID and content hash bound by all five
  strategies for every shared seed, and the frozen world types;
- the frozen target-achievement probabilities, all five strategies
  feasible at the 0.40 hard gates, the frozen maximum total weighted
  regrets (strict one-ULP discipline for the non-exact decimal), the
  exact dominance facts, the preferred brief (status preferred,
  preferred ``mock-adaptive``, all five strategies considered in exact
  candidate order, no identifier-order winner), and the hard-coded
  authoring-time policy/comparison/brief identifiers, content hashes,
  and gate-aware summary - never recomputed through identity functions;
- complete lineage alignment across the policy, comparison, brief,
  outcome matrix, realization matrix, observation matrix, evaluation
  profile, campaign, and compiled world;
- replay equivalence and idempotency through the real
  ``replay_realization_run`` for at least one completed/extracted run
  of every strategy: expected/recomputed execution and observation-set
  hashes equal the stored hashes, realization identity and plan-set
  hash align, repeated identical replay is byte-idempotent, only the
  two manifest collections change, and the replay service accepts no
  adapter at all (structural no-NEXUS/no-LEGION proof);
- read-only decision queries: byte-identical repeats, unchanged
  complete store digest, no persistence of comparison or brief, and no
  operational activity; tenant isolation: foreign-tenant decision and
  replay attempts fail with the established typed non-leaking errors
  and leave the digest unchanged;
- failure atomicity: an invalid declared logical transition id supplied
  only for the fifth strategy makes the real planning service raise
  ``InvalidTrajectoryDraftError`` with zero authoritative trajectory
  plans stored, no partial collection, and no hidden activity - still
  with no patch and no production mutation.
"""

from __future__ import annotations

import inspect
import re
from typing import Any

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.campaign_decision_query_service import (
    get_verified_campaign_decision_brief,
    get_verified_campaign_strategy_comparison,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    InvalidTrajectoryDraftError,
    RunNotFoundError,
    TrajectoryPlansNotFoundError,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.realization_replay import replay_realization_run
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignStrategyComparison,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix

from tests.phase4_helpers import NOW, TENANT, build_request
from tests.phase27_1_helpers import (
    CAMPAIGN_ID,
    CAMPAIGN_NAME,
    CAUSAL_EXPECTATION,
    EXPECTED_MAX_TOTAL_REGRETS,
    EXPECTED_TARGET_PROBABILITIES,
    EXPECTED_WORLD_TYPES,
    GOLDEN_BRIEF_CONTENT_HASH,
    GOLDEN_BRIEF_ID,
    GOLDEN_BRIEF_SUMMARY,
    GOLDEN_COMPARISON_CONTENT_HASH,
    GOLDEN_COMPARISON_ID,
    GOLDEN_POLICY_CONTENT_HASH,
    GOLDEN_POLICY_ID,
    METRIC_IDS,
    MINIMUM_SAMPLE_COUNT,
    OBJECTIVE_IDS,
    SEED_IDENTIFIERS,
    STORE_COLLECTIONS,
    STRATEGIES,
    STRATEGY_PLANS,
    THRESHOLDS,
    TIE_TOLERANCE,
    TRANSITIONS,
    build_seed_ensemble,
    complete_exact_five_store,
    declare_exact_five_policy,
    declared_fixture_store,
    dump_value,
    exact_five_legion,
    expected_attempt_sequence,
    expected_observed,
    is_within_one_ulp,
    realized_world_type,
    store_state,
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


def _run_plan_by_key(store: InMemoryScenarioStore) -> dict[tuple[str, str], Any]:
    """The (strategy, seed) -> run plan lookup of the acceptance campaign."""
    return {
        (plan.strategy_candidate_id, plan.scenario_seed_id): plan
        for plan in store.get_run_plans(TENANT, CAMPAIGN_ID)
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


def _collection_states(store: InMemoryScenarioStore) -> dict[str, str]:
    """A per-collection canonical digest map for surgical write proofs."""
    return {
        name: canonical_json(
            {repr(key): dump_value(value) for key, value in getattr(store, name).items()}
        )
        for name in STORE_COLLECTIONS
    }


def _factor_tuple(factor: Any) -> tuple[str, str | None, str | None, tuple[Any, ...]]:
    """One reduced factor-trail tuple of one decision factor record."""
    return (factor.code, factor.strategy_id, factor.objective_id, tuple(factor.values))


@pytest.fixture(scope="module")
def acceptance_store() -> InMemoryScenarioStore:
    """The real COMPLETE 20-run exact-five campaign with policy declared."""
    store = complete_exact_five_store()
    declare_exact_five_policy(store)
    return store


@pytest.fixture(scope="module")
def world_types(acceptance_store: InMemoryScenarioStore) -> dict[str, tuple[int, int]]:
    """The realized ``(level, reserve)`` world type of every shared seed."""
    return {
        seed.identifier: realized_world_type(acceptance_store, seed)
        for seed in build_seed_ensemble()
    }


class TestUnpatchedExactFivePreparation:
    """Requirement 1: the real adapter and the unmodified production path."""

    def test_real_adapter_returns_exactly_the_five_default_candidates(self) -> None:
        # A bare real adapter (no declarations) still returns the exact
        # five default candidates in the exact production order: the
        # declaration mapping changes proposals, never the candidate set.
        candidates = MockLegionAdapter().request_strategies(build_request(TENANT))
        assert tuple(candidate.identifier for candidate in candidates) == STRATEGIES
        declared = exact_five_legion().request_strategies(build_request(TENANT))
        assert tuple(candidate.identifier for candidate in declared) == STRATEGIES
        # The production invariant constant is imported live and equals 5.
        from kalhas.application.campaign_service import EXPECTED_STRATEGY_SET_SIZE

        assert EXPECTED_STRATEGY_SET_SIZE == 5

    def test_prepared_campaign_holds_exact_cardinalities(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        campaign = acceptance_store.get_campaign(TENANT, CAMPAIGN_ID)
        assert campaign.name == CAMPAIGN_NAME
        assert tuple(seed.identifier for seed in campaign.seed_ensemble) == SEED_IDENTIFIERS
        assert campaign.strategy_candidate_ids == list(STRATEGIES)
        assert campaign.created_at == NOW
        stored_plans = acceptance_store.get_run_plans(TENANT, CAMPAIGN_ID)
        assert len(stored_plans) == 20
        assert {plan.runtime_version for plan in stored_plans} == {"3.0.0"}
        assert len(acceptance_store.get_strategy_candidates(TENANT, CAMPAIGN_ID)) == 5
        assert len(acceptance_store._realization_run_trajectory_executions) == 20
        assert len(acceptance_store._realization_run_metric_observation_sets) == 20

    def test_exactly_five_authoritative_trajectory_plans_were_stored(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        # Through the real verifying getter: exactly five authoritative
        # plans, one per strategy, produced by the real planning service.
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, CAMPAIGN_ID)
        assert len(plans) == 5
        assert tuple(plan.strategy_candidate_id for plan in plans) == STRATEGIES
        assert len(acceptance_store._strategy_trajectory_plans) == 1


class TestDistinctDeclaredPlans:
    """Requirement 2: every stored plan carries its declared transition order."""

    def test_every_plan_carries_its_declared_logical_transition_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, CAMPAIGN_ID)
        sequences = set()
        for plan in plans:
            logical = tuple(reference.transition_id for reference in plan.transition_references)
            assert logical == STRATEGY_PLANS[plan.strategy_candidate_id]
            sequences.add(logical)
        # Five genuinely different executable orders - not five labels.
        assert len(sequences) == 5

    def test_declared_mapping_is_immutable_and_complete(self) -> None:
        assert set(STRATEGY_PLANS) == set(STRATEGIES)
        assert set(CAUSAL_EXPECTATION) == set(STRATEGIES)

    def test_transition_catalog_is_exactly_the_seven_declared_transitions(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        transitions = acceptance_store.list_domain_state_transitions(TENANT, "scenario-1")
        assert {transition.transition_id for transition in transitions} == {
            transition_id for transition_id, _guard, _target in TRANSITIONS
        }
        bindings = acceptance_store.list_domain_metric_observations(TENANT, "scenario-1")
        assert {binding.metric_id for binding in bindings} == set(METRIC_IDS)


class TestSharedSeedFairness:
    """Requirement 3: identical shared worlds for all five strategies."""

    def test_exactly_four_shared_realizations_never_twenty(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert len(realization_matrix.realizations) == len(SEED_IDENTIFIERS) == 4
        assert realization_matrix.ordered_scenario_seed_ids == SEED_IDENTIFIERS
        assert len({r.identifier for r in realization_matrix.realizations}) == 4
        assert len({r.content_hash for r in realization_matrix.realizations}) == 4

    def test_frozen_world_types_of_the_four_shared_seeds(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        assert world_types == EXPECTED_WORLD_TYPES
        for seed_id, world_type in EXPECTED_WORLD_TYPES.items():
            position = SEED_IDENTIFIERS.index(seed_id)
            realization_matrix = get_verified_campaign_world_realizations(
                store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            )
            overrides = {
                override.state_field_id: override.value
                for override in realization_matrix.realizations[
                    position
                ].realized_initial_state_overrides
            }
            assert (overrides["level"], overrides["reserve"]) == world_type

    def test_all_five_strategies_bind_identical_realizations_per_seed(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        plans_by_key = _run_plan_by_key(acceptance_store)
        assert len(plans_by_key) == 20
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

    def test_observation_matrix_is_seed_aligned_with_the_realization_matrix(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert observation_matrix.ordered_world_realization_ids == tuple(
            r.identifier for r in realization_matrix.realizations
        )
        assert observation_matrix.ordered_world_realization_content_hashes == tuple(
            r.content_hash for r in realization_matrix.realizations
        )


class TestCausalExecutionProofs:
    """Requirement 4: attempts, observations, and causal distinctness."""

    def test_every_attempt_sequence_matches_the_independent_reconstruction(
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
                applied = [transition for transition, _outcome in attempts if _outcome == "applied"]
                assert applied, (strategy_id, seed_id)

    def test_every_observation_equals_the_engine_produced_final_state(
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
                assert (observed[METRIC_IDS[0]], observed[METRIC_IDS[1]]) == expected, (
                    strategy_id,
                    seed_id,
                )
                # The recorded final state of the execution itself equals
                # the independent expectation - the observation is the
                # engine-produced final state, not a separate artifact.
                execution = acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_id
                )
                finals = {
                    (result.final_state["level"], result.final_state["reserve"])
                    for result in execution.results
                }
                assert finals == {expected}, (strategy_id, seed_id)

    def test_five_complete_signatures_are_pairwise_distinct(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        plans_by_key = _run_plan_by_key(acceptance_store)
        signatures: dict[
            str, tuple[tuple[tuple[int, int], ...], frozenset[tuple[tuple[str, str], ...]]]
        ] = {}
        for strategy_id in STRATEGIES:
            finals = tuple(
                expected_observed(strategy_id, world_types[seed_id]) for seed_id in SEED_IDENTIFIERS
            )
            attempts = frozenset(
                _attempt_sequence(
                    acceptance_store,
                    run_identifier(plans_by_key[(strategy_id, seed_id)]),
                )
                for seed_id in SEED_IDENTIFIERS
            )
            signatures[strategy_id] = (finals, attempts)
        assert len(signatures) == 5
        distinct_finals = {finals for finals, _attempts in signatures.values()}
        assert len(distinct_finals) == 5
        for first in range(len(STRATEGIES)):
            for second in range(first + 1, len(STRATEGIES)):
                assert signatures[STRATEGIES[first]] != signatures[STRATEGIES[second]]

    def test_distinctness_is_causal_not_labelled(
        self,
        acceptance_store: InMemoryScenarioStore,
        world_types: dict[str, tuple[int, int]],
    ) -> None:
        # Every strategy's complete final vector follows mechanically
        # from applying its declared guarded plan to the SAME shared
        # realized worlds: no outcome was assigned, injected, or chosen.
        plans_by_key = _run_plan_by_key(acceptance_store)
        for strategy_id in STRATEGIES:
            for seed_id in SEED_IDENTIFIERS:
                run_id = run_identifier(plans_by_key[(strategy_id, seed_id)])
                execution = acceptance_store.get_realization_run_trajectory_execution(
                    TENANT, run_id
                )
                # The executed plan references belong to this strategy's
                # authoritative plan, and the initial state is exactly the
                # shared realized world of this seed.
                initial = {
                    (result.initial_state["level"], result.initial_state["reserve"])
                    for result in execution.results
                }
                assert initial == {world_types[seed_id]}, (strategy_id, seed_id)
                assert execution.scenario_seed_id == seed_id
                assert execution.strategy_candidate_id == strategy_id
        # The five final vectors differ only through the declared plans:
        # identical worlds, five distinct declared orders, five distinct
        # causal outcome vectors.
        vectors = {
            strategy_id: tuple(
                expected_observed(strategy_id, world_types[seed_id]) for seed_id in SEED_IDENTIFIERS
            )
            for strategy_id in STRATEGIES
        }
        assert len(set(vectors.values())) == 5


class TestDecisionEvidence:
    """Requirement 5: probabilities, feasibility, regret, dominance, brief."""

    def test_exact_target_achievement_probabilities_and_feasibility(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        profiles = _profile_by_strategy(comparison)
        assert comparison.ordered_strategy_candidate_ids == STRATEGIES
        assert comparison.ordered_objective_ids == OBJECTIVE_IDS
        assert comparison.tie_tolerance == TIE_TOLERANCE
        assert comparison.minimum_sample_count == MINIMUM_SAMPLE_COUNT
        for strategy_id in STRATEGIES:
            profile = profiles[strategy_id]
            assert profile.feasible is True, strategy_id
            observed_probabilities = []
            for record, objective_id in zip(profile.target_feasibility, OBJECTIVE_IDS, strict=True):
                assert record.objective_id == objective_id
                assert record.threshold == THRESHOLDS[objective_id]
                expected_probability = EXPECTED_TARGET_PROBABILITIES[strategy_id][
                    OBJECTIVE_IDS.index(objective_id)
                ]
                assert record.observed_probability == expected_probability
                assert record.passed is True
                observed_probabilities.append(record.observed_probability)
            assert tuple(observed_probabilities) == EXPECTED_TARGET_PROBABILITIES[strategy_id]

    def test_maximum_total_weighted_regrets_with_one_ulp_discipline(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        profiles = _profile_by_strategy(comparison)
        for strategy_id in STRATEGIES:
            maximum = profiles[strategy_id].maximum_total_weighted_regret
            expected = EXPECTED_MAX_TOTAL_REGRETS[strategy_id]
            if strategy_id == "mock-balanced":
                # The strict one-ULP discipline for the non-exact decimal
                # 4.44: no broad tolerance, exactly one float step.
                assert is_within_one_ulp(maximum, 4.44), strategy_id
            else:
                assert maximum == expected, strategy_id
        # mock-adaptive is the unique minimum-maximum-regret strategy.
        maxima = {
            strategy_id: profiles[strategy_id].maximum_total_weighted_regret
            for strategy_id in STRATEGIES
        }
        assert min(maxima, key=lambda sid: maxima[sid]) == "mock-adaptive"
        assert maxima["mock-adaptive"] < min(
            value for sid, value in maxima.items() if sid != "mock-adaptive"
        )

    def test_exact_dominance_facts(self, acceptance_store: InMemoryScenarioStore) -> None:
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        profiles = _profile_by_strategy(comparison)
        dominating_pairs = set()
        for relation in comparison.dominance_relations:
            if relation.dominates:
                dominating_pairs.add(
                    (relation.first_strategy_candidate_id, relation.second_strategy_candidate_id)
                )
        assert dominating_pairs == {
            ("mock-adaptive", "mock-conservative"),
            ("mock-adaptive", "mock-balanced"),
            ("mock-diversified", "mock-conservative"),
            ("mock-diversified", "mock-balanced"),
            ("mock-conservative", "mock-balanced"),
        }
        assert profiles["mock-adaptive"].dominated_by == ()
        assert profiles["mock-baseline"].dominated_by == ()
        assert profiles["mock-diversified"].dominated_by == ()
        assert set(profiles["mock-conservative"].dominated_by) == {
            "mock-adaptive",
            "mock-diversified",
        }
        assert profiles["mock-balanced"].dominated_by != ()
        assert set(profiles["mock-adaptive"].dominates) == {"mock-conservative", "mock-balanced"}
        assert set(profiles["mock-diversified"].dominates) == {
            "mock-conservative",
            "mock-balanced",
        }
        assert profiles["mock-baseline"].dominates == ()

    def test_preferred_brief_without_identifier_order_winner(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert brief.status == "preferred"
        assert brief.preferred_strategy_id == "mock-adaptive"
        # All five strategies were considered in the exact candidate order.
        assert brief.considered_strategy_ids == STRATEGIES
        # No winner is manufactured through identifier order: the first
        # and last candidates are real non-preferred results and the
        # preferred strategy is neither of them.
        assert brief.considered_strategy_ids[0] == "mock-baseline"
        assert brief.considered_strategy_ids[-1] == "mock-diversified"
        assert brief.preferred_strategy_id not in (
            brief.considered_strategy_ids[0],
            brief.considered_strategy_ids[-1],
        )
        # The four non-preferred candidates are real evaluated results.
        assert brief.preferred_strategy_id == "mock-adaptive"
        assert set(brief.considered_strategy_ids) - {brief.preferred_strategy_id} == {
            "mock-baseline",
            "mock-conservative",
            "mock-balanced",
            "mock-diversified",
        }

    def test_terminal_reason_unique_minimax_preference(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert brief.terminal_reason.code == "unique_minimax_preference"
        assert brief.terminal_reason.values == (0.94, TIE_TOLERANCE)
        minimax_factor = next(
            factor for factor in brief.decisive_factors if factor.code == "unique_minimax_regret"
        )
        assert minimax_factor.strategy_id == "mock-adaptive"
        # The nearest competitor is the deterministic tie-broken runner-up
        # among the tied 2.94 maximum-regret strategies (baseline and
        # diversified); the real service reports mock-diversified.
        assert minimax_factor.related_strategy_ids == ("mock-diversified",)
        winner = float(minimax_factor.values[0])
        nearest = float(minimax_factor.values[1])
        gap = float(minimax_factor.values[2])
        assert winner == 0.94
        # The nearest competitor is the tied 2.94 maximum-regret runner-up.
        assert nearest == EXPECTED_MAX_TOTAL_REGRETS["mock-diversified"] == 2.94
        assert gap == nearest - winner
        assert gap == 2.0

    def test_decisive_trail_shape_and_non_dominated_order(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        codes = [factor.code for factor in brief.decisive_factors]
        assert codes == [
            "feasible_candidate",
            "feasible_candidate",
            "feasible_candidate",
            "feasible_candidate",
            "feasible_candidate",
            *(["target_feasibility_passed"] * 10),
            "pareto_non_dominated",
            "pareto_non_dominated",
            "pareto_non_dominated",
            "unique_minimax_regret",
        ]
        feasible_order = [
            factor.strategy_id
            for factor in brief.decisive_factors
            if factor.code == "feasible_candidate"
        ]
        assert feasible_order == list(STRATEGIES)
        non_dominated = [
            factor.strategy_id
            for factor in brief.decisive_factors
            if factor.code == "pareto_non_dominated"
        ]
        assert non_dominated == ["mock-baseline", "mock-adaptive", "mock-diversified"]

    def test_blocking_factors_name_only_dominated_strategies(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert brief.blocking_factors
        for factor in brief.blocking_factors:
            assert factor.code == "dominated_strategy"
            assert factor.strategy_id in ("mock-conservative", "mock-balanced")
        assert {factor.strategy_id for factor in brief.blocking_factors} == {
            "mock-conservative",
            "mock-balanced",
        }
        assert not any(factor.code == "minimax_regret_tie" for factor in brief.blocking_factors)


class TestIdentityHashAndLineageGoldens:
    """Requirement 6: hard-coded goldens and complete lineage alignment."""

    def test_hard_coded_policy_comparison_brief_goldens(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        policy = acceptance_store.get_campaign_decision_policy(TENANT, CAMPAIGN_ID)
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        # Frozen authoring-time goldens - never recomputed through the
        # identity or hash builder functions inside these assertions.
        assert policy.identifier == GOLDEN_POLICY_ID
        assert policy.content_hash == GOLDEN_POLICY_CONTENT_HASH
        assert comparison.identifier == GOLDEN_COMPARISON_ID
        assert comparison.content_hash == GOLDEN_COMPARISON_CONTENT_HASH
        assert brief.identifier == GOLDEN_BRIEF_ID
        assert brief.content_hash == GOLDEN_BRIEF_CONTENT_HASH

    def test_policy_declaration_field_goldens(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        from tests.phase20_helpers import DECLARED_AT

        policy = acceptance_store.get_campaign_decision_policy(TENANT, CAMPAIGN_ID)
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
        assert policy.declared_at == DECLARED_AT
        assert policy.metadata == {}

    def test_exact_gate_aware_summary(self, acceptance_store: InMemoryScenarioStore) -> None:
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert brief.summary == GOLDEN_BRIEF_SUMMARY
        assert brief.produced_at == NOW

    def test_complete_lineage_across_all_artifacts(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        policy = acceptance_store.get_campaign_decision_policy(TENANT, CAMPAIGN_ID)
        comparison = get_verified_campaign_strategy_comparison(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        brief = get_verified_campaign_decision_brief(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        outcome = get_verified_campaign_outcome_distributions(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        realization_matrix = get_verified_campaign_world_realizations(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        campaign = acceptance_store.get_campaign(TENANT, CAMPAIGN_ID)
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
        assert outcome.world_version_id == world.identifier
        assert outcome.world_content_hash == world.content_hash
        assert outcome.evaluation_profile_id == profile.identifier
        assert outcome.evaluation_profile_content_hash == profile.content_hash
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


@pytest.fixture(scope="module")
def replay_store() -> InMemoryScenarioStore:
    """A fresh COMPLETE exact-five store for the replay-mutating proofs."""
    return complete_exact_five_store()


@pytest.fixture(scope="module")
def replay_free_store() -> InMemoryScenarioStore:
    """A fresh COMPLETE store whose replay-manifest maps stay empty."""
    return complete_exact_five_store()


class TestReplayEquivalence:
    """Requirement 7: exact replay of one representative run per strategy."""

    def test_replay_one_representative_run_per_strategy_is_exact(
        self, replay_store: InMemoryScenarioStore
    ) -> None:
        plans_by_key = _run_plan_by_key(replay_store)
        for strategy_id in STRATEGIES:
            run_id = run_identifier(plans_by_key[(strategy_id, "seed-000")])
            generic = replay_realization_run(store=replay_store, tenant_id=TENANT, run_id=run_id)
            assert generic.replay_classification == "exact"
            assert generic.strategy_candidate_id == strategy_id
            assert generic.scenario_seed_id == "seed-000"
            assert generic.created_at == NOW
            realization_manifest = replay_store.get_realization_run_trajectory_replay_manifest(
                TENANT, run_id
            )
            execution = replay_store.get_realization_run_trajectory_execution(TENANT, run_id)
            observations = replay_store.get_realization_run_metric_observation_set(TENANT, run_id)
            # Expected and recomputed execution hashes equal the stored hash.
            assert realization_manifest.expected_execution_hash == execution.content_hash
            assert realization_manifest.recomputed_execution_hash == execution.content_hash
            # Expected and recomputed observation-set hashes equal the stored hash.
            assert realization_manifest.expected_observation_set_hash == observations.content_hash
            assert realization_manifest.recomputed_observation_set_hash == observations.content_hash
            # World realization identity and plan-set hash align with the
            # verified execution artifact.
            assert realization_manifest.world_realization_id == execution.world_realization_id
            assert (
                realization_manifest.world_realization_content_hash
                == execution.world_realization_content_hash
            )
            assert (
                realization_manifest.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
            )
            assert realization_manifest.replayed_at == NOW

    def test_replay_service_accepts_no_adapter_structural_no_legion_proof(self) -> None:
        # The real replay service takes only the store, the tenant, and
        # the deterministic run id: there is no adapter seam through
        # which NEXUS or LEGION could be called during replay.
        signature = inspect.signature(replay_realization_run)
        assert set(signature.parameters) == {"store", "tenant_id", "run_id"}

    def test_repeated_identical_replay_is_idempotent_and_writes_only_manifests(
        self, replay_store: InMemoryScenarioStore
    ) -> None:
        plans_by_key = _run_plan_by_key(replay_store)
        run_id = run_identifier(plans_by_key[("mock-adaptive", "seed-001")])
        replay_realization_run(store=replay_store, tenant_id=TENANT, run_id=run_id)
        states_after_first = _collection_states(replay_store)
        first_manifest = replay_store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        generic_second = replay_realization_run(store=replay_store, tenant_id=TENANT, run_id=run_id)
        states_after_second = _collection_states(replay_store)
        second_manifest = replay_store.get_realization_run_trajectory_replay_manifest(
            TENANT, run_id
        )
        # Byte-idempotent manifests and zero further state change.
        assert second_manifest.model_dump(mode="json") == first_manifest.model_dump(mode="json")
        assert generic_second.identifier == f"replay-{run_id}"
        for name in STORE_COLLECTIONS:
            assert states_after_second[name] == states_after_first[name], name
        # Exactly the two replay-manifest collections differ from the
        # pristine complete store: executions, observation sets, plans,
        # statuses, events, and activity are untouched.
        pristine = complete_exact_five_store()
        pristine_states = _collection_states(pristine)
        changed = [
            name for name in STORE_COLLECTIONS if states_after_second[name] != pristine_states[name]
        ]
        assert sorted(changed) == [
            "_realization_run_trajectory_replay_manifests",
            "_replay_manifests",
        ]
        assert replay_store.list_operational_activity(TENANT) == ()


class TestReadOnlyDecisionQueries:
    """Requirement 8: byte-identical repeats and zero store mutation."""

    def test_repeated_queries_byte_identical_digest_unchanged_no_activity(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        before = store_state(acceptance_store)
        comparisons = [
            get_verified_campaign_strategy_comparison(
                store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            )
            for _ in range(3)
        ]
        briefs = [
            get_verified_campaign_decision_brief(
                store=acceptance_store, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
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
        # no execution/replay/extraction triggered by any query.
        assert store_state(acceptance_store) == before
        assert acceptance_store.list_operational_activity(TENANT) == ()
        assert len(acceptance_store.get_run_plans(TENANT, CAMPAIGN_ID)) == 20
        assert len(acceptance_store._realization_run_trajectory_executions) == 20
        assert len(acceptance_store._realization_run_metric_observation_sets) == 20
        assert len(acceptance_store._realization_run_trajectory_replay_manifests) == 0

    def test_comparison_and_brief_are_never_stored(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        assert _stored_artifact_scan(acceptance_store) == []
        assert not hasattr(acceptance_store, "put_campaign_strategy_comparison")
        assert not hasattr(acceptance_store, "put_campaign_decision_brief")
        # Exactly one stored decision policy remains.
        assert len(acceptance_store._campaign_decision_policies) == 1
        stored = acceptance_store.get_campaign_decision_policy(TENANT, CAMPAIGN_ID)
        assert stored.identifier == GOLDEN_POLICY_ID


class TestTenantIsolation:
    """Requirement 9: foreign tenants receive typed non-leaking failures."""

    def test_foreign_tenant_decision_queries_fail_typed_without_leaking(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        before = store_state(acceptance_store)
        for query in (
            get_verified_campaign_strategy_comparison,
            get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignNotFoundError) as exc_info:
                query(store=acceptance_store, tenant_id="tenant-other", campaign_id=CAMPAIGN_ID)
            message = str(exc_info.value)
            assert not re.search(r"[0-9a-f]{64}", message)
            assert GOLDEN_POLICY_ID not in message
            assert GOLDEN_COMPARISON_ID not in message
            assert GOLDEN_BRIEF_ID not in message
        assert store_state(acceptance_store) == before

    def test_foreign_tenant_replay_fails_typed_without_leaking(
        self, replay_free_store: InMemoryScenarioStore
    ) -> None:
        plans_by_key = _run_plan_by_key(replay_free_store)
        run_id = run_identifier(plans_by_key[("mock-adaptive", "seed-000")])
        before = store_state(replay_free_store)
        with pytest.raises(RunNotFoundError) as exc_info:
            replay_realization_run(store=replay_free_store, tenant_id="tenant-other", run_id=run_id)
        message = str(exc_info.value)
        assert not re.search(r"[0-9a-f]{64}", message)
        assert store_state(replay_free_store) == before


class TestPlanningFailureAtomicity:
    """Requirement 10: invalid fifth-strategy draft stores nothing."""

    def test_invalid_fifth_strategy_declaration_is_atomic(
        self,
    ) -> None:
        # A fresh exact-five PREPARED campaign through the real
        # unmodified production path (cardinality 5 accepted unpached).
        store = declared_fixture_store()
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        prepare_realization_campaign(
            store=store,
            legion=exact_five_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id=CAMPAIGN_ID,
            campaign_name=CAMPAIGN_NAME,
            seed_ensemble=build_seed_ensemble(),
            created_at=NOW,
        )
        # Still the real MockLegionAdapter - no subclass, no replaced
        # method, no cardinality patch: the declaration mapping supplies
        # an invalid logical id for the FIFTH strategy only.
        invalid_declarations = dict(STRATEGY_PLANS)
        invalid_declarations["mock-diversified"] = ("t-does-not-exist",)
        invalid_legion = MockLegionAdapter(declared_transition_sequences=invalid_declarations)
        before = store_state(store)
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store, legion=invalid_legion, tenant_id=TENANT, campaign_id=CAMPAIGN_ID
            )
        # Zero authoritative trajectory plans are stored and no partial
        # collection exists: the verifying getter raises its typed
        # not-found error and the raw collection is empty.
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, CAMPAIGN_ID)
        assert len(store._strategy_trajectory_plans) == 0
        # No hidden activity and no mutation of any prepared state.
        assert store.list_operational_activity(TENANT) == ()
        assert store_state(store) == before
        # The campaign remains COMPILED and fully intact for retry.
        assert store.get_campaign_status(TENANT, CAMPAIGN_ID).state.value == "compiled"
        assert len(store.get_run_plans(TENANT, CAMPAIGN_ID)) == 20
        # The real service remains correct: the same fresh preparation
        # with the exact valid declarations plans all five authorities.
        retry_store = declared_fixture_store()
        retry_compiled = MockNexusAdapter(retry_store).compile_scenario(TENANT, "scenario-1")
        prepare_realization_campaign(
            store=retry_store,
            legion=exact_five_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=retry_compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id=CAMPAIGN_ID,
            campaign_name=CAMPAIGN_NAME,
            seed_ensemble=build_seed_ensemble(),
            created_at=NOW,
        )
        retry_plans = prepare_strategy_trajectory_plans(
            store=retry_store, legion=exact_five_legion(), tenant_id=TENANT, campaign_id=CAMPAIGN_ID
        )
        assert len(retry_plans) == 5


class TestNoManufacturedEvidence:
    """Requirement 11: every record is lifecycle-produced; nothing injected."""

    def test_lifecycle_produced_exactly_the_real_records(
        self, acceptance_store: InMemoryScenarioStore
    ) -> None:
        assert len(acceptance_store.get_run_plans(TENANT, CAMPAIGN_ID)) == 20
        assert len(acceptance_store._realization_run_trajectory_executions) == 20
        assert len(acceptance_store._realization_run_metric_observation_sets) == 20
        assert len(acceptance_store._realization_run_trajectory_replay_manifests) == 0
        candidates = acceptance_store.get_strategy_candidates(TENANT, CAMPAIGN_ID)
        assert tuple(candidate.identifier for candidate in candidates) == STRATEGIES
        plans = acceptance_store.get_strategy_trajectory_plans(TENANT, CAMPAIGN_ID)
        assert len(plans) == 5
        assert len(acceptance_store._campaign_decision_policies) == 1
        # The prepared campaign carries exactly the five default
        # candidates through the real LEGION boundary - no replacement.
        candidates = exact_five_legion().request_strategies(build_request(TENANT))
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
                assert (observed[METRIC_IDS[0]], observed[METRIC_IDS[1]]) == expected
        assert _stored_artifact_scan(acceptance_store) == []
