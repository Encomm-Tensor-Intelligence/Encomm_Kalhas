"""Phase 15 service tests: immutable strategy-bound trajectory plans.

Proves the planning service is deterministic, authoritative, atomic, and
read-only with respect to every other store collection: LEGION proposes,
KALHAS verifies and binds, drafts are re-validated even when built
through validator-bypassing paths, the full plan matrix is stored only
after every draft is valid, and stored plans are re-verified before any
service read. Also proves the store's snapshot isolation for the new
collection and that hostile adapter mutation cannot corrupt storage or
authoritative plan inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    CampaignNotPlanningStateError,
    InvalidTrajectoryDraftError,
    RunInputIntegrityError,
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansAlreadyPreparedError,
    TrajectoryPlansNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.domain_state_model_service import (
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    get_strategy_trajectory_plans,
    prepare_strategy_trajectory_plans,
    strategy_candidate_content_hash,
    trajectory_plan_content_hash,
    trajectory_plan_identifier,
    trajectory_request_identifier,
)
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.strategy import StrategyRequest
from kalhas.contracts.v1.trajectory import (
    MAX_TRAJECTORY_PLAN_TRANSITIONS,
    StrategyTrajectoryPlan,
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
    StrategyTrajectoryTransitionReference,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from pydantic import ValidationError

from tests.phase4_helpers import (
    NOW,
    TENANT,
    build_scenario,
    build_store,
    execute,
    prepare,
    start,
)

OTHER_TENANT = "tenant-other"
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

SM_1_IDENTIFIER = state_model_identifier(
    scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="sm-1"
)
SM_2_IDENTIFIER = state_model_identifier(
    scenario_id="scenario-1", manifest_id="manifest-2", state_model_id="sm-2"
)
SM_3_IDENTIFIER = state_model_identifier(
    scenario_id="scenario-1", manifest_id="manifest-3", state_model_id="sm-3"
)


def _request_stub() -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id=TENANT,
        scenario_id="scenario-1",
        required_observations=[],
        requested_at=NOW,
    )


def _build_model(
    *,
    state_model_id: str,
    manifest_id: str,
    field: str,
    initial_value: str,
) -> DomainStateModel:
    model = DomainStateModel(
        identifier=state_model_identifier(
            scenario_id="scenario-1",
            manifest_id=manifest_id,
            state_model_id=state_model_id,
        ),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id=f"binding-{state_model_id}",
        manifest_id=manifest_id,
        pack_id=f"pack-{state_model_id}",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id=state_model_id,
        state_fields=(
            DomainStateFieldDefinition(
                identifier=field,
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value=initial_value,
            ),
        ),
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return model.model_copy(update={"content_hash": state_model_content_hash(model)})


def _build_transition(
    model: DomainStateModel,
    *,
    transition_id: str,
    guard_value: str,
    target_value: str,
) -> DomainStateTransition:
    field = model.state_fields[0].identifier
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=model.scenario_id,
            manifest_id=model.manifest_id,
            state_model_id=model.state_model_id,
            transition_id=transition_id,
        ),
        tenant_id=model.tenant_id,
        scenario_id=model.scenario_id,
        binding_id=model.binding_id,
        manifest_id=model.manifest_id,
        pack_id=model.pack_id,
        pack_version=model.pack_version,
        manifest_content_hash=model.manifest_content_hash,
        state_model_id=model.state_model_id,
        state_model_content_hash=model.content_hash,
        transition_id=transition_id,
        description="Declared state change",
        guard_values={field: guard_value},
        target_values={field: target_value},
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


def _rich_store() -> tuple[InMemoryScenarioStore, str]:
    """A prepared campaign whose world embeds two transition-capable models.

    Model sm-1 (manifest-1, field ``status``) carries transitions t-1a and
    t-1b; model sm-2 (manifest-2, field ``mode``) carries t-2a and t-2b.
    The campaign is prepared with the default five-strategy fake, so the
    full plan matrix is 5 strategies x 2 models = 10 plans.
    """
    store = InMemoryScenarioStore()
    scenario = build_scenario()
    store.put_scenario(scenario)
    sm_1 = _build_model(
        state_model_id="sm-1",
        manifest_id="manifest-1",
        field="status",
        initial_value="idle",
    )
    sm_2 = _build_model(
        state_model_id="sm-2",
        manifest_id="manifest-2",
        field="mode",
        initial_value="off",
    )
    transitions = (
        _build_transition(sm_1, transition_id="t-1a", guard_value="idle", target_value="active"),
        _build_transition(sm_1, transition_id="t-1b", guard_value="active", target_value="idle"),
        _build_transition(sm_2, transition_id="t-2a", guard_value="off", target_value="on"),
        _build_transition(sm_2, transition_id="t-2b", guard_value="on", target_value="off"),
    )
    compiled = compile_world(
        scenario,
        state_models=(sm_1, sm_2),
        transitions=transitions,
    )
    store.put_world(compiled.version, compiled.manifest)
    prepare(store, compiled.version.identifier, runtime_version="2.0.0")
    return store, compiled.version.identifier


def _canonical_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=tuple(
            transition.identifier for transition in request.available_transitions
        ),
    )


class _ScriptedLegion(MockLegionAdapter):
    """Deterministic scripted adapter; falls back to the canonical proposal.

    Scripts are applied per request in order and wrap around, so a single
    script applies to every request and a script list can target specific
    request positions (for example, an invalid draft on the last request).
    """

    def __init__(
        self,
        scripts: Sequence[Callable[[StrategyTrajectoryPlanRequest], StrategyTrajectoryPlanDraft]]
        | None = None,
    ) -> None:
        self.scripts = scripts
        self.requests: list[StrategyTrajectoryPlanRequest] = []

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.requests.append(request)
        if self.scripts is None:
            return _canonical_script(request)
        position = len(self.requests) - 1
        return self.scripts[position % len(self.scripts)](request)


class _HostileLegion(MockLegionAdapter):
    """Mutates every nested mutable value inside the detached request."""

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        # Mutate every mutable nested value inside the detached request
        # (top-level fields are frozen, so nested dicts/lists are the only
        # attack surface).
        request.strategy_candidate.metadata["hacked"] = True
        request.state_model.metadata["hacked"] = True
        request.available_transitions[0].target_values["status"] = "pwned"
        return _canonical_script(request)


def _reversed_available_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose the available transitions in reverse order."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=tuple(
            reversed([transition.identifier for transition in request.available_transitions])
        ),
    )


def _repeated_first_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose the first available transition twice."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(
            request.available_transitions[0].identifier,
            request.available_transitions[0].identifier,
        ),
    )


def _script_second_first_second(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose the sequence (second, first, second) from the available catalog."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(
            request.available_transitions[1].identifier,
            request.available_transitions[0].identifier,
            request.available_transitions[1].identifier,
        ),
    )


def _script_second_second_first(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose the sequence (second, second, first) from the available catalog."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(
            request.available_transitions[1].identifier,
            request.available_transitions[1].identifier,
            request.available_transitions[0].identifier,
        ),
    )


def _wrong_request_id_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose a valid sequence under a forged request identifier."""
    return StrategyTrajectoryPlanDraft(
        request_id="trajectory-request-ffffffffffffffff",
        ordered_transition_identifiers=(request.available_transitions[0].identifier,),
    )


