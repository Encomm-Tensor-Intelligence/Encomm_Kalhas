"""Tests for the verified read-only campaign decision query services.

Tests for ``kalhas/application/campaign_decision_query_service.py``
(``get_verified_campaign_strategy_comparison`` and
``get_verified_campaign_decision_brief``) and the two frozen integrity
errors added to ``kalhas/application/campaign_decision_errors.py``.
The fixture is a real COMPLETE runtime-3.0.0 multi-objective campaign
(three targeted objectives ``obj-3``/``obj-1``/``obj-5`` in
non-lexicographic order plus two optimization-only objectives
``obj-2``/``obj-4``) built exclusively through the real declaration,
compilation, preparation, and execution services, with the immutable
decision policy declared through the real declaration service
(per-objective thresholds 0.4, minimum sample count 2, tie tolerance
0.05, hard gates on).

Proves:

- successful comparison query: exact ``CampaignStrategyComparison``
  type, exact campaign/policy/outcome lineage, exactly one outcome
  query, exactly one comparison-builder call, the exact
  ``[policy, outcome, comparison]`` call order, repeated byte-identical
  results, and an unchanged complete store digest;
- successful brief query: exact ``CampaignDecisionBrief`` type, exact
  scenario/policy/outcome/comparison lineage, exactly one outcome
  query, exactly one comparison-builder call, exactly one
  brief-builder call, the exact ``[policy, outcome, comparison, brief]``
  call order, the brief receiving the exact same policy/outcome objects
  used by the comparison builder, repeated byte-identical results, and
  an unchanged store digest;
- the policy-first short circuit: a missing policy and a
  foreign-tenant policy raise ``CampaignDecisionPolicyNotFoundError``
  with zero outcome/builder calls and zero writes;
- the campaign/status boundary: unknown and foreign campaigns raise
  ``CampaignNotFoundError`` and every non-COMPLETE state raises
  ``CampaignNotCompleteError`` with zero policy/outcome/builder calls
  after the gate;
- upstream error preservation: policy integrity, outcome integrity,
  and unsupported-runtime errors propagate unchanged and are never
  wrapped into the new integrity errors;
- the new integrity errors: comparison-builder and brief-builder
  ``ValueError``/``OverflowError``, missing and inconsistent campaign
  scenarios, exact typed class, safe generic public message, internal
  cause retained through exception chaining, no raw diagnostic in the
  public message, no partial artifact, and no write;
- call identity and count through recording wrappers on the symbols
  imported into the query-service module - exact counts and order, not
  merely "called";
- architectural prohibitions: no API/NEXUS/LEGION imports, no
  execution/replay/extraction/activity or wall-clock/randomness
  surface, no store write methods, no comparison/brief persistence
  collection, and an exact public ``__all__``.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.application import campaign_decision_query_service as service_module
from kalhas.application import realization_campaign_service
from kalhas.application.campaign_decision_errors import (
    CampaignDecisionBriefIntegrityError,
    CampaignDecisionComparisonIntegrityError,
    CampaignDecisionPolicyIntegrityError,
    CampaignDecisionPolicyNotFoundError,
)
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
    get_verified_campaign_decision_policy,
)
from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    KalhasDomainError,
    ScenarioNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
)
from kalhas.application.realization_campaign_service import prepare_realization_campaign
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import prepare_strategy_trajectory_plans
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    ObjectiveTargetRequirement,
)
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection
from kalhas.contracts.v1.world_realization import DiscreteDistribution
from pydantic import BaseModel

from tests.phase4_helpers import NOW, TENANT, build_request, start
from tests.phase20_helpers import DECLARED_AT, _register_pack, build_observation_scenario
from tests.phase24_helpers import uncertainty_fields
from tests.phase25_helpers import (
    ACCEPTANCE_BRANCH_X,
    ACCEPTANCE_BRANCH_Y,
    ACCEPTANCE_SEEDS,
    ACCEPTANCE_VALUE_X,
    ACCEPTANCE_VALUE_Y,
    acceptance_legion,
    inject_unsupported_recorded_runtime,
)

SERVICE_PATH = Path(service_module.__file__).resolve()
ERRORS_PATH = (
    Path(__file__).resolve().parents[1] / "kalhas" / "application" / "campaign_decision_errors.py"
)

#: The five authoritative scenario objectives in deliberately
#: NON-lexicographic order (sorted would be obj-1..obj-5): the first
#: three are targeted, the last two optimization-only.
_ACCEPTANCE_OBJECTIVES = (
    Objective(
        identifier="obj-3",
        description="Minimize the primary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-1",
        description="Maximize the primary metric",
        direction=ObjectiveDirection.MAXIMIZE,
        target=90.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-5",
        description="Reach the primary metric target band",
        direction=ObjectiveDirection.REACH,
        target=100.0,
        weight=1.0,
    ),
    Objective(
        identifier="obj-2",
        description="Optimize the primary metric downward",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-4",
        description="Optimize the primary metric upward",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=1.0,
    ),
)

#: The caller-owned profile drafts binding every objective to m-1.
_ACCEPTANCE_PROFILE_DRAFTS = (
    ObjectiveMetricBindingDraft(
        objective_id="obj-3", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-1", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-5",
        metric_id="m-1",
        reach_tolerance=5.0,
        normalization_scale=100.0,
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-2", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
    ObjectiveMetricBindingDraft(
        objective_id="obj-4", metric_id="m-1", reach_tolerance=None, normalization_scale=100.0
    ),
)

#: The exact ordered per-objective target coverage of the fixture.
_TARGETED_IDS = ("obj-3", "obj-1", "obj-5")

#: The four symbols the query module imports from the accepted layers.
_SYMBOL_NAMES = (
    "get_verified_campaign_decision_policy",
    "get_verified_campaign_outcome_distributions",
    "build_campaign_strategy_comparison",
    "build_campaign_decision_brief",
)

#: The exact generic public messages of the two new integrity errors.
_COMPARISON_INTEGRITY_MESSAGE = (
    "Campaign strategy comparison derivation failed integrity verification and was rejected"
)
_BRIEF_INTEGRITY_MESSAGE = (
    "Campaign decision brief derivation failed integrity verification and was rejected"
)

#: A raw diagnostic sentinel that must never leak into a public message.
_RAW_SENTINEL = "SENTINEL-RAW-DIAGNOSTIC-9f3a"


def _build_complete_store() -> InMemoryScenarioStore:
    """A real COMPLETE runtime-3.0.0 campaign over the fixture objectives.

    Declarations, compilation, preparation, planning, start, full
    execution (2 strategies x 2 seeds), and per-run observation
    extraction all go through the real public services; the evaluation
    profile is declared before world compilation so the compiled world
    embeds the exact snapshot.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario().model_copy(
        update={"objectives": list(_ACCEPTANCE_OBJECTIVES)}
    )
    store.put_scenario(scenario)
    _register_pack(store)
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=uncertainty_fields(),
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-x",
        description="X branch transition",
        guard_values={"level": ACCEPTANCE_BRANCH_X},
        target_values={"level": ACCEPTANCE_VALUE_X},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        transition_id="t-y",
        description="Y branch transition",
        guard_values={"level": ACCEPTANCE_BRANCH_Y},
        target_values={"level": ACCEPTANCE_VALUE_Y},
        declared_at=DECLARED_AT,
    )
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-1",
        state_field_id="level",
        declared_at=DECLARED_AT,
    )
    declare_world_uncertainty_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=(
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-1",
                state_field_id="level",
                distribution=DiscreteDistribution(
                    kind="discrete",
                    values=(ACCEPTANCE_BRANCH_X, ACCEPTANCE_BRANCH_Y),
                    probabilities=(0.5, 0.5),
                ),
                rounding_policy="nearest_ties_to_even",
            ),
        ),
        declared_at=DECLARED_AT,
    )
    declare_scenario_evaluation_profile(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=_ACCEPTANCE_PROFILE_DRAFTS,
        declared_at=DECLARED_AT,
        metadata={},
    )
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    with patch.object(realization_campaign_service, "EXPECTED_STRATEGY_SET_SIZE", 2):
        prepare_realization_campaign(
            store=store,
            legion=acceptance_legion(),
            tenant_id=TENANT,
            scenario_id="scenario-1",
            world_version_id=compiled.version.identifier,
            strategy_request=build_request(TENANT),
            campaign_id="campaign-1",
            campaign_name="Decision query fixture campaign",
            seed_ensemble=ACCEPTANCE_SEEDS,
            created_at=NOW,
        )
    prepare_strategy_trajectory_plans(
        store=store, legion=acceptance_legion(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store


def _declare_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """Declare the fixture policy through the real declaration service.

    Per-objective thresholds 0.4 on the three targeted objectives in
    exact authoritative order, minimum sample count 2 (equal to the
    fixture's seed count, so the decision is evaluated), tie tolerance
    0.05, hard gates on.
    """
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-1",
        draft=CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="per_objective",
            minimum_sample_count=2,
            tie_tolerance=0.05,
            all_targeted_objectives_are_hard_gates=True,
            declared_at=DECLARED_AT,
            minimum_target_achievement_probability=None,
            objective_target_requirements=tuple(
                ObjectiveTargetRequirement(
                    objective_id=objective_id,
                    minimum_target_achievement_probability=0.4,
                )
                for objective_id in _TARGETED_IDS
            ),
            metadata={},
        ),
    )


