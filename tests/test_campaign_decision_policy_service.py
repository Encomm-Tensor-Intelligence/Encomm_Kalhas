"""Tests for the campaign decision policy declaration service.

Tests for ``kalhas/application/campaign_decision_policy_service.py``
(``declare_campaign_decision_policy`` and
``get_verified_campaign_decision_policy``) and its verified-store
integration in ``kalhas/application/in_memory_store.py``. The fixture
is a real COMPLETE runtime-3.0.0 multi-objective campaign (three
targeted objectives ``obj-3``/``obj-1``/``obj-5`` in non-lexicographic
order plus two optimization-only objectives ``obj-2``/``obj-4``) built
exclusively through the real declaration, compilation, preparation,
and execution services - no outcome, hash, or artifact is hand-authored.

Proves:

- successful global/per-objective declarations with the exact
  authoritative references, the fixed tail alpha 0.95, exact
  authoritative weight snapshots in non-lexicographic objective order
  (never sorted, never normalized, all-zero weights preserved),
  deterministic identifier/content hash/declared timestamp,
  byte-identical policies across equivalent independent stores,
  caller draft/metadata immutability, no operational activity, and the
  exact accepted runtime tuple;
- target validation: inclusive probability boundaries 0 and 1, exact
  ordered per-objective coverage, missing/duplicate/unknown/additional/
  reordered requirement rejection, optimization-only requirement
  rejection, per-objective zero-target rejection, and no silent
  sorting or repair;
- campaign and source verification: unknown/foreign campaigns, every
  non-COMPLETE state, empty/mixed/unsupported recorded run-plan
  runtimes, missing/corrupt world or manifest, campaign/world/scenario
  mismatch, missing embedded profile, missing/corrupt stored profile,
  the exact stored-vs-embedded profile mismatch family (metric_id,
  metric_unit, normalization_scale, reach_tolerance, declared_at,
  metadata), profile/scenario hash mismatch, and binding
  coverage/order/direction/target/weight tampering - all fail closed
  with the safe typed integrity error;
- persistence: one policy per tenant/campaign, duplicate rejection
  with the original untouched, zero writes on failed declarations,
  tenant isolation, deep-copy isolation, no update/delete/replace/
  repair surface, no comparison/brief collection, and no activity
  mutation;
- stored-policy tampering: ownership, identity, identifier, content
  hash, weight snapshots, thresholds/rules, tail alpha,
  declared_at/metadata, nested validator bypass, and malformed
  Python-mode data - every tamper raises
  CampaignDecisionPolicyIntegrityError and is never repaired;
- verified retrieval: deep detached copies, byte-identical repeated
  reads, no COMPLETE requirement on retrieval, and no raw validation
  diagnostic ever escapes;
- API error mapping through the registered-handler pattern on a
  minimal FastAPI instance (no api/app.py modification, no routes
  added to the application): exact 404/409/422/409 statuses and
  ErrorCode values, generic non-leaking messages, and internal reasons
  absent from every response.
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from kalhas.adapters.mocks import MockNexusAdapter
from kalhas.api.errors import register_error_handlers
from kalhas.application import campaign_decision_policy_service as service_module
from kalhas.application import realization_campaign_service
from kalhas.application.campaign_decision_errors import (
    CampaignDecisionPolicyAlreadyExistsError,
    CampaignDecisionPolicyIntegrityError,
    CampaignDecisionPolicyNotFoundError,
    CampaignDecisionPolicyValidationError,
)
from kalhas.application.campaign_decision_identity import (
    campaign_decision_policy_content_hash,
    campaign_decision_policy_identifier,
)
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
    get_verified_campaign_decision_policy,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_identity import (
    evaluation_profile_content_hash,
    evaluation_profile_identifier,
    scenario_content_hash,
)
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
    CampaignDecisionPolicy,
    ObjectiveTargetRequirement,
    ObjectiveWeightSnapshot,
)
from kalhas.contracts.v1.common import ErrorCode
from kalhas.contracts.v1.objective_evaluation import ScenarioEvaluationProfile
from kalhas.contracts.v1.scenario import Objective, ObjectiveDirection
from kalhas.contracts.v1.shared import SCHEMA_VERSION, JsonValue
from kalhas.contracts.v1.world_realization import DiscreteDistribution

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

#: The authoritative targeted objectives in exact order.
TARGETED_IDS = ("obj-3", "obj-1", "obj-5")

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

#: The all-optimization-only variant (no targets anywhere, no reach).
_OPTIMIZATION_ONLY_OBJECTIVES = (
    Objective(
        identifier="obj-3",
        description="Optimize the primary metric downward",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-1",
        description="Optimize the primary metric upward",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-5",
        description="Optimize the secondary metric downward",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-2",
        description="Optimize the secondary metric upward",
        direction=ObjectiveDirection.MAXIMIZE,
        target=None,
        weight=1.0,
    ),
    Objective(
        identifier="obj-4",
        description="Optimize the tertiary metric",
        direction=ObjectiveDirection.MINIMIZE,
        target=None,
        weight=1.0,
    ),
)

_OPTIMIZATION_ONLY_DRAFTS = tuple(
    ObjectiveMetricBindingDraft(
        objective_id=objective.identifier,
        metric_id="m-1",
        reach_tolerance=None,
        normalization_scale=100.0,
    )
    for objective in _OPTIMIZATION_ONLY_OBJECTIVES
)

SERVICE_PATH = Path(service_module.__file__).resolve()


def _build_complete_store(
    *,
    objectives: tuple[Objective, ...],
    profile_drafts: tuple[ObjectiveMetricBindingDraft, ...],
    declare_profile: bool = True,
) -> InMemoryScenarioStore:
    """A real COMPLETE runtime-3.0.0 campaign over the given objectives.

    Declarations, compilation, preparation, planning, start, full
    execution (2 strategies x 2 seeds), and per-run observation
    extraction all go through the real public services. The evaluation
    profile is declared before world compilation when
    ``declare_profile`` is true (so the compiled world embeds the exact
    snapshot); otherwise the world carries no embedded profile.
    """
    store = InMemoryScenarioStore()
    scenario = build_observation_scenario().model_copy(update={"objectives": list(objectives)})
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
    if declare_profile:
        declare_scenario_evaluation_profile(
            store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            bindings=profile_drafts,
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
            campaign_name="Decision policy fixture campaign",
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


def _policy_fixture_store(*, weights: tuple[float, ...] | None = None) -> InMemoryScenarioStore:
    """The main fixture: 3 targeted + 2 optimization-only objectives."""
    objectives = list(_ACCEPTANCE_OBJECTIVES)
    if weights is not None:
        objectives = [
            objective.model_copy(update={"weight": weight})
            for objective, weight in zip(objectives, weights, strict=True)
        ]
    return _build_complete_store(
        objectives=tuple(objectives), profile_drafts=_ACCEPTANCE_PROFILE_DRAFTS
    )


def _zero_target_fixture_store() -> InMemoryScenarioStore:
    """A COMPLETE campaign whose objectives are all optimization-only."""
    return _build_complete_store(
        objectives=_OPTIMIZATION_ONLY_OBJECTIVES, profile_drafts=_OPTIMIZATION_ONLY_DRAFTS
    )


def _no_embedded_profile_fixture_store() -> InMemoryScenarioStore:
    """A COMPLETE campaign whose compiled world embeds no evaluation profile."""
    return _build_complete_store(
        objectives=_ACCEPTANCE_OBJECTIVES,
        profile_drafts=_ACCEPTANCE_PROFILE_DRAFTS,
        declare_profile=False,
    )


@pytest.fixture(scope="module")
def fixture_store() -> InMemoryScenarioStore:
    """The real executed profile-bearing acceptance store (built once)."""
    return _policy_fixture_store()


@pytest.fixture(scope="module")
def zero_target_store() -> InMemoryScenarioStore:
    """The all-optimization-only COMPLETE campaign store (built once)."""
    return _zero_target_fixture_store()


@pytest.fixture(scope="module")
def no_profile_store() -> InMemoryScenarioStore:
    """The COMPLETE campaign store without an embedded profile (built once)."""
    return _no_embedded_profile_fixture_store()


@pytest.fixture(scope="module")
def zero_weight_store() -> InMemoryScenarioStore:
    """The COMPLETE campaign store with all-zero authoritative weights."""
    return _policy_fixture_store(weights=(0.0, 0.0, 0.0, 0.0, 0.0))


@pytest.fixture()
def store(fixture_store: InMemoryScenarioStore) -> InMemoryScenarioStore:
    """A per-test deep-copied isolation of the real lifecycle store."""
    return copy.deepcopy(fixture_store)


def _requirement(objective_id: str, probability: float = 0.4) -> ObjectiveTargetRequirement:
    """One per-objective target requirement instance."""
    return ObjectiveTargetRequirement(
        objective_id=objective_id, minimum_target_achievement_probability=probability
    )


def _targeted_requirements() -> tuple[ObjectiveTargetRequirement, ...]:
    """The exact ordered per-objective coverage of the targeted objectives."""
    return tuple(_requirement(objective_id) for objective_id in TARGETED_IDS)


def _draft(
    *,
    mode: Literal["global", "per_objective"] = "global",
    probability: float | None = 0.5,
    requirements: tuple[ObjectiveTargetRequirement, ...] = (),
    minimum_sample_count: int = 100,
    tie_tolerance: float = 0.05,
    hard_gates: bool = True,
    declared_at: datetime = DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> CampaignDecisionPolicyDeclarationDraft:
    """A caller-owned declaration draft with the explicit decision rules."""
    return CampaignDecisionPolicyDeclarationDraft(
        target_requirement_mode=mode,
        minimum_sample_count=minimum_sample_count,
        tie_tolerance=tie_tolerance,
        all_targeted_objectives_are_hard_gates=hard_gates,
        declared_at=declared_at,
        minimum_target_achievement_probability=probability,
        objective_target_requirements=requirements,
        metadata=metadata if metadata is not None else {},
    )


def _declare(
    store: InMemoryScenarioStore,
    *,
    mode: Literal["global", "per_objective"] = "global",
    probability: float | None = 0.5,
    requirements: tuple[ObjectiveTargetRequirement, ...] = (),
    minimum_sample_count: int = 100,
    tie_tolerance: float = 0.05,
    hard_gates: bool = True,
    declared_at: datetime = DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> CampaignDecisionPolicy:
    """Declare one policy on the fixture campaign with the given draft."""
    return declare_campaign_decision_policy(
        store,
        tenant_id=TENANT,
        campaign_id="campaign-1",
        draft=_draft(
            mode=mode,
            probability=probability,
            requirements=requirements,
            minimum_sample_count=minimum_sample_count,
            tie_tolerance=tie_tolerance,
            hard_gates=hard_gates,
            declared_at=declared_at,
            metadata=metadata,
        ),
    )


def _stored_policy(store: InMemoryScenarioStore) -> CampaignDecisionPolicy:
    """The raw stored policy snapshot (private test seam)."""
    return store._campaign_decision_policies[(TENANT, "campaign-1")]


def _replace_stored(store: InMemoryScenarioStore, policy: CampaignDecisionPolicy) -> None:
    """Replace the stored policy record through the private test seam."""
    store._campaign_decision_policies[(TENANT, "campaign-1")] = policy


def _tamper_stored(store: InMemoryScenarioStore, update: dict[str, object]) -> None:
    """Tamper one stored policy field without rehashing; never repairs."""
    _replace_stored(store, _stored_policy(store).model_copy(update=update))


def _store_state(store: InMemoryScenarioStore) -> dict[str, object]:
    """A deep-copied snapshot of the complete store state for equality checks."""
    return copy.deepcopy(store.__dict__)


def _forge_profile(
    store: InMemoryScenarioStore,
    *,
    binding_updates: dict[str, dict[str, object]] | None = None,
    binding_order: tuple[int, ...] | None = None,
    scenario_content_hash_value: str | None = None,
    declared_at: datetime | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> ScenarioEvaluationProfile:
    """Replace the stored profile with a self-consistent, correctly rehashed forgery.

    Every tamper keeps the profile contract-valid and recomputes the
    deterministic identifier and content hash over the tampered payload,
    so the store revalidation and identity verification both pass and
    only the layer under test can catch the divergence.
    """
    stored = store.get_evaluation_profile(TENANT, "scenario-1")
    bindings = list(stored.bindings)
    if binding_updates is not None:
        for objective_id, updates in binding_updates.items():
            bindings = [
                binding.model_copy(update=updates)
                if binding.objective_id == objective_id
                else binding
                for binding in bindings
            ]
    if binding_order is not None:
        bindings = [bindings[position] for position in binding_order]
    forged = stored.model_copy(
        update={
            "bindings": tuple(bindings),
            "scenario_content_hash": (
                scenario_content_hash_value
                if scenario_content_hash_value is not None
                else stored.scenario_content_hash
            ),
            "declared_at": declared_at if declared_at is not None else stored.declared_at,
            "metadata": metadata if metadata is not None else stored.metadata,
        }
    )
    identifier = evaluation_profile_identifier(
        tenant_id=TENANT,
        scenario_id="scenario-1",
        scenario_content_hash_value=forged.scenario_content_hash,
    )
    # The content hash covers the identifier, so the identifier must be
    # fixed first and the digest computed over the identifier-bearing
    # payload.
    with_identifier = forged.model_copy(update={"identifier": identifier})
    digest = evaluation_profile_content_hash(with_identifier)
    final = with_identifier.model_copy(update={"content_hash": digest})
    store._evaluation_profiles[(TENANT, "scenario-1")] = final
    return final


class TestSuccessfulDeclaration:
    """Successful global/per-objective declarations and exact snapshots."""

    def test_global_mode_declaration_succeeds(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(store)
        assert policy.target_requirement_mode == "global"
        assert policy.minimum_target_achievement_probability == 0.5
        assert policy.objective_target_requirements == ()
        assert policy.minimum_sample_count == 100
        assert policy.tie_tolerance == 0.05
        assert policy.all_targeted_objectives_are_hard_gates is True
        assert policy.declared_at == DECLARED_AT
        assert policy.tail_alpha == 0.95
        assert policy.algorithm_identifier == "feasibility-pareto-minimax-regret-v1"

    def test_per_objective_mode_declaration_succeeds(self, store: InMemoryScenarioStore) -> None:
        requirements = _targeted_requirements()
        policy = _declare(store, mode="per_objective", probability=None, requirements=requirements)
        assert policy.target_requirement_mode == "per_objective"
        assert policy.minimum_target_achievement_probability is None
        assert policy.objective_target_requirements == requirements

    def test_global_zero_target_vacuous_declaration_succeeds(
        self, zero_target_store: InMemoryScenarioStore
    ) -> None:
        store = copy.deepcopy(zero_target_store)
        policy = _declare(store)
        assert policy.target_requirement_mode == "global"
        assert policy.objective_target_requirements == ()
        assert policy.minimum_target_achievement_probability == 0.5

    def test_exact_scenario_world_profile_references(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(store)
        scenario = store.get_scenario(TENANT, "scenario-1")
        world = store.get_world(TENANT, store.get_campaign(TENANT, "campaign-1").world_version_id)
        profile = store.get_evaluation_profile(TENANT, "scenario-1")
        assert policy.campaign_id == "campaign-1"
        assert policy.scenario_id == scenario.identifier
        assert policy.scenario_content_hash == scenario_content_hash(scenario)
        assert policy.world_version_id == world.identifier
        assert policy.world_content_hash == world.content_hash
        assert policy.evaluation_profile_id == profile.identifier
        assert policy.evaluation_profile_content_hash == profile.content_hash

    def test_fixed_tail_alpha_is_always_0_95(self, store: InMemoryScenarioStore) -> None:
        global_store = copy.deepcopy(store)
        per_objective_store = copy.deepcopy(store)
        assert _declare(global_store).tail_alpha == 0.95
        assert (
            _declare(
                per_objective_store,
                mode="per_objective",
                probability=None,
                requirements=_targeted_requirements(),
            ).tail_alpha
            == 0.95
        )

    def test_authoritative_weight_snapshots_in_exact_order(
        self, store: InMemoryScenarioStore
    ) -> None:
        policy = _declare(store)
        scenario = store.get_scenario(TENANT, "scenario-1")
        snapshot_ids = [snapshot.objective_id for snapshot in policy.objective_weight_snapshots]
        assert snapshot_ids == [objective.identifier for objective in scenario.objectives]
        assert snapshot_ids == ["obj-3", "obj-1", "obj-5", "obj-2", "obj-4"]
        assert tuple(snapshot.weight for snapshot in policy.objective_weight_snapshots) == tuple(
            objective.weight for objective in scenario.objectives
        )
        assert len(set(snapshot_ids)) == len(snapshot_ids)

    def test_non_lexicographic_objective_order_preserved(
        self, store: InMemoryScenarioStore
    ) -> None:
        policy = _declare(store)
        snapshot_ids = [snapshot.objective_id for snapshot in policy.objective_weight_snapshots]
        assert snapshot_ids != sorted(snapshot_ids)
        assert snapshot_ids == ["obj-3", "obj-1", "obj-5", "obj-2", "obj-4"]

    def test_all_zero_authoritative_weights_preserved(
        self, zero_weight_store: InMemoryScenarioStore
    ) -> None:
        store = copy.deepcopy(zero_weight_store)
        policy = _declare(store)
        assert tuple(snapshot.weight for snapshot in policy.objective_weight_snapshots) == (
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        )

    def test_deterministic_identifier_hash_and_declared_timestamp(
        self, store: InMemoryScenarioStore
    ) -> None:
        policy = _declare(store)
        assert policy.identifier == campaign_decision_policy_identifier(
            tenant_id=TENANT,
            campaign_id="campaign-1",
            scenario_id="scenario-1",
            world_version_id=store.get_campaign(TENANT, "campaign-1").world_version_id,
            evaluation_profile_id=store.get_evaluation_profile(TENANT, "scenario-1").identifier,
            schema_version=SCHEMA_VERSION,
        )
        assert policy.content_hash == campaign_decision_policy_content_hash(policy)
        assert policy.declared_at == DECLARED_AT

    def test_equivalent_independent_stores_produce_byte_identical_policies(
        self, fixture_store: InMemoryScenarioStore
    ) -> None:
        first_store = copy.deepcopy(fixture_store)
        second_store = copy.deepcopy(fixture_store)
        first = _declare(first_store)
        second = _declare(second_store)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.identifier == second.identifier
        assert first.content_hash == second.content_hash

    def test_caller_draft_and_metadata_not_mutated(self, store: InMemoryScenarioStore) -> None:
        metadata: dict[str, JsonValue] = {"note": "caller-owned", "nested": [1, 2.5, True]}
        requirements = _targeted_requirements()
        metadata_before = copy.deepcopy(metadata)
        requirements_before = copy.deepcopy(requirements)
        _declare(
            store,
            mode="per_objective",
            probability=None,
            requirements=requirements,
            metadata=metadata,
        )
        assert metadata == metadata_before
        assert requirements == requirements_before

    def test_no_operational_activity(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        assert store._operational_activity == {}
        assert store._activity_sequences == {}

    def test_exact_accepted_runtime_tuple(self, store: InMemoryScenarioStore) -> None:
        plans = store.get_run_plans(TENANT, "campaign-1")
        assert plans
        assert all(plan.runtime_version == "3.0.0" for plan in plans)
        _declare(store)


class TestTargetValidation:
    """Declared target-policy validation against the targeted objectives."""

    def test_probability_boundaries_zero_and_one_accepted(
        self, store: InMemoryScenarioStore
    ) -> None:
        zero_store = copy.deepcopy(store)
        one_store = copy.deepcopy(store)
        per_objective_store = copy.deepcopy(store)
        assert _declare(zero_store, probability=0.0).minimum_target_achievement_probability == 0.0
        assert _declare(one_store, probability=1.0).minimum_target_achievement_probability == 1.0
        policy = _declare(
            per_objective_store,
            mode="per_objective",
            probability=None,
            requirements=(
                _requirement("obj-3", probability=0.0),
                _requirement("obj-1", probability=1.0),
                _requirement("obj-5", probability=0.5),
            ),
        )
        assert policy.objective_target_requirements[0].minimum_target_achievement_probability == 0.0

    def test_exact_ordered_coverage_accepted(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(
            store,
            mode="per_objective",
            probability=None,
            requirements=_targeted_requirements(),
        )
        assert [r.objective_id for r in policy.objective_target_requirements] == list(TARGETED_IDS)

    def test_missing_target_rejected(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(_requirement("obj-3"), _requirement("obj-5")),
            )

    def test_duplicate_target_rejected(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(
                    _requirement("obj-3"),
                    _requirement("obj-3"),
                    _requirement("obj-1"),
                ),
            )

    def test_unknown_target_rejected(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(_requirement("obj-9"),),
            )

    def test_additional_target_rejected(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(*_targeted_requirements(), _requirement("obj-2")),
            )

    def test_optimization_only_target_requirement_rejected(
        self, store: InMemoryScenarioStore
    ) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(_requirement("obj-2"),),
            )

    def test_reordered_target_requirements_rejected(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(
                    _requirement("obj-1"),
                    _requirement("obj-3"),
                    _requirement("obj-5"),
                ),
            )

    def test_per_objective_zero_target_declaration_rejected(
        self, zero_target_store: InMemoryScenarioStore
    ) -> None:
        store = copy.deepcopy(zero_target_store)
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(_requirement("obj-3"),),
            )
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(store, mode="per_objective", probability=None, requirements=())

    def test_no_silent_sorting_or_repair(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(
                    _requirement("obj-5"),
                    _requirement("obj-3"),
                    _requirement("obj-1"),
                ),
            )
        with pytest.raises(CampaignDecisionPolicyNotFoundError):
            store.get_campaign_decision_policy(TENANT, "campaign-1")


class TestCampaignAndSourceVerification:
    """Campaign, runtime, world, scenario, and profile fail-closed matrix."""

    def test_unknown_campaign_raises_not_found(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignNotFoundError):
            declare_campaign_decision_policy(
                store, tenant_id=TENANT, campaign_id="campaign-unknown", draft=_draft()
            )

    def test_foreign_tenant_campaign_raises_not_found(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignNotFoundError):
            declare_campaign_decision_policy(
                store, tenant_id="foreign-tenant", campaign_id="campaign-1", draft=_draft()
            )

    @pytest.mark.parametrize(
        "state",
        [
            CampaignState.DRAFT,
            CampaignState.VALIDATED,
            CampaignState.COMPILED,
            CampaignState.RUNNING,
            CampaignState.FAILED,
            CampaignState.CANCELLED,
        ],
    )
    def test_non_complete_states_rejected(
        self, store: InMemoryScenarioStore, state: CampaignState
    ) -> None:
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": state})
        )
        with pytest.raises(CampaignNotCompleteError) as exc_info:
            _declare(store)
        assert exc_info.value.current_state == state.value

    def test_empty_run_plan_tuple_rejected(self, store: InMemoryScenarioStore) -> None:
        store._run_plans[(TENANT, "campaign-1")] = ()
        with pytest.raises(UnsupportedRuntimeVersionError):
            _declare(store)

    def test_mixed_runtime_tuple_rejected(self, store: InMemoryScenarioStore) -> None:
        plans = store.get_run_plans(TENANT, "campaign-1")
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plans[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            _declare(store)

    def test_unsupported_runtime_tuple_rejected(self, store: InMemoryScenarioStore) -> None:
        plans = store.get_run_plans(TENANT, "campaign-1")
        for plan in plans:
            inject_unsupported_recorded_runtime(
                store, campaign_id="campaign-1", plan=plan, unsupported_version="9.9.9"
            )
        with pytest.raises(UnsupportedRuntimeVersionError):
            _declare(store)

    def test_missing_world_rejected(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._worlds[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_missing_manifest_rejected(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        del store._manifests[(TENANT, campaign.world_version_id)]
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_corrupt_world_rejected(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        store._worlds[(TENANT, campaign.world_version_id)] = world.model_copy(
            update={"content_hash": "0" * 64}
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_campaign_world_scenario_mismatch_rejected(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        store._campaigns[(TENANT, "campaign-1")] = campaign.model_copy(
            update={"scenario_id": "scenario-other"}
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_missing_embedded_profile_rejected(
        self, no_profile_store: InMemoryScenarioStore
    ) -> None:
        store = copy.deepcopy(no_profile_store)
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            _declare(store)
        assert exc_info.value.reason == "embedded evaluation profile missing"

    def test_malformed_embedded_profile_rejected(self, store: InMemoryScenarioStore) -> None:
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        body = dict(world.world)
        body["evaluation_profile"] = {"not": "a profile"}
        store._worlds[(TENANT, campaign.world_version_id)] = world.model_copy(
            update={"world": body}
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_missing_stored_profile_rejected(self, store: InMemoryScenarioStore) -> None:
        del store._evaluation_profiles[(TENANT, "scenario-1")]
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            _declare(store)
        assert exc_info.value.reason == "stored evaluation profile missing"

    def test_corrupt_stored_profile_rejected(self, store: InMemoryScenarioStore) -> None:
        stored = store.get_evaluation_profile(TENANT, "scenario-1")
        store._evaluation_profiles[(TENANT, "scenario-1")] = stored.model_copy(
            update={"scenario_id": 42}
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    @pytest.mark.parametrize(
        ("binding_updates", "label"),
        [
            ({"obj-3": {"metric_id": "m-2"}}, "metric_id"),
            ({"obj-3": {"metric_unit": "other"}}, "metric_unit"),
            ({"obj-3": {"normalization_scale": 50.0}}, "normalization_scale"),
            ({"obj-5": {"reach_tolerance": 7.5}}, "reach_tolerance"),
            (None, "declared_at"),
            (None, "metadata"),
        ],
    )
    def test_stored_vs_embedded_profile_mismatch_family_rejected(
        self,
        store: InMemoryScenarioStore,
        binding_updates: dict[str, dict[str, object]] | None,
        label: str,
    ) -> None:
        if label == "declared_at":
            _forge_profile(store, declared_at=datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC))
        elif label == "metadata":
            _forge_profile(store, metadata={"forged": True})
        else:
            assert binding_updates is not None
            _forge_profile(store, binding_updates=binding_updates)
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            _declare(store)
        assert exc_info.value.reason == "stored and embedded evaluation profile mismatch"

    def test_profile_scenario_hash_mismatch_rejected(self, store: InMemoryScenarioStore) -> None:
        _forge_profile(store, scenario_content_hash_value="0" * 64)
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            _declare(store)
        assert exc_info.value.reason == "campaign profile snapshot mismatch"

    @pytest.mark.parametrize(
        ("binding_updates", "label"),
        [
            ({"obj-3": {"direction": "maximize"}}, "direction"),
            ({"obj-3": {"target": 80.0}}, "target"),
            ({"obj-3": {"weight": 2.5}}, "weight"),
        ],
    )
    def test_binding_snapshot_tamper_rejected(
        self,
        store: InMemoryScenarioStore,
        binding_updates: dict[str, dict[str, object]],
        label: str,
    ) -> None:
        _forge_profile(store, binding_updates=binding_updates)
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)

    def test_binding_order_tamper_rejected(self, store: InMemoryScenarioStore) -> None:
        _forge_profile(store, binding_order=(1, 0, 2, 3, 4))
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            _declare(store)


class TestPersistence:
    """One-policy-per-campaign atomicity, isolation, and surface closure."""

    def test_duplicate_declaration_rejected_and_original_unchanged(
        self, store: InMemoryScenarioStore
    ) -> None:
        original = _declare(store)
        with pytest.raises(CampaignDecisionPolicyAlreadyExistsError):
            _declare(store)
        again = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert again.model_dump(mode="json") == original.model_dump(mode="json")
        assert again.content_hash == original.content_hash

    def test_failed_declaration_writes_nothing(self, store: InMemoryScenarioStore) -> None:
        before = _store_state(store)
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(store, probability=-0.5)
        with pytest.raises(CampaignDecisionPolicyValidationError):
            _declare(
                store,
                mode="per_objective",
                probability=None,
                requirements=(_requirement("obj-1"), _requirement("obj-3"), _requirement("obj-5")),
            )
        with pytest.raises(CampaignDecisionPolicyNotFoundError):
            store.get_campaign_decision_policy(TENANT, "campaign-1")
        assert _store_state(store) == before

    def test_tenant_isolation(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        with pytest.raises(CampaignDecisionPolicyNotFoundError):
            get_verified_campaign_decision_policy(
                store, tenant_id="foreign-tenant", campaign_id="campaign-1"
            )

    def test_deep_copy_isolation(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(store)
        policy.metadata["tampered"] = True
        again = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert "tampered" not in again.metadata

    def test_returned_policy_mutation_cannot_affect_store(
        self, store: InMemoryScenarioStore
    ) -> None:
        policy = _declare(store)
        first = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert first.model_dump(mode="json") == policy.model_dump(mode="json")
        first.metadata["mutated"] = True
        second = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert "mutated" not in second.metadata

    def test_no_update_delete_replace_repair_surface(self) -> None:
        store = InMemoryScenarioStore()
        for name in (
            "update_campaign_decision_policy",
            "delete_campaign_decision_policy",
            "replace_campaign_decision_policy",
            "repair_campaign_decision_policy",
            "overwrite_campaign_decision_policy",
            "put_campaign_strategy_comparison",
            "put_campaign_decision_brief",
        ):
            assert not hasattr(store, name), name

    def test_no_comparison_or_brief_collection(self) -> None:
        store = InMemoryScenarioStore()
        assert not hasattr(store, "_campaign_strategy_comparisons")
        assert not hasattr(store, "_campaign_decision_briefs")

    def test_declaration_mutates_no_activity(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        assert store._operational_activity == {}
        assert store._activity_sequences == {}


class TestStoredPolicyTampering:
    """Every stored-policy tamper fails closed and is never repaired."""

    @pytest.mark.parametrize(
        ("update", "label"),
        [
            ({"tenant_id": "foreign-tenant"}, "tenant ownership"),
            ({"campaign_id": "campaign-other"}, "campaign identity"),
            ({"scenario_id": "scenario-other"}, "scenario identity"),
            ({"scenario_content_hash": "1" * 64}, "scenario hash"),
            ({"world_version_id": "world-other"}, "world identity"),
            ({"world_content_hash": "2" * 64}, "world hash"),
            ({"evaluation_profile_id": "profile-other"}, "profile identity"),
            ({"evaluation_profile_content_hash": "3" * 64}, "profile hash"),
            ({"identifier": "campaign-decision-policy-0123456789abcdef"}, "policy identifier"),
            ({"content_hash": "4" * 64}, "content hash"),
            ({"minimum_target_achievement_probability": 0.9}, "threshold"),
            ({"tie_tolerance": -1.0}, "tie tolerance"),
            ({"minimum_sample_count": 0}, "sample count"),
            ({"target_requirement_mode": "per_objective"}, "mode XOR"),
            ({"declared_at": datetime(2026, 2, 1, 12, 0, 0, tzinfo=UTC)}, "declared_at"),
            ({"metadata": {"forged": 1}}, "metadata"),
        ],
    )
    def test_identity_hash_and_rule_tampers_rejected(
        self, store: InMemoryScenarioStore, update: dict[str, object], label: str
    ) -> None:
        _declare(store)
        _tamper_stored(store, update)
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")
        # The stored tampered record is never repaired: the store read
        # still rejects it on every subsequent attempt.
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            store.get_campaign_decision_policy(TENANT, "campaign-1")

    def test_weight_snapshot_tamper_rejected(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(store)
        snapshots = policy.objective_weight_snapshots
        tampered = snapshots[0].model_copy(update={"weight": 99.0})
        _replace_stored(
            store,
            policy.model_copy(update={"objective_weight_snapshots": (tampered, *snapshots[1:])}),
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_tail_alpha_tamper_rejected(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        _tamper_stored(store, {"tail_alpha": 0.9})
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_nested_validator_bypass_rejected(self, store: InMemoryScenarioStore) -> None:
        policy = _declare(store)
        bad_snapshot = ObjectiveWeightSnapshot.model_construct(objective_id="obj-3", weight=-1.0)
        _replace_stored(
            store,
            policy.model_copy(
                update={
                    "objective_weight_snapshots": (
                        bad_snapshot,
                        *policy.objective_weight_snapshots[1:],
                    )
                }
            ),
        )
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_malformed_python_mode_data_rejected(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        _tamper_stored(store, {"minimum_sample_count": "not-an-int"})
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_non_policy_object_rejected(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        store._campaign_decision_policies[(TENANT, "campaign-1")] = "not a policy"  # type: ignore[assignment]
        with pytest.raises(CampaignDecisionPolicyIntegrityError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_no_raw_validation_diagnostic_escapes(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        _tamper_stored(store, {"metadata": {"bad": float("nan")}})
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")
        assert type(exc_info.value) is CampaignDecisionPolicyIntegrityError
        assert str(exc_info.value) == (
            "Stored campaign decision policy failed integrity verification and was rejected"
        )

    def test_service_verification_pass_failures_wrapped(
        self, store: InMemoryScenarioStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(store)

        def _explode(policy: object) -> None:
            raise ValueError("raw pydantic-style diagnostic that must never escape")

        monkeypatch.setattr(service_module, "_strictly_revalidate_policy", _explode)
        with pytest.raises(CampaignDecisionPolicyIntegrityError) as exc_info:
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason == "stored campaign decision policy verification failed"
        assert "pydantic-style" not in str(exc_info.value)


class TestVerifiedRetrieval:
    """Verified read behavior and independence from campaign lifecycle."""

    def test_retrieval_returns_detached_deep_copy(self, store: InMemoryScenarioStore) -> None:
        declared = _declare(store)
        retrieved = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert retrieved.model_dump(mode="json") == declared.model_dump(mode="json")
        assert retrieved is not declared
        retrieved.metadata["mutated"] = True
        again = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert "mutated" not in again.metadata

    def test_absent_policy_raises_not_found(self, store: InMemoryScenarioStore) -> None:
        with pytest.raises(CampaignDecisionPolicyNotFoundError):
            get_verified_campaign_decision_policy(store, tenant_id=TENANT, campaign_id="campaign-1")

    def test_foreign_tenant_raises_not_found(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        with pytest.raises(CampaignDecisionPolicyNotFoundError):
            get_verified_campaign_decision_policy(
                store, tenant_id="foreign-tenant", campaign_id="campaign-1"
            )

    def test_retrieval_does_not_require_complete(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT, "campaign-1", status.model_copy(update={"state": CampaignState.DRAFT})
        )
        policy = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert policy.campaign_id == "campaign-1"

    def test_repeated_reads_byte_identical(self, store: InMemoryScenarioStore) -> None:
        _declare(store)
        first = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_campaign_decision_policy(
            store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestApiErrorMapping:
    """Registered-handler mapping of the four typed policy errors."""

    @pytest.fixture()
    def policy_app(self) -> FastAPI:
        app = FastAPI()
        register_error_handlers(app)

        @app.get("/_test/raise/{kind}")
        def _raise(kind: str) -> None:
            if kind == "not_found":
                raise CampaignDecisionPolicyNotFoundError(TENANT, "campaign-1")
            if kind == "exists":
                raise CampaignDecisionPolicyAlreadyExistsError(TENANT, "campaign-1")
            if kind == "validation":
                raise CampaignDecisionPolicyValidationError(
                    TENANT, "campaign-1", reason="secret internal validation reason"
                )
            raise CampaignDecisionPolicyIntegrityError(
                TENANT, "campaign-1", reason="secret internal integrity reason"
            )

        return app

    @pytest.mark.parametrize(
        ("kind", "status", "code"),
        [
            ("not_found", 404, ErrorCode.NOT_FOUND),
            ("exists", 409, ErrorCode.CONFLICT),
            ("validation", 422, ErrorCode.VALIDATION_ERROR),
            ("integrity", 409, ErrorCode.INTEGRITY_ERROR),
        ],
    )
    def test_exact_status_and_error_code(
        self, policy_app: FastAPI, kind: str, status: int, code: ErrorCode
    ) -> None:
        with TestClient(policy_app) as client:
            response = client.get(f"/_test/raise/{kind}")
        assert response.status_code == status
        body = response.json()
        assert body["code"] == code.value
        assert body["message"]
        assert body["details"] == []

    @pytest.mark.parametrize(
        ("kind", "message"),
        [
            ("not_found", "Campaign decision policy not found"),
            ("exists", "Campaign decision policy already exists for this campaign"),
            ("validation", "Campaign decision policy declaration is invalid"),
            (
                "integrity",
                "Stored campaign decision policy failed integrity verification and was rejected",
            ),
        ],
    )
    def test_generic_non_leaking_messages(
        self, policy_app: FastAPI, kind: str, message: str
    ) -> None:
        with TestClient(policy_app) as client:
            response = client.get(f"/_test/raise/{kind}")
        assert response.json()["message"] == message

    @pytest.mark.parametrize("kind", ["validation", "integrity"])
    def test_internal_reason_absent_from_response(self, policy_app: FastAPI, kind: str) -> None:
        with TestClient(policy_app) as client:
            response = client.get(f"/_test/raise/{kind}")
        body_text = json.dumps(response.json())
        assert "secret internal" not in body_text
        assert "reason" not in response.json()


class TestServiceBoundary:
    """The service module stays pure and decision-surface-free."""

    def test_service_module_boundary_scan(self) -> None:
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
        assert "random" not in imported
        chains: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                chains.add(".".join(reversed(_attribute_parts(node.func))))
        assert "datetime.now" not in chains
        put_calls = {
            chain.rsplit(".", 1)[-1]
            for chain in chains
            if chain.rsplit(".", 1)[-1].startswith("put_")
        }
        assert put_calls == {"put_campaign_decision_policy"}
        assert "CampaignStrategyComparison" not in source
        assert "CampaignDecisionBrief" not in source
        assert "build_campaign_strategy_comparison" not in source
        assert "build_campaign_decision_brief" not in source


def _attribute_parts(attribute: ast.Attribute) -> list[str]:
    """The dotted parts of one attribute chain (helper for the boundary scan)."""
    parts: list[str] = []
    target: ast.expr = attribute
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    return parts


class TestDraftBoundary:
    """The direct application draft boundary rejects silent defaults."""

    def test_required_decision_rules_have_no_defaults(self) -> None:
        with pytest.raises(TypeError):
            CampaignDecisionPolicyDeclarationDraft(  # type: ignore[call-arg]
                target_requirement_mode="global"
            )
        with pytest.raises(TypeError):
            CampaignDecisionPolicyDeclarationDraft(  # type: ignore[call-arg]
                target_requirement_mode="global",
                declared_at=DECLARED_AT,
                minimum_sample_count=100,
                all_targeted_objectives_are_hard_gates=True,
            )

    def test_mutable_requirements_list_rejected(self, store: InMemoryScenarioStore) -> None:
        bad_draft = CampaignDecisionPolicyDeclarationDraft(
            target_requirement_mode="per_objective",
            minimum_sample_count=100,
            tie_tolerance=0.05,
            all_targeted_objectives_are_hard_gates=True,
            declared_at=DECLARED_AT,
            objective_target_requirements=[  # type: ignore[arg-type]
                _requirement("obj-3"),
                _requirement("obj-1"),
                _requirement("obj-5"),
            ],
        )
        with pytest.raises(CampaignDecisionPolicyValidationError):
            declare_campaign_decision_policy(
                store,
                tenant_id=TENANT,
                campaign_id="campaign-1",
                draft=bad_draft,
            )

    def test_exact_bool_required_at_draft_boundary(self, store: InMemoryScenarioStore) -> None:
        for bad_gates in (1, 0, 1.0, 0.0, "true", "false", None, [True]):
            with pytest.raises(CampaignDecisionPolicyValidationError):
                declare_campaign_decision_policy(
                    store,
                    tenant_id=TENANT,
                    campaign_id="campaign-1",
                    draft=_draft(hard_gates=bad_gates),  # type: ignore[arg-type]
                )

    def test_non_json_metadata_rejected_at_draft_boundary(
        self, store: InMemoryScenarioStore
    ) -> None:
        import decimal

        for bad_metadata in (
            {"bad": decimal.Decimal("1.5")},
            {"bad": (1, 2)},
            {"bad": {1, 2}},
            {1: "bad-key"},
            {"bad": {"nested": float("nan")}},
            {"bad": float("inf")},
        ):
            with pytest.raises(CampaignDecisionPolicyValidationError):
                declare_campaign_decision_policy(
                    store,
                    tenant_id=TENANT,
                    campaign_id="campaign-1",
                    draft=_draft(metadata=bad_metadata),  # type: ignore[arg-type]
                )

    def test_nested_json_metadata_accepted(self, store: InMemoryScenarioStore) -> None:
        metadata: dict[str, JsonValue] = {
            "string": "value",
            "int": 7,
            "float": 2.5,
            "bool": True,
            "none": None,
            "list": [1, "two", 3.0, False, None],
            "nested": {"a": {"b": [1, 2]}},
        }
        policy = _declare(store, metadata=metadata)
        assert policy.metadata == metadata