def _unknown_identifier_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose a transition identifier that is not in the available catalog."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=("transition-ffffffffffffffff",),
    )


def _foreign_transition_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose the transition of another embedded state model."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(
            transition_identifier(
                scenario_id="scenario-1",
                manifest_id="manifest-2",
                state_model_id="sm-2",
                transition_id="t-2a",
            ),
        ),
    )


def _empty_bypassed_draft_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Return a validator-bypassing draft with an empty sequence."""
    return StrategyTrajectoryPlanDraft.model_construct(
        request_id=request.identifier, ordered_transition_identifiers=()
    )


def _oversized_bypassed_draft_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Return a validator-bypassing draft with a 1001-identifier sequence."""
    return StrategyTrajectoryPlanDraft.model_construct(
        request_id=request.identifier,
        ordered_transition_identifiers=(request.available_transitions[0].identifier,)
        * (MAX_TRAJECTORY_PLAN_TRANSITIONS + 1),
    )


def _single_reference_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose exactly one transition - the valid lower bound."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(request.available_transitions[0].identifier,),
    )


def _thousand_references_script(
    request: StrategyTrajectoryPlanRequest,
) -> StrategyTrajectoryPlanDraft:
    """Propose exactly 1000 repetitions - the valid upper bound."""
    return StrategyTrajectoryPlanDraft(
        request_id=request.identifier,
        ordered_transition_identifiers=(request.available_transitions[0].identifier,)
        * MAX_TRAJECTORY_PLAN_TRANSITIONS,
    )