@pytest.fixture(scope="module")
def query_store() -> InMemoryScenarioStore:
    """The real executed COMPLETE campaign store with a declared policy."""
    store = _build_complete_store()
    _declare_policy(store)
    return store


@pytest.fixture()
def store(query_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the real lifecycle store."""
    return copy.deepcopy(query_store)


def _dump_value(value: object) -> object:
    """One canonical JSON dump of a stored record or record tuple."""
    if isinstance(value, tuple):
        return tuple(_dump_value(item) for item in value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _store_state(store: InMemoryScenarioStore) -> str:
    """The canonical JSON digest of the complete store state."""
    payload: dict[str, object] = {}
    for name, collection in store.__dict__.items():
        payload[name] = {repr(key): _dump_value(value) for key, value in collection.items()}
    return canonical_json(payload)


def _stored_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """The raw stored policy snapshot (private test seam)."""
    return store._campaign_decision_policies[(TENANT, "campaign-1")]


def _install_recorders(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[str], dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]]]:
    """Recording wrappers around every imported query/builder symbol.

    The wrappers forward to the real functions; the order list and the
    per-symbol captured argument lists prove exact call counts, exact
    call order, and object identity across calls - never merely
    "called".
    """
    originals = {name: getattr(service_module, name) for name in _SYMBOL_NAMES}
    order: list[str] = []
    captured: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {
        name: [] for name in _SYMBOL_NAMES
    }

    def make_wrapper(name: str) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            order.append(name)
            captured[name].append((args, kwargs))
            return originals[name](*args, **kwargs)

        return wrapper

    for name in _SYMBOL_NAMES:
        monkeypatch.setattr(service_module, name, make_wrapper(name))
    return order, captured


def _builder_args(
    captured: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]], name: str
) -> dict[str, Any]:
    """The keyword arguments of the single recorded call of one symbol."""
    assert len(captured[name]) == 1
    return captured[name][0][1]


def _replace_builder(
    monkeypatch: pytest.MonkeyPatch, name: str, error_type: type[Exception]
) -> None:
    """Replace one builder symbol with a deterministic raiser."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise error_type(_RAW_SENTINEL)

    monkeypatch.setattr(service_module, name, boom)


def _attribute_parts(attribute: ast.Attribute) -> list[str]:
    """The dotted parts of one attribute chain (boundary-scan helper)."""
    parts: list[str] = []
    target: ast.expr = attribute
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return parts


class TestComparisonQuery:
    """Successful comparison query: type, lineage, identity, and determinism."""

    def test_comparison_query_returns_exact_verified_lineage(
        self, store: InMemoryScenarioStore
    ) -> None:
        comparison = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(comparison, CampaignStrategyComparison)
        policy = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        outcome = get_verified_campaign_outcome_distributions(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert comparison.campaign_id == "campaign-1"
        assert comparison.scenario_id == policy.scenario_id == "scenario-1"
        assert comparison.scenario_content_hash == policy.scenario_content_hash
        assert comparison.world_version_id == policy.world_version_id
        assert comparison.world_content_hash == policy.world_content_hash
        assert comparison.runtime_version == "3.0.0"
        assert comparison.comparison_mode == "identical_conditions"
        assert comparison.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"
        assert comparison.policy_id == policy.identifier
        assert comparison.policy_content_hash == policy.content_hash
        assert comparison.tie_tolerance == policy.tie_tolerance == 0.05
        assert comparison.minimum_sample_count == policy.minimum_sample_count == 2
        assert comparison.source_outcome_matrix_id == outcome.identifier
        assert comparison.source_outcome_matrix_content_hash == outcome.content_hash
        assert comparison.ordered_strategy_candidate_ids == ("mock-a", "mock-b")
        assert comparison.ordered_scenario_seed_ids == ("seed-0", "seed-2")
        assert comparison.ordered_objective_ids == ("obj-3", "obj-1", "obj-5", "obj-2", "obj-4")
        assert len(comparison.paired_comparisons) == 2 * 1 * 5
        assert len(comparison.dominance_relations) == 2
        assert len(comparison.robustness_profiles) == 2
        assert comparison.robustness_profiles[0].strategy_candidate_id == "mock-a"
        assert comparison.robustness_profiles[1].strategy_candidate_id == "mock-b"
        assert comparison.derived_at == outcome.derived_at
        assert comparison.derived_at == store.get_campaign(TENANT, "campaign-1").created_at
        assert comparison.identifier.startswith("campaign-strategy-comparison-")
        assert len(comparison.content_hash) == 64

    def test_comparison_query_calls_policy_outcome_builder_exactly_once_in_order(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order, captured = _install_recorders(monkeypatch)
        comparison = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(comparison, CampaignStrategyComparison)
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
            "build_campaign_strategy_comparison",
        ]
        assert len(captured["build_campaign_decision_brief"]) == 0
        for name in _SYMBOL_NAMES:
            assert len(captured[name]) == order.count(name)

    def test_comparison_builder_receives_the_verified_policy_and_single_outcome_matrix(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, captured = _install_recorders(monkeypatch)
        service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        args = _builder_args(captured, "build_campaign_strategy_comparison")
        policy = args["policy"]
        outcome = args["outcome_matrix"]
        assert isinstance(policy, CampaignDecisionPolicy)
        assert isinstance(outcome, CampaignOutcomeDistributionMatrix)
        assert policy.identifier == _stored_policy(store).identifier
        assert outcome.ordered_strategy_candidate_ids == ("mock-a", "mock-b")

    def test_comparison_query_repeated_results_byte_identical_and_store_unchanged(
        self, store: InMemoryScenarioStore
    ) -> None:
        before = _store_state(store)
        first = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        third = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        first_json = first.model_dump(mode="json")
        assert second.model_dump(mode="json") == first_json
        assert third.model_dump(mode="json") == first_json
        assert canonical_json(second.model_dump(mode="json")) == canonical_json(first_json)
        assert canonical_json(third.model_dump(mode="json")) == canonical_json(first_json)
        assert _store_state(store) == before


class TestBriefQuery:
    """Successful brief query: type, lineage, identity, and determinism."""

    def test_brief_query_returns_exact_verified_lineage(self, store: InMemoryScenarioStore) -> None:
        brief = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(brief, CampaignDecisionBrief)
        policy = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        comparison = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        scenario = store.get_scenario(TENANT, "scenario-1")
        assert brief.campaign_id == "campaign-1"
        assert brief.scenario_id == "scenario-1"
        assert brief.world_version_id == policy.world_version_id
        assert brief.world_content_hash == policy.world_content_hash
        assert brief.runtime_version == "3.0.0"
        assert brief.comparison_mode == "identical_conditions"
        assert brief.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"
        assert brief.policy_id == policy.identifier
        assert brief.policy_content_hash == policy.content_hash
        assert brief.comparison_id == comparison.identifier
        assert brief.comparison_content_hash == comparison.content_hash
        assert brief.considered_strategy_ids == ("mock-a", "mock-b")
        # Identical shared-seed strategy evidence: no dominance, zero
        # regret everywhere, both strategies tied within the tolerance.
        assert brief.status == "inconclusive"
        assert brief.preferred_strategy_id is None
        assert brief.terminal_reason.code == "regret_tie_within_tolerance"
        assert brief.terminal_reason.values == (0.0, 0.05)
        assert brief.terminal_reason.related_strategy_ids == ("mock-a", "mock-b")
        # Both strategies are feasible and non-dominated, so the
        # decisive factors are exactly: one feasible_candidate per
        # strategy, one target_feasibility_passed per passed targeted
        # objective per strategy (3 targeted objectives, all passed),
        # and one pareto_non_dominated per strategy - in pipeline-stage
        # order; the minimax tie is the single blocking factor.
        decisive_codes = [factor.code for factor in brief.decisive_factors]
        assert decisive_codes == (
            ["feasible_candidate"] * 2
            + ["target_feasibility_passed"] * 6
            + ["pareto_non_dominated"] * 2
        )
        assert all(factor.strategy_id in ("mock-a", "mock-b") for factor in brief.decisive_factors)
        assert any(factor.code == "minimax_regret_tie" for factor in brief.blocking_factors)
        assert len(brief.summary) > 1
        assert brief.robustness_profiles == comparison.robustness_profiles
        assert brief.assumptions == tuple(scenario.assumptions)
        assert brief.evaluation_profile_id == policy.evaluation_profile_id
        assert brief.evaluation_profile_content_hash == policy.evaluation_profile_content_hash
        assert brief.uncertainty_model_id is not None
        assert brief.uncertainty_model_content_hash is not None
        assert brief.source_outcome_matrix_id == comparison.source_outcome_matrix_id
        assert (
            brief.source_outcome_matrix_content_hash
            == comparison.source_outcome_matrix_content_hash
        )
        assert brief.produced_at == comparison.derived_at
        assert brief.identifier.startswith("campaign-decision-brief-")
        assert len(brief.content_hash) == 64

    def test_brief_query_calls_each_symbol_exactly_once_in_exact_order(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order, captured = _install_recorders(monkeypatch)
        brief = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(brief, CampaignDecisionBrief)
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
            "build_campaign_strategy_comparison",
            "build_campaign_decision_brief",
        ]
        for name in _SYMBOL_NAMES:
            assert len(captured[name]) == 1

    def test_brief_receives_the_exact_policy_and_outcome_objects_used_by_comparison(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, captured = _install_recorders(monkeypatch)
        brief = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(brief, CampaignDecisionBrief)
        comparison_args = _builder_args(captured, "build_campaign_strategy_comparison")
        brief_args = _builder_args(captured, "build_campaign_decision_brief")
        assert brief_args["policy"] is comparison_args["policy"]
        assert brief_args["outcome_matrix"] is comparison_args["outcome_matrix"]
        assert brief_args["comparison"].identifier == brief.comparison_id
        assert brief_args["scenario"].identifier == "scenario-1"
        assert brief_args["scenario"].tenant_id == TENANT

    def test_brief_query_repeated_results_byte_identical_and_store_unchanged(
        self, store: InMemoryScenarioStore
    ) -> None:
        before = _store_state(store)
        first = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        third = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        first_json = first.model_dump(mode="json")
        assert second.model_dump(mode="json") == first_json
        assert third.model_dump(mode="json") == first_json
        assert canonical_json(second.model_dump(mode="json")) == canonical_json(first_json)
        assert canonical_json(third.model_dump(mode="json")) == canonical_json(first_json)
        assert _store_state(store) == before


class TestPolicyFirstShortCircuit:
    """The verified policy must exist before any outcome derivation."""

    def test_missing_policy_raises_not_found_with_zero_outcome_and_zero_builders(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del store._campaign_decision_policies[(TENANT, "campaign-1")]
        order, captured = _install_recorders(monkeypatch)
        before = _store_state(store)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignDecisionPolicyNotFoundError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert exc_info.value.tenant_id == TENANT
            assert exc_info.value.campaign_id == "campaign-1"
            assert str(exc_info.value) == "Campaign decision policy not found"
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_decision_policy",
        ]
        assert len(captured["get_verified_campaign_outcome_distributions"]) == 0
        assert len(captured["build_campaign_strategy_comparison"]) == 0
        assert len(captured["build_campaign_decision_brief"]) == 0
        assert _store_state(store) == before

    def test_foreign_tenant_policy_raises_not_found_with_zero_downstream_work(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        foreign = _stored_policy(store)
        del store._campaign_decision_policies[(TENANT, "campaign-1")]
        store._campaign_decision_policies[("tenant-2", "campaign-1")] = foreign
        order, captured = _install_recorders(monkeypatch)
        before = _store_state(store)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignDecisionPolicyNotFoundError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert str(exc_info.value) == "Campaign decision policy not found"
        assert len(captured["get_verified_campaign_outcome_distributions"]) == 0
        assert len(captured["build_campaign_strategy_comparison"]) == 0
        assert len(captured["build_campaign_decision_brief"]) == 0
        assert _store_state(store) == before


class TestCampaignStatusBoundary:
    """Unknown/foreign campaigns and every non-COMPLETE state fail first."""

    @pytest.mark.parametrize(
        ("tenant_id", "campaign_id"),
        ((TENANT, "campaign-unknown"), ("tenant-2", "campaign-1")),
    )
    def test_unknown_and_foreign_campaigns_raise_not_found_and_do_no_work(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        tenant_id: str,
        campaign_id: str,
    ) -> None:
        order, captured = _install_recorders(monkeypatch)
        before = _store_state(store)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignNotFoundError):
                query(store=store, tenant_id=tenant_id, campaign_id=campaign_id)
        assert order == []
        for name in _SYMBOL_NAMES:
            assert len(captured[name]) == 0
        assert _store_state(store) == before

    @pytest.mark.parametrize(
        "state",
        (
            CampaignState.DRAFT,
            CampaignState.VALIDATED,
            CampaignState.COMPILED,
            CampaignState.RUNNING,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        ),
    )
    def test_non_complete_states_rejected_before_any_policy_or_outcome_work(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        state: CampaignState,
    ) -> None:
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": state})
        )
        order, captured = _install_recorders(monkeypatch)
        before = _store_state(store)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignNotCompleteError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert exc_info.value.current_state == state.value
        assert order == []
        for name in _SYMBOL_NAMES:
            assert len(captured[name]) == 0
        assert _store_state(store) == before


class TestUpstreamErrorPreservation:
    """Established typed errors propagate unchanged; nothing is wrapped."""

    def test_policy_integrity_error_propagates_unchanged(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tampered = _stored_policy(store).model_copy(update={"identifier": "tampered-identifier"})
        store._campaign_decision_policies[(TENANT, "campaign-1")] = tampered
        order, captured = _install_recorders(monkeypatch)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert not isinstance(exc_info.value, CampaignDecisionComparisonIntegrityError)
            assert not isinstance(exc_info.value, CampaignDecisionBriefIntegrityError)
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_decision_policy",
        ]
        assert len(captured["get_verified_campaign_outcome_distributions"]) == 0
        assert len(captured["build_campaign_strategy_comparison"]) == 0

    def test_outcome_integrity_error_propagates_unchanged(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        order, captured = _install_recorders(monkeypatch)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(CampaignOutcomeDistributionMatrixIntegrityError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert not isinstance(exc_info.value, CampaignDecisionComparisonIntegrityError)
            assert not isinstance(exc_info.value, CampaignDecisionBriefIntegrityError)
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
        ]
        assert len(captured["build_campaign_strategy_comparison"]) == 0
        assert len(captured["build_campaign_decision_brief"]) == 0

    def test_unsupported_recorded_runtime_error_propagates_unchanged(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        order, captured = _install_recorders(monkeypatch)
        for query in (
            service_module.get_verified_campaign_strategy_comparison,
            service_module.get_verified_campaign_decision_brief,
        ):
            with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
                query(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            assert not isinstance(exc_info.value, CampaignDecisionComparisonIntegrityError)
            assert not isinstance(exc_info.value, CampaignDecisionBriefIntegrityError)
        assert order == [
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
            "get_verified_campaign_decision_policy",
            "get_verified_campaign_outcome_distributions",
        ]
        assert len(captured["build_campaign_strategy_comparison"]) == 0
        assert len(captured["build_campaign_decision_brief"]) == 0


class TestLocalIntegrityTranslation:
    """Only the precisely expected local builder/scenario failures translate."""

    @pytest.mark.parametrize(
        ("error_type", "expected_class"),
        (
            (ValueError, CampaignDecisionComparisonIntegrityError),
            (OverflowError, CampaignDecisionComparisonIntegrityError),
        ),
    )
    def test_comparison_builder_failure_translates_on_comparison_query(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        error_type: type[Exception],
        expected_class: type[CampaignDecisionComparisonIntegrityError],
    ) -> None:
        _replace_builder(monkeypatch, "build_campaign_strategy_comparison", error_type)
        before = _store_state(store)
        with pytest.raises(CampaignDecisionComparisonIntegrityError) as exc_info:
            service_module.get_verified_campaign_strategy_comparison(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        self._assert_safe_integrity_error(
            exc_info.value,
            expected_class,
            _COMPARISON_INTEGRITY_MESSAGE,
            "campaign strategy comparison derivation failed",
            error_type,
            cause_has_sentinel=True,
        )
        assert _store_state(store) == before

    @pytest.mark.parametrize(
        ("error_type", "expected_class"),
        (
            (ValueError, CampaignDecisionComparisonIntegrityError),
            (OverflowError, CampaignDecisionComparisonIntegrityError),
        ),
    )
    def test_comparison_builder_failure_translates_on_brief_query(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        error_type: type[Exception],
        expected_class: type[CampaignDecisionComparisonIntegrityError],
    ) -> None:
        _replace_builder(monkeypatch, "build_campaign_strategy_comparison", error_type)
        before = _store_state(store)
        with pytest.raises(CampaignDecisionComparisonIntegrityError) as exc_info:
            service_module.get_verified_campaign_decision_brief(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        self._assert_safe_integrity_error(
            exc_info.value,
            expected_class,
            _COMPARISON_INTEGRITY_MESSAGE,
            "campaign strategy comparison derivation failed",
            error_type,
            cause_has_sentinel=True,
        )
        assert _store_state(store) == before

    @pytest.mark.parametrize(
        "error_type",
        (ValueError, OverflowError),
    )
    def test_brief_builder_failure_translates_on_brief_query(
        self,
        store: InMemoryScenarioStore,
        monkeypatch: pytest.MonkeyPatch,
        error_type: type[Exception],
    ) -> None:
        _replace_builder(monkeypatch, "build_campaign_decision_brief", error_type)
        before = _store_state(store)
        with pytest.raises(CampaignDecisionBriefIntegrityError) as exc_info:
            service_module.get_verified_campaign_decision_brief(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        self._assert_safe_integrity_error(
            exc_info.value,
            CampaignDecisionBriefIntegrityError,
            _BRIEF_INTEGRITY_MESSAGE,
            "campaign decision brief derivation failed",
            error_type,
            cause_has_sentinel=True,
        )
        assert _store_state(store) == before

    def test_missing_campaign_scenario_translates_on_brief_query(
        self, store: InMemoryScenarioStore
    ) -> None:
        del store._scenarios[(TENANT, "scenario-1")]
        before = _store_state(store)
        with pytest.raises(CampaignDecisionBriefIntegrityError) as exc_info:
            service_module.get_verified_campaign_decision_brief(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        self._assert_safe_integrity_error(
            exc_info.value,
            CampaignDecisionBriefIntegrityError,
            _BRIEF_INTEGRITY_MESSAGE,
            "campaign scenario record missing",
            ScenarioNotFoundError,
        )
        assert _store_state(store) == before

    def test_inconsistent_campaign_scenario_translates_on_brief_query(
        self, store: InMemoryScenarioStore
    ) -> None:
        other = build_observation_scenario().model_copy(update={"identifier": "scenario-other"})
        store._scenarios[(TENANT, "scenario-1")] = other
        before = _store_state(store)
        with pytest.raises(CampaignDecisionBriefIntegrityError) as exc_info:
            service_module.get_verified_campaign_decision_brief(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        self._assert_safe_integrity_error(
            exc_info.value,
            CampaignDecisionBriefIntegrityError,
            _BRIEF_INTEGRITY_MESSAGE,
            "campaign scenario identity mismatch",
            None,
        )
        assert _store_state(store) == before

    def test_comparison_query_never_translates_brief_builder_failures(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The comparison query never reaches the brief builder: a
        # failing brief builder must not affect it at all.
        _replace_builder(monkeypatch, "build_campaign_decision_brief", ValueError)
        comparison = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert isinstance(comparison, CampaignStrategyComparison)

    @staticmethod
    def _assert_safe_integrity_error(
        error: Any,
        expected_class: type[KalhasDomainError],
        expected_message: str,
        expected_reason: str,
        expected_cause: type[BaseException] | None,
        *,
        cause_has_sentinel: bool = False,
    ) -> None:
        assert error.tenant_id == TENANT
        assert error.campaign_id == "campaign-1"
        assert str(error) == expected_message
        assert error.reason == expected_reason
        assert _RAW_SENTINEL not in str(error)
        assert _RAW_SENTINEL not in repr(error)
        # The type assertion must come after the attribute accesses so
        # mypy does not narrow the Any parameter to the base class.
        assert type(error) is expected_class
        if expected_cause is not None:
            assert isinstance(error.__cause__, expected_cause)
            if cause_has_sentinel:
                assert _RAW_SENTINEL in str(error.__cause__)


class TestNewIntegrityErrors:
    """The two frozen integrity error contracts in the errors module."""

    def test_comparison_integrity_error_contract(self) -> None:
        error = CampaignDecisionComparisonIntegrityError(TENANT, "campaign-1")
        assert error.tenant_id == TENANT
        assert error.campaign_id == "campaign-1"
        assert error.reason is None
        assert str(error) == _COMPARISON_INTEGRITY_MESSAGE
        with_reason = CampaignDecisionComparisonIntegrityError(
            TENANT, "campaign-1", reason="internal diagnostic"
        )
        assert with_reason.reason == "internal diagnostic"
        assert str(with_reason) == _COMPARISON_INTEGRITY_MESSAGE
        assert "internal diagnostic" not in str(with_reason)

    def test_brief_integrity_error_contract(self) -> None:
        error = CampaignDecisionBriefIntegrityError(TENANT, "campaign-1")
        assert error.tenant_id == TENANT
        assert error.campaign_id == "campaign-1"
        assert error.reason is None
        assert str(error) == _BRIEF_INTEGRITY_MESSAGE
        with_reason = CampaignDecisionBriefIntegrityError(
            TENANT, "campaign-1", reason="internal diagnostic"
        )
        assert with_reason.reason == "internal diagnostic"
        assert str(with_reason) == _BRIEF_INTEGRITY_MESSAGE
        assert "internal diagnostic" not in str(with_reason)

    def test_new_errors_subclass_kalhas_domain_error(self) -> None:
        from kalhas.application.domain_errors import KalhasDomainError

        assert issubclass(CampaignDecisionComparisonIntegrityError, KalhasDomainError)
        assert issubclass(CampaignDecisionBriefIntegrityError, KalhasDomainError)

    def test_errors_module_all_includes_both_new_names(self) -> None:
        import kalhas.application.campaign_decision_errors as errors_module

        assert "CampaignDecisionComparisonIntegrityError" in errors_module.__all__
        assert "CampaignDecisionBriefIntegrityError" in errors_module.__all__
        assert "CampaignDecisionPolicyNotFoundError" in errors_module.__all__
        assert "CampaignDecisionPolicyAlreadyExistsError" in errors_module.__all__
        assert "CampaignDecisionPolicyValidationError" in errors_module.__all__
        assert "CampaignDecisionPolicyIntegrityError" in errors_module.__all__
        assert len(errors_module.__all__) == 6


class TestArchitecturalBoundary:
    """The query module stays pure, read-only, and decision-surface-free."""

    def test_public_all_is_exactly_the_two_queries(self) -> None:
        assert service_module.__all__ == [
            "get_verified_campaign_strategy_comparison",
            "get_verified_campaign_decision_brief",
        ]

    def test_module_boundary_scan(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported |= {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert "fastapi" not in imported
        assert "nexus" not in imported
        assert "legion" not in imported
        assert "adapters" not in imported
        assert "random" not in imported
        assert "datetime" not in imported
        assert "time" not in imported
        paths: set[str] = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        paths |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(path.startswith("kalhas.api") for path in paths)
        assert not any(path.startswith("kalhas.adapters") for path in paths)

    def test_module_never_calls_store_writes_execution_or_activity(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        chains: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                chains.add(".".join(reversed(_attribute_parts(node.func))))
        store_chains = {chain for chain in chains if chain.startswith("store.")}
        assert store_chains == {
            "store.get_campaign",
            "store.get_campaign_status",
            "store.get_scenario",
        }
        assert "store.update_campaign_status" not in chains
        assert "store.append_operational_activity" not in chains
        assert not any(
            chain.rsplit(".", 1)[-1].startswith(("put_", "update_", "append_")) for chain in chains
        )
        name_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not (name_calls & {"execute", "replay", "extract", "random", "uuid", "time"})

    def test_module_uses_only_the_accepted_imported_symbols(self) -> None:
        source = SERVICE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        symbols: set[str] = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "build_campaign_strategy_comparison" in symbols
        assert "build_campaign_decision_brief" in symbols
        assert "get_verified_campaign_decision_policy" in symbols
        assert "get_verified_campaign_outcome_distributions" in symbols

    def test_no_comparison_or_brief_persistence_surface_in_the_store(
        self, store: InMemoryScenarioStore
    ) -> None:
        assert "_campaign_strategy_comparisons" not in store.__dict__
        assert "_campaign_decision_briefs" not in store.__dict__
        assert not hasattr(store, "put_campaign_strategy_comparison")
        assert not hasattr(store, "put_campaign_decision_brief")

    def test_query_results_are_detached_from_stored_state(
        self, store: InMemoryScenarioStore
    ) -> None:
        comparison = service_module.get_verified_campaign_strategy_comparison(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        brief = service_module.get_verified_campaign_decision_brief(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored_policy = _stored_policy(store)
        before = _store_state(store)
        # The returned artifacts must never alias stored records: a
        # caller-side mutation of a returned nested model is impossible
        # (frozen contracts), so prove detachment by deep-copy identity
        # of the underlying payload snapshots.
        assert comparison.policy_id == stored_policy.identifier
        assert brief.policy_id == stored_policy.identifier
        assert _store_state(store) == before