class TestDeterminism:
    def test_identical_inputs_produce_identical_identifiers_and_hashes(self) -> None:
        store_a, world_id_a = _rich_store()
        store_b, world_id_b = _rich_store()
        plans_a = prepare_strategy_trajectory_plans(
            store=store_a, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        plans_b = prepare_strategy_trajectory_plans(
            store=store_b, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert world_id_a == world_id_b
        assert [plan.model_dump(mode="json") for plan in plans_a] == [
            plan.model_dump(mode="json") for plan in plans_b
        ]
        assert [plan.identifier for plan in plans_a] == [plan.identifier for plan in plans_b]
        assert [plan.content_hash for plan in plans_a] == [plan.content_hash for plan in plans_b]

    def test_identifiers_are_hash_derived_with_distinct_prefixes(self) -> None:
        store, world_id = _rich_store()
        request_id = trajectory_request_identifier(
            campaign_id="campaign-1",
            world_version_id=world_id,
            strategy_candidate_id="mock-baseline",
            state_model_identifier="state-model-1",
        )
        plan_id = trajectory_plan_identifier(
            campaign_id="campaign-1",
            world_version_id=world_id,
            strategy_candidate_id="mock-baseline",
            state_model_identifier="state-model-1",
        )
        assert request_id.startswith("trajectory-request-")
        assert plan_id.startswith("trajectory-plan-")
        assert request_id != plan_id
        assert len(request_id) == len("trajectory-request-") + 16
        assert len(plan_id) == len("trajectory-plan-") + 16

    def test_changed_sequence_order_changes_plan_hash(self) -> None:
        store_a, _ = _rich_store()
        store_b, _ = _rich_store()
        plans_a = prepare_strategy_trajectory_plans(
            store=store_a, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        plans_b = prepare_strategy_trajectory_plans(
            store=store_b,
            legion=_ScriptedLegion(scripts=[_reversed_available_script]),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        assert plans_a[0].content_hash != plans_b[0].content_hash
        assert plans_a[0].transition_references[0].transition_id == "t-1a"
        assert plans_b[0].transition_references[0].transition_id == "t-1b"

    def test_repeated_references_affect_the_hash(self) -> None:
        store_a, _ = _rich_store()
        store_b, _ = _rich_store()
        plans_a = prepare_strategy_trajectory_plans(
            store=store_a, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        plans_b = prepare_strategy_trajectory_plans(
            store=store_b,
            legion=_ScriptedLegion(scripts=[_repeated_first_script]),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        assert len(plans_b[0].transition_references) == 2
        assert plans_a[0].content_hash != plans_b[0].content_hash

    def test_strategy_hash_ignores_mapping_insertion_order(self) -> None:
        candidate = MockLegionAdapter().request_strategies(_request_stub())[0]
        metadata_a: dict[str, JsonValue] = {"x": 1, "y": {"p": 1, "q": 2}}
        metadata_b: dict[str, JsonValue] = {"y": {"q": 2, "p": 1}, "x": 1}
        candidate_a = candidate.model_copy(update={"metadata": metadata_a})
        candidate_b = candidate.model_copy(update={"metadata": metadata_b})
        # Same canonical content, different insertion order: the canonical
        # serialization sorts keys, so the hashes must be identical.
        assert strategy_candidate_content_hash(candidate_a) == strategy_candidate_content_hash(
            candidate_b
        )

    def test_planned_at_is_the_recorded_campaign_created_at(self) -> None:
        store, _ = _rich_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert all(plan.planned_at == campaign.created_at for plan in plans)
        assert all(plan.planned_at == NOW for plan in plans)


class TestPlanningBehavior:
    def test_five_strategies_times_two_models_produces_ten_ordered_plans(self) -> None:
        store, _ = _rich_store()
        legion = _ScriptedLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(plans) == 10
        campaign = store.get_campaign(TENANT, "campaign-1")
        expected_strategies = [
            candidate_id for candidate_id in campaign.strategy_candidate_ids for _ in range(2)
        ]
        assert [plan.strategy_candidate_id for plan in plans] == expected_strategies
        assert [plan.state_model_identifier for plan in plans] == [
            SM_1_IDENTIFIER,
            SM_2_IDENTIFIER,
        ] * 5
        assert [plan.world_version_id for plan in plans] == [campaign.world_version_id] * 10
        # The mock proposes the canonical available order, preserved exactly.
        assert [r.transition_id for r in plans[0].transition_references] == ["t-1a", "t-1b"]
        assert [r.transition_id for r in plans[1].transition_references] == ["t-2a", "t-2b"]

    def test_requests_follow_strategy_then_model_order(self) -> None:
        store, _ = _rich_store()
        legion = _ScriptedLegion()
        prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert len(legion.requests) == 10
        assert [
            (request.strategy_candidate.identifier, request.state_model.state_model_id)
            for request in legion.requests
        ] == [
            (candidate_id, model_id)
            for candidate_id in campaign.strategy_candidate_ids
            for model_id in ("sm-1", "sm-2")
        ]

    def test_exact_legion_sequence_preserved_with_repetitions(self) -> None:
        store, _ = _rich_store()
        legion = _ScriptedLegion(scripts=[_script_second_first_second])
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        references = plans[0].transition_references
        assert [r.transition_id for r in references] == ["t-1b", "t-1a", "t-1b"]
        assert [r.sequence_position for r in references] == [0, 1, 2]
        assert references[0].transition_identifier == references[2].transition_identifier
        assert references[0].transition_content_hash == references[2].transition_content_hash

    def test_kalhas_never_selects_reorders_or_deduplicates(self) -> None:
        store, _ = _rich_store()
        legion = _ScriptedLegion(scripts=[_script_second_second_first])
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [r.transition_id for r in plans[0].transition_references] == [
            "t-1b",
            "t-1b",
            "t-1a",
        ]

    def test_only_compiled_world_snapshots_are_used(self) -> None:
        store, world_id = _rich_store()
        # A declaration added to the live registry after compilation must
        # never influence planning for the existing world.
        late_model = _build_model(
            state_model_id="sm-3",
            manifest_id="manifest-3",
            field="level",
            initial_value="low",
        )
        late_transition = _build_transition(
            late_model, transition_id="t-3a", guard_value="low", target_value="high"
        )
        store.put_domain_state_model(late_model)
        store.put_domain_state_transition(late_transition)
        legion = _ScriptedLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(plans) == 10
        assert SM_3_IDENTIFIER not in {plan.state_model_identifier for plan in plans}
        assert all(len(request.available_transitions) == 2 for request in legion.requests)

    def test_model_without_transitions_causes_no_request(self) -> None:
        store = InMemoryScenarioStore()
        scenario = build_scenario()
        store.put_scenario(scenario)
        sm_1 = _build_model(
            state_model_id="sm-1",
            manifest_id="manifest-1",
            field="status",
            initial_value="idle",
        )
        sm_2 = _build_model(
            state_model_id="sm-2",
            manifest_id="manifest-2",
            field="mode",
            initial_value="off",
        )
        compiled = compile_world(
            scenario,
            state_models=(sm_1, sm_2),
            transitions=(
                _build_transition(
                    sm_1, transition_id="t-1a", guard_value="idle", target_value="active"
                ),
            ),
        )
        store.put_world(compiled.version, compiled.manifest)
        prepare(store, compiled.version.identifier, runtime_version="2.0.0")
        legion = _ScriptedLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(legion.requests) == 5  # one per strategy, sm-2 is ignored
        assert len(plans) == 5
        assert {plan.state_model_identifier for plan in plans} == {SM_1_IDENTIFIER}

    def test_world_without_capable_models_records_empty_tuple(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id, runtime_version="2.0.0")
        legion = _ScriptedLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert plans == ()
        assert legion.requests == []
        assert (
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
            == ()
        )

    def test_no_campaign_or_run_lifecycle_records_change(self) -> None:
        store, _ = _rich_store()
        status_before = store.get_campaign_status(TENANT, "campaign-1").model_dump(mode="json")
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        plans_before = [plan.model_dump(mode="json") for plan in run_plans]
        run_statuses_before = [
            store.get_run_status(TENANT, run_identifier(plan)).model_dump(mode="json")
            for plan in run_plans
        ]
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        status_after = store.get_campaign_status(TENANT, "campaign-1").model_dump(mode="json")
        assert status_after == status_before
        assert [
            plan.model_dump(mode="json") for plan in store.get_run_plans(TENANT, "campaign-1")
        ] == plans_before
        assert [
            store.get_run_status(TENANT, run_identifier(plan)).model_dump(mode="json")
            for plan in store.get_run_plans(TENANT, "campaign-1")
        ] == run_statuses_before
        assert store._run_events == {}
        assert store._replay_manifests == {}
        assert store._input_integrity_manifests == {}

    def test_service_getter_returns_verified_plans(self) -> None:
        store, _ = _rich_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        retrieved = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [plan.model_dump(mode="json") for plan in retrieved] == [
            plan.model_dump(mode="json") for plan in plans
        ]


class TestFailureAndAtomicity:
    def test_corrupted_world_rejected_before_legion(self) -> None:
        store, world_id = _rich_store()
        scenario = store._worlds[(TENANT, world_id)].world["scenario"]
        assert isinstance(scenario, dict)
        scenario["name"] = "Tampered"
        legion = _ScriptedLegion()
        with pytest.raises(WorldSnapshotIntegrityError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.requests == []

    def test_missing_manifest_rejected_before_legion(self) -> None:
        store, world_id = _rich_store()
        del store._manifests[(TENANT, world_id)]
        legion = _ScriptedLegion()
        with pytest.raises(WorldSnapshotIntegrityError) as exc_info:
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.reason is not None
        assert "world manifest missing" in exc_info.value.reason
        assert legion.requests == []

    def test_corrupted_strategy_candidate_rejected_before_legion(self) -> None:
        store, _ = _rich_store()
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        tampered = candidates[0].model_copy(
            update={"policy": candidates[0].policy.model_copy(update={"summary": "Tampered"})}
        )
        store._strategy_candidates[(TENANT, "campaign-1")] = (tampered, *candidates[1:])
        legion = _ScriptedLegion()
        with pytest.raises(RunInputIntegrityError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.requests == []

    def test_corrupted_run_status_rejected_before_legion(self) -> None:
        store, _ = _rich_store()
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        status = store.get_run_status(TENANT, run_id)
        store._run_statuses[(TENANT, run_id)] = status.model_copy(update={"input_hash": "f" * 64})
        legion = _ScriptedLegion()
        with pytest.raises(RunInputIntegrityError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.requests == []

    def test_corrupted_run_plan_rejected_before_legion(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered, *plans[1:])
        legion = _ScriptedLegion()
        with pytest.raises(RunInputIntegrityError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.requests == []

    def test_wrong_draft_request_id_rejected(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=[_wrong_request_id_script]),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_unknown_transition_identifier_rejected(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=[_unknown_identifier_script]),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )

    def test_transition_from_another_model_rejected(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=[_foreign_transition_script]),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )

    def test_validator_bypassed_empty_draft_rejected(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=[_empty_bypassed_draft_script]),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )

    def test_validator_bypassed_oversized_draft_rejected(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=[_oversized_bypassed_draft_script]),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )

    def test_invalid_later_draft_stores_zero_plans(self) -> None:
        store, _ = _rich_store()
        scripts = [_canonical_script] * 9
        scripts.append(_empty_bypassed_draft_script)
        with pytest.raises(InvalidTrajectoryDraftError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=scripts),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_legion_exception_stores_zero_plans(self) -> None:
        store, _ = _rich_store()

        def exploding(request: StrategyTrajectoryPlanRequest) -> StrategyTrajectoryPlanDraft:
            raise RuntimeError("adapter failure")

        scripts = [_canonical_script, _canonical_script, exploding]
        with pytest.raises(RuntimeError):
            prepare_strategy_trajectory_plans(
                store=store,
                legion=_ScriptedLegion(scripts=scripts),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")

    def test_duplicate_preparation_rejected_without_overwrite(self) -> None:
        store, _ = _rich_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        with pytest.raises(TrajectoryPlansAlreadyPreparedError):
            prepare_strategy_trajectory_plans(
                store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert [
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        ] == [plan.model_dump(mode="json") for plan in plans]

    def test_running_and_complete_campaigns_rejected(self) -> None:
        store, _ = _rich_store()
        # Prepare the plans while COMPILED so the campaign can later
        # execute (a trajectory-runtime campaign executes only with its
        # prepared plan collection); the preparation gate itself is the
        # behavior under test.
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        start(store)
        with pytest.raises(CampaignNotPlanningStateError) as exc_info:
            prepare_strategy_trajectory_plans(
                store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.current_state == "running"
        execute(store)
        with pytest.raises(CampaignNotPlanningStateError) as exc_info:
            prepare_strategy_trajectory_plans(
                store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert exc_info.value.current_state == "complete"

    def test_cross_tenant_reads_look_missing(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        with pytest.raises(TrajectoryPlansNotFoundError):
            get_strategy_trajectory_plans(
                store=store, tenant_id=OTHER_TENANT, campaign_id="campaign-1"
            )

    def test_store_rejects_foreign_plan_preflight(self) -> None:
        store, _ = _rich_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        foreign = plans[0].model_copy(update={"tenant_id": OTHER_TENANT})
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            store.put_strategy_trajectory_plans(OTHER_TENANT, "campaign-other", (foreign,))


class TestStoredPlanIntegrity:
    def test_stored_plan_content_hash_tampering_rejected(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        tampered = stored[0].model_copy(update={"content_hash": "f" * 64})
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan content hash mismatch" in exc_info.value.reason

    def test_stored_plan_reference_tampering_rejected(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        plan = stored[0]
        reference = plan.transition_references[0].model_copy(
            update={"transition_content_hash": "e" * 64}
        )
        tampered = plan.model_copy(
            update={"transition_references": (reference, *plan.transition_references[1:])}
        )
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan transition content hash mismatch" in exc_info.value.reason

    def test_stored_plan_reordering_rejected(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        plan = stored[0]
        reversed_refs = tuple(reversed(plan.transition_references))
        tampered = plan.model_copy(update={"transition_references": reversed_refs})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan sequence positions are not contiguous" in exc_info.value.reason

    def test_stored_plan_strategy_tampering_rejected(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        plan = stored[0]
        tampered = plan.model_copy(update={"strategy_content_hash": "e" * 64})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan strategy content hash mismatch" in exc_info.value.reason

    def test_public_error_text_leaks_no_hashes_or_values(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        stored = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        tampered = stored[0].model_copy(update={"strategy_content_hash": "e" * 64})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        message = str(exc_info.value)
        assert "e" * 64 not in message
        assert HASH_64 not in message
        # The reason is internal-only: it names the violated rule and is
        # never part of the generic public message.
        assert exc_info.value.reason == "trajectory plan strategy content hash mismatch"
        assert "trajectory plan strategy content hash mismatch" not in message
        assert "rejected" in message


class TestSnapshotIsolation:
    def test_hostile_mock_mutation_cannot_corrupt_storage_or_plans(self) -> None:
        store, _ = _rich_store()
        pristine_candidates = [
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, "campaign-1")
        ]
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=_HostileLegion(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        # The stored strategy records are untouched.
        assert [
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, "campaign-1")
        ] == pristine_candidates
        # The authoritative plans resolve the pristine stored identities
        # and hashes, not the mutated request copies: the service getter
        # re-verifies every plan against the verified world catalog and
        # stored candidates, and it passes.
        retrieved = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [plan.model_dump(mode="json") for plan in retrieved] == [
            plan.model_dump(mode="json") for plan in plans
        ]

    def test_mutating_original_plans_after_put_never_changes_storage(self) -> None:
        store, _ = _rich_store()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        pristine = [plan.model_dump(mode="json") for plan in plans]
        # Plans are fully frozen: top-level assignment is refused and
        # there is no mutable nested data to walk into.
        with pytest.raises(ValidationError):
            plans[0].planned_at = NOW  # frozen by contract
        assert [
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        ] == pristine

    def test_mutating_retrieved_plans_never_changes_storage(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        retrieved = store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        pristine = [plan.model_dump(mode="json") for plan in retrieved]
        with pytest.raises(ValidationError):
            retrieved[0].campaign_id = "campaign-other"  # frozen by contract
        assert [
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        ] == pristine

    def test_empty_tuple_is_distinguishable_from_not_prepared(self) -> None:
        store, _ = _rich_store()
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        # A plain world has no transition-capable models: preparation
        # records an empty collection.
        store_plain, world_id = build_store()
        prepare(store_plain, world_id, runtime_version="2.0.0")
        plans = prepare_strategy_trajectory_plans(
            store=store_plain,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        assert plans == ()
        assert store_plain.get_strategy_trajectory_plans(TENANT, "campaign-1") == ()
        # Re-preparation of the empty collection is still refused.
        with pytest.raises(TrajectoryPlansAlreadyPreparedError):
            prepare_strategy_trajectory_plans(
                store=store_plain,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )

    def test_campaign_state_remains_compiled_after_preparation(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state is CampaignState.COMPILED
        assert all(
            store.get_run_status(TENANT, run_identifier(plan)).state is RunState.PLANNED
            for plan in store.get_run_plans(TENANT, "campaign-1")
        )


class _CountingTrajectoryLegion(MockLegionAdapter):
    """MockLegionAdapter wrapper counting trajectory boundary calls."""

    def __init__(self) -> None:
        self.trajectory_calls = 0

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.trajectory_calls += 1
        return super().request_trajectory_plan(request)


class _BoundaryMutatingLegion(MockLegionAdapter):
    """Mutates the disposable boundary request copy in every possible way.

    The adapter only ever sees the deep-copied boundary request; the
    service retains the authoritative request snapshot and builds plans
    exclusively from authoritative stored records. The adapter first
    captures the pristine request identifier and transition identifiers,
    then mutates the boundary copy: the strategy candidate identifier
    (via ``model_copy`` + ``object.__setattr__`` - the frozen contract
    refuses plain assignment), strategy metadata and policy data,
    state-model metadata, and transition guard/target values. The
    returned draft uses the captured pristine identifiers, so preparation
    must succeed and produce authoritative pristine plans.
    """

    def __init__(self) -> None:
        self.captured_request_ids: list[str] = []
        self.captured_transition_ids: list[tuple[str, ...]] = []

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        request_id = request.identifier
        transition_ids = tuple(
            transition.identifier for transition in request.available_transitions
        )
        self.captured_request_ids.append(request_id)
        self.captured_transition_ids.append(transition_ids)
        # 1. Strategy candidate identifier (frozen: rebuild the nested
        #    model and swap it in past the frozen guard).
        evil_candidate = request.strategy_candidate.model_copy(
            update={"identifier": "evil-candidate"}
        )
        object.__setattr__(request, "strategy_candidate", evil_candidate)
        # 2. Strategy metadata and policy nested data.
        request.strategy_candidate.metadata["hacked"] = True
        request.strategy_candidate.policy.summary = "hacked policy"
        # 3. State-model nested metadata.
        request.state_model.metadata["hacked"] = True
        # 4. Transition guard/target nested data.
        request.available_transitions[0].guard_values["status"] = "pwned"
        request.available_transitions[0].target_values["status"] = "pwned"
        return StrategyTrajectoryPlanDraft(
            request_id=request_id,
            ordered_transition_identifiers=transition_ids,
        )


class TestBoundaryRequestIsolation:
    def test_hostile_boundary_mutation_yields_pristine_authoritative_plans(self) -> None:
        """A mutated disposable boundary copy never influences plan construction.

        The hostile adapter captures the original request identifier and
        original valid transition identifiers, mutates the boundary
        copy's strategy candidate identifier, strategy metadata/policy,
        state-model metadata, and transition guard/target values, and
        returns a valid draft under the original identifiers. Preparation
        must succeed, every plan must use the pristine stored
        candidate/model/transition identities and hashes, and storage
        must remain unchanged.
        """
        store, _ = _rich_store()
        pristine_candidates = [
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, "campaign-1")
        ]
        hostile = _BoundaryMutatingLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=hostile, tenant_id=TENANT, campaign_id="campaign-1"
        )
        # 1. Preparation succeeds with the full matrix.
        assert len(plans) == 10
        assert len(hostile.captured_request_ids) == 10
        # Every request carried the pristine available sequence.
        campaign = store.get_campaign(TENANT, "campaign-1")
        assert all(len(ids) == 2 for ids in hostile.captured_transition_ids)
        # 2. Every plan uses the pristine stored candidate identity -
        #    never the mutated boundary identifier.
        assert all(plan.strategy_candidate_id != "evil-candidate" for plan in plans)
        assert all(plan.strategy_candidate_id in campaign.strategy_candidate_ids for plan in plans)
        # 3. Plans are byte-identical to a pristine preparation of the
        #    same store state (same identities and hashes).
        store_pristine, _ = _rich_store()
        pristine_plans = prepare_strategy_trajectory_plans(
            store=store_pristine,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        assert [plan.model_dump(mode="json") for plan in plans] == [
            plan.model_dump(mode="json") for plan in pristine_plans
        ]
        # 4. Stored strategy records are untouched and the getter's full
        #    re-verification passes.
        assert [
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, "campaign-1")
        ] == pristine_candidates
        retrieved = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [plan.model_dump(mode="json") for plan in retrieved] == [
            plan.model_dump(mode="json") for plan in plans
        ]


class TestStoredPlanCollectionIntegrity:
    """Collection-level stored-plan matrix verification (private injection)."""

    def _prepared(self) -> tuple[InMemoryScenarioStore, tuple[StrategyTrajectoryPlan, ...]]:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        return store, store._strategy_trajectory_plans[(TENANT, "campaign-1")]

    @staticmethod
    def _expect_rejected(
        store: InMemoryScenarioStore, tampered: tuple[StrategyTrajectoryPlan, ...]
    ) -> None:
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = tampered
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None

    def test_removed_plan_rejected(self) -> None:
        store, stored = self._prepared()
        self._expect_rejected(store, stored[:-1])

    def test_additional_plan_rejected(self) -> None:
        store, stored = self._prepared()
        self._expect_rejected(store, (*stored, stored[0]))

    def test_duplicated_plan_rejected(self) -> None:
        store, stored = self._prepared()
        # Plan 0's pair (and identifier) appears twice; plan 1's pair is
        # now missing - the collection must be rejected as a whole.
        self._expect_rejected(store, (stored[0], stored[0], *stored[2:]))

    def test_reversed_collection_rejected(self) -> None:
        store, stored = self._prepared()
        self._expect_rejected(store, tuple(reversed(stored)))

    def test_swapped_plans_rejected(self) -> None:
        store, stored = self._prepared()
        self._expect_rejected(store, (stored[1], stored[0], *stored[2:]))

    def test_missing_strategy_model_pair_rejected(self) -> None:
        store, stored = self._prepared()
        # The (fake-0, sm-2) pair is missing from the collection; the
        # (fake-0, sm-1) pair now appears twice. The duplicated copy
        # carries a forged (fresh) identifier and a self-consistent
        # content hash, so only the duplicate-PAIR check can catch it.
        duplicated = stored[0].model_copy(update={"identifier": "trajectory-plan-ffffffffffffffff"})
        duplicated = duplicated.model_copy(
            update={"content_hash": trajectory_plan_content_hash(duplicated)}
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (
                stored[0],
                duplicated,
                *stored[2:],
            )
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "duplicate trajectory plan strategy/model pair" in exc_info.value.reason

    def test_unexpected_strategy_model_pair_rejected(self) -> None:
        store, stored = self._prepared()
        # The expected (fake-0, sm-1) pair is replaced by a forged plan
        # for an unexpected (ghost) strategy - the expected pair is
        # missing and an unexpected pair is present.
        plan = stored[0]
        forged = plan.model_copy(
            update={
                "identifier": "trajectory-plan-ffffffffffffffff",
                "strategy_candidate_id": "ghost-candidate",
            }
        )
        forged = forged.model_copy(update={"content_hash": trajectory_plan_content_hash(forged)})
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (forged, *stored[1:])
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan collection pair mismatch" in exc_info.value.reason

    def test_changed_planned_at_rejected(self) -> None:
        store, stored = self._prepared()
        later = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
        tampered = stored[0].model_copy(update={"planned_at": later})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        assert exc_info.value.reason is not None
        assert "trajectory plan planned_at mismatch" in exc_info.value.reason

    def test_empty_collection_is_the_only_valid_state_for_plain_worlds(self) -> None:
        store_plain, world_id = build_store()
        prepare(store_plain, world_id, runtime_version="2.0.0")
        plans = prepare_strategy_trajectory_plans(
            store=store_plain,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        assert plans == ()
        # Any non-empty collection on a plain world is rejected.
        store_rich, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store_rich, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        foreign_plan = store_rich._strategy_trajectory_plans[(TENANT, "campaign-1")][0]
        with pytest.raises(StoredTrajectoryPlanIntegrityError):
            store_plain._strategy_trajectory_plans[(TENANT, "campaign-1")] = (foreign_plan,)
            get_strategy_trajectory_plans(
                store=store_plain, tenant_id=TENANT, campaign_id="campaign-1"
            )


class TestRunPlanMatrixPreflight:
    """Exact stored run-plan matrix verification before any LEGION call."""

    def _expect_rejected_before_legion(self, store: InMemoryScenarioStore) -> None:
        legion = _CountingTrajectoryLegion()
        with pytest.raises(RunInputIntegrityError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.trajectory_calls == 0

    def test_missing_run_plan_rejected(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = plans[:-1]
        self._expect_rejected_before_legion(store)

    def test_additional_run_plan_rejected(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = (*plans, plans[0])
        self._expect_rejected_before_legion(store)

    def test_reordered_run_plans_rejected(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = tuple(reversed(plans))
        self._expect_rejected_before_legion(store)

    def test_duplicated_strategy_seed_pair_rejected(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = (plans[0], plans[0], *plans[2:])
        self._expect_rejected_before_legion(store)

    def test_missing_strategy_seed_pair_rejected(self) -> None:
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        store._run_plans[(TENANT, "campaign-1")] = plans[1:]
        self._expect_rejected_before_legion(store)

    def test_changed_run_plan_with_internally_plausible_fields_rejected(self) -> None:
        """A self-consistent run plan under a different created time is
        still a matrix-level mismatch against the recomputed expectation
        (the runtime-version gate now rejects a non-2.0.0 matrix earlier
        with a typed error, so this tamper exercises the matrix check
        itself)."""
        store, _ = _rich_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        plan = plans[0]
        other_created_at = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
        tampered = plan.model_copy(update={"created_at": other_created_at})
        store._run_plans[(TENANT, "campaign-1")] = (tampered, *plans[1:])
        self._expect_rejected_before_legion(store)

    def test_candidate_collection_mismatch_rejected(self) -> None:
        store, _ = _rich_store()
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        store._strategy_candidates[(TENANT, "campaign-1")] = tuple(reversed(candidates))
        self._expect_rejected_before_legion(store)

    def test_candidate_collection_extra_member_rejected(self) -> None:
        store, _ = _rich_store()
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        store._strategy_candidates[(TENANT, "campaign-1")] = (*candidates, candidates[0])
        self._expect_rejected_before_legion(store)


class TestDuplicatePreparationPreflight:
    def test_second_preparation_makes_zero_legion_calls(self) -> None:
        store, _ = _rich_store()
        legion = _CountingTrajectoryLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        first_calls = legion.trajectory_calls
        assert first_calls == 10
        pristine = [plan.model_dump(mode="json") for plan in plans]
        with pytest.raises(TrajectoryPlansAlreadyPreparedError):
            prepare_strategy_trajectory_plans(
                store=store, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        # The second attempt made zero additional LEGION trajectory calls.
        assert legion.trajectory_calls == first_calls
        # The original collection remains byte-identical.
        assert [
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        ] == pristine

    def test_second_preparation_of_empty_collection_makes_zero_legion_calls(self) -> None:
        store_plain, world_id = build_store()
        prepare(store_plain, world_id, runtime_version="2.0.0")
        legion = _CountingTrajectoryLegion()
        plans = prepare_strategy_trajectory_plans(
            store=store_plain, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert plans == ()
        assert legion.trajectory_calls == 0
        with pytest.raises(TrajectoryPlansAlreadyPreparedError):
            prepare_strategy_trajectory_plans(
                store=store_plain, legion=legion, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert legion.trajectory_calls == 0
        assert store_plain.get_strategy_trajectory_plans(TENANT, "campaign-1") == ()


class TestStoredPlanContractRevalidation:
    """Strict stored-contract revalidation against validator bypasses.

    ``model_copy``/``model_construct`` and private-store injection can
    produce a stored ``StrategyTrajectoryPlan`` whose contract
    validators never ran - empty or 1001-reference tuples, malformed
    nested references, or foreign objects. The getter must strictly
    revalidate every stored plan against its complete contract (nested
    ``StrategyTrajectoryTransitionReference`` types and the 1-1000
    bound included) before trusting any field, reject with a generic
    public message, and never repair or rewrite storage.
    """

    _VIOLATION_REASON = "stored trajectory plan violates its contract"

    def _prepared(self) -> tuple[InMemoryScenarioStore, tuple[StrategyTrajectoryPlan, ...]]:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
        )
        return store, store._strategy_trajectory_plans[(TENANT, "campaign-1")]

    def _expect_contract_rejection(self, store: InMemoryScenarioStore) -> None:
        stored_before = store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            get_strategy_trajectory_plans(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        # The internal reason names only the violated rule.
        assert exc_info.value.reason == self._VIOLATION_REASON
        # The public message stays generic: no reason, field names,
        # validation details, hashes, or raw values.
        message = str(exc_info.value)
        assert "violates" not in message
        assert "transition_references" not in message
        assert "ValidationError" not in message
        assert "pydantic" not in message
        assert "rejected" in message
        # Storage is never repaired, normalized, replaced, or rewritten:
        # the exact same tuple object remains stored, and its contents
        # are unchanged (equality is type-safe even for injected foreign
        # objects, which have no model_dump).
        assert store._strategy_trajectory_plans[(TENANT, "campaign-1")] is stored_before
        assert store._strategy_trajectory_plans[(TENANT, "campaign-1")] == stored_before

    def test_empty_references_rejected(self) -> None:
        """transition_references=() with a recomputed content hash."""
        store, stored = self._prepared()
        tampered = stored[0].model_copy(update={"transition_references": ()})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        self._expect_contract_rejection(store)

    def test_1001_references_rejected(self) -> None:
        """1001 contiguous references with a recomputed content hash."""
        store, stored = self._prepared()
        source = stored[0].transition_references[0]
        references = tuple(
            StrategyTrajectoryTransitionReference(
                sequence_position=position,
                transition_identifier=source.transition_identifier,
                transition_id=source.transition_id,
                transition_content_hash=source.transition_content_hash,
            )
            for position in range(MAX_TRAJECTORY_PLAN_TRANSITIONS + 1)
        )
        tampered = stored[0].model_copy(update={"transition_references": references})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        self._expect_contract_rejection(store)

    def test_nested_reference_wrong_sequence_position_type_rejected(self) -> None:
        """A nested reference whose sequence_position is a string."""
        store, stored = self._prepared()
        source = stored[0].transition_references[0]
        bad_reference = StrategyTrajectoryTransitionReference.model_construct(
            sequence_position="0",  # wrong runtime type: str, not int
            transition_identifier=source.transition_identifier,
            transition_id=source.transition_id,
            transition_content_hash=source.transition_content_hash,
        )
        tampered = stored[0].model_copy(
            update={"transition_references": (bad_reference, *stored[0].transition_references[1:])}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        self._expect_contract_rejection(store)

    def test_nested_reference_invalid_hash_pattern_rejected(self) -> None:
        """A nested reference with a malformed transition_content_hash."""
        store, stored = self._prepared()
        source = stored[0].transition_references[0]
        bad_reference = StrategyTrajectoryTransitionReference.model_construct(
            sequence_position=0,
            transition_identifier=source.transition_identifier,
            transition_id=source.transition_id,
            transition_content_hash="not-a-valid-sha256",
        )
        tampered = stored[0].model_copy(
            update={"transition_references": (bad_reference, *stored[0].transition_references[1:])}
        )
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered, *stored[1:])
        self._expect_contract_rejection(store)

    def test_foreign_object_in_collection_rejected(self) -> None:
        """A non-StrategyTrajectoryPlan object in a correctly sized collection."""
        store, stored = self._prepared()
        foreign: dict[str, object] = {"campaign_id": "campaign-1"}
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = cast(
            tuple[StrategyTrajectoryPlan, ...], (foreign, *stored[1:])
        )
        self._expect_contract_rejection(store)

    def test_store_put_defense_in_depth_rejects_validator_bypassed_plan(self) -> None:
        """The store's put preflight applies the same strict revalidation.

        A validator-bypassed plan (empty references, recomputed hash) can
        never enter storage through ``put_strategy_trajectory_plans``
        either - the defense-in-depth check fires before the ownership
        preflight and before any write.
        """
        store, stored = self._prepared()
        tampered = stored[0].model_copy(update={"transition_references": ()})
        tampered = tampered.model_copy(
            update={"content_hash": trajectory_plan_content_hash(tampered)}
        )
        with pytest.raises(StoredTrajectoryPlanIntegrityError) as exc_info:
            store.put_strategy_trajectory_plans(OTHER_TENANT, "campaign-other", (tampered,))
        assert exc_info.value.reason == self._VIOLATION_REASON
        assert "violates" not in str(exc_info.value)
        # Nothing was written for the other tenant.
        with pytest.raises(TrajectoryPlansNotFoundError):
            store.get_strategy_trajectory_plans(OTHER_TENANT, "campaign-other")


class TestStoredPlanContractBoundaries:
    """Valid-boundary regression: exactly 1 and exactly 1000 references."""

    def test_exactly_one_reference_accepted(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store,
            legion=_ScriptedLegion(scripts=[_single_reference_script]),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        retrieved = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(retrieved) == 10
        assert all(len(plan.transition_references) == 1 for plan in retrieved)
        assert all(plan.transition_references[0].sequence_position == 0 for plan in retrieved)

    def test_exactly_1000_references_accepted(self) -> None:
        store, _ = _rich_store()
        prepare_strategy_trajectory_plans(
            store=store,
            legion=_ScriptedLegion(scripts=[_thousand_references_script]),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        retrieved = get_strategy_trajectory_plans(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(retrieved) == 10
        assert all(
            len(plan.transition_references) == MAX_TRAJECTORY_PLAN_TRANSITIONS for plan in retrieved
        )
        assert all(
            reference.sequence_position == position
            for plan in retrieved
            for position, reference in enumerate(plan.transition_references)
        )
        # Positions 0-999 are contiguous and every reference is
        # authoritative (identifier/id/hash resolved from the catalog).
        first = retrieved[0]
        assert [r.sequence_position for r in first.transition_references] == list(
            range(MAX_TRAJECTORY_PLAN_TRANSITIONS)
        )
        assert len({r.transition_identifier for r in first.transition_references}) == 1
        assert all(
            r.transition_content_hash == first.transition_references[0].transition_content_hash
            for r in first.transition_references
        )
