"""Focused runtime-4 selected-action trajectory application proofs (H28-S06C2A).

Proves the pure ``apply_selected_adaptive_action`` primitive end to end
against a real compiled two-state-model world, a real bound ``AdaptivePolicy``
built by the real binding service, real stored ``StrategyTrajectoryPlan``
records (including one declared repeated-transition plan), and the real
Phase 13 transition kernel: successful multi-plan application, initial-state
authority, real guard outcomes, exact attempt/order/hash evidence, canonical
ordering, determinism, input immutability, per-action plan resolution, and
every rejection class - each adversarial case first audits its own base
fixture as valid, so each rejection is proven to fire for exactly the
intended invariant. No observation derivation, policy advancement, adaptive
orchestration, store write, activity event, replay, or aggregate execution
is invoked. No skips, xfails, mocks of the unit under test, monkeypatching,
or lint/type suppressions exist in this module.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from math import inf
from typing import Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_action_trajectory_runtime import (
    AdaptiveActionTrajectoryStepResult,
    apply_selected_adaptive_action,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_service import (
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    prepare_strategy_trajectory_plans,
    trajectory_plan_content_hash,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.adaptive_policy_state import AdaptivePolicyDecisionEvent
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
)
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import NOW, TENANT, build_scenario, prepare

RUNTIME: Literal["4.0.0"] = "4.0.0"
CAMPAIGN = "campaign-1"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_TIMING = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)


# ---------------------------------------------------------------------------
# Typed fixture bundle
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """Every independently addressable authority of one canonical decision."""

    policy: AdaptivePolicy
    baseline_decision: AdaptivePolicyDecisionEvent
    balanced_decision: AdaptivePolicyDecisionEvent
    baseline_plans: tuple[StrategyTrajectoryPlan, ...]
    balanced_plans: tuple[StrategyTrajectoryPlan, ...]
    catalogs: tuple[ModelTrajectoryCatalog, ...]
    pre_action_states: dict[str, dict[str, JsonValue]]
    drifted_states: dict[str, dict[str, JsonValue]]
    state_model_a: DomainStateModel
    state_model_b: DomainStateModel
    transition_a: DomainStateTransition
    transition_b: DomainStateTransition
    binding_a: object
    binding_b: object


def _leaf(
    condition_id: str,
    observation_id: str,
    kind: Literal["integer", "number"],
    threshold: int | float,
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id=observation_id,
        observed_value_kind=kind,
        unit=None,
        operator="gt",
        threshold=threshold,
        missing_behavior="false",
    )


def _policy_draft() -> AdaptivePolicyDraft:
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            AdaptivePolicyRuleDraft(
                rule_id="rule-1",
                priority=0,
                target_action_id="act-1",
                enter_condition=_leaf("c1a", "obs-a", "integer", 0),
                retain_condition=_leaf("c1r", "obs-a", "integer", 0),
                per_rule_switch_budget=1,
            ),
            AdaptivePolicyRuleDraft(
                rule_id="rule-2",
                priority=1,
                target_action_id="act-2",
                enter_condition=_leaf("c2a", "obs-b", "number", 0.0),
                retain_condition=_leaf("c2r", "obs-b", "number", 0.0),
                per_rule_switch_budget=1,
            ),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _binding_request() -> AdaptivePolicyBindingRequest:
    return AdaptivePolicyBindingRequest(
        policy_id="policy-1",
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=BOUND_AT,
        metadata={},
    )


def _declare(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    field_id: str,
    kind: Literal["integer", "number"],
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            state_source=StateFieldObservationDraft(
                manifest_id="manifest-1",
                state_model_id="sm-a",
                state_field_id=field_id,
            ),
            timing=_TIMING,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )


def _decision(policy: AdaptivePolicy, action_id: str) -> AdaptivePolicyDecisionEvent:
    """A valid, self-consistent decision event selecting ``action_id``."""
    return AdaptivePolicyDecisionEvent(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=0,
        current_action_id="act-1",
        rule_evaluation_evidence=(),
        selected_rule_id=None,
        selected_action_id=action_id,
        decision_kind="fallback",
        action_changed=action_id != "act-1",
        fallback_blocked_reason=None,
    )


def _fixture() -> _Fixture:
    store = InMemoryScenarioStore()
    scenario: ScenarioSpec = build_scenario()
    store.put_scenario(scenario)
    register_manifest(
        store,
        tenant_id=TENANT,
        identifier="manifest-1",
        pack_id="pack-1",
        name="Generic reference pack",
        pack_version="1.2.3",
        description="Declarative pack metadata only",
        supported_api_versions=("1",),
        capabilities=(
            DomainPackCapability(
                identifier="cap-1",
                description="Declared capability",
                input_ids=("in-1",),
                output_ids=("out-1",),
            ),
        ),
        schema_metadata={},
        created_at=NOW,
        metadata={},
    )
    from kalhas.application.domain_pack_binding_service import bind_manifest
    from kalhas.application.domain_state_model_service import declare_state_model
    from kalhas.application.domain_state_transition_service import declare_transition

    bind_manifest(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        bound_at=NOW,
    )

    def _field(
        identifier: str,
        kind: StateValueKind,
        initial: JsonValue,
    ) -> DomainStateFieldDefinition:
        return DomainStateFieldDefinition(
            identifier=identifier,
            description="Declared state field",
            value_kind=kind,
            initial_value=initial,
        )

    fields_a = (
        _field("level", StateValueKind.INTEGER, 0),
        _field("ratio", StateValueKind.NUMBER, 0.0),
        _field("status", StateValueKind.STRING, "idle"),
    )
    fields_b = (
        _field("count", StateValueKind.INTEGER, 3),
        _field("weight", StateValueKind.NUMBER, 0.5),
    )
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-a",
        state_fields=fields_a,
        declared_at=DECLARED_AT,
    )
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-b",
        state_fields=fields_b,
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-a",
        transition_id="t-1",
        description="Advance the numeric fields",
        guard_values={"level": 0, "ratio": 0.0},
        target_values={"level": 1, "ratio": 1.5},
        declared_at=DECLARED_AT,
    )
    declare_transition(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-b",
        transition_id="t-1",
        description="Set the secondary numeric fields",
        guard_values={"count": 3},
        target_values={"count": 4, "weight": 1.0},
        declared_at=DECLARED_AT,
    )
    from kalhas.application.world_compiler import compile_world

    compiled = compile_world(
        scenario,
        bindings=(store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1"),),
        state_models=(
            store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a"),
            store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b"),
        ),
        transitions=tuple(store.list_domain_state_transitions(TENANT, "scenario-1")),
    )
    store.put_world(compiled.version, compiled.manifest)
    world_id = compiled.version.identifier

    prepare(
        store,
        world_id,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    # Real stored plans: the baseline strategy declares the repeated logical
    # transition ("t-1", "t-1"). Both state models declare the logical id
    # "t-1" in their own catalogs, so the single per-strategy declaration
    # resolves to the repeated deterministic transition of each catalog -
    # both bound plans of the selected action carry real repetitions.
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare(store, world_id, "obs-a", "level", "integer")
    _declare(store, world_id, "obs-b", "ratio", "number")
    policy = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_policy_draft(),
        binding_request=_binding_request(),
    )
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    baseline_action = next(
        action for action in policy.actions if action.strategy_candidate_id == "mock-baseline"
    )
    balanced_action = next(
        action for action in policy.actions if action.strategy_candidate_id == "mock-balanced"
    )
    baseline_plans = tuple(
        next(plan for plan in plans if plan.identifier == binding.trajectory_plan_id)
        for binding in baseline_action.trajectory_plan_bindings
    )
    balanced_plans = tuple(
        next(plan for plan in plans if plan.identifier == binding.trajectory_plan_id)
        for binding in balanced_action.trajectory_plan_bindings
    )
    world = store.get_world(TENANT, world_id)
    catalog_entries = extract_world_catalog(world)
    state_model_a = next(m for m in catalog_entries.state_models if m.state_model_id == "sm-a")
    state_model_b = next(m for m in catalog_entries.state_models if m.state_model_id == "sm-b")
    transition_a = next(t for t in catalog_entries.transitions if t.state_model_id == "sm-a")
    transition_b = next(t for t in catalog_entries.transitions if t.state_model_id == "sm-b")
    catalogs = tuple(
        ModelTrajectoryCatalog(
            state_model=model,
            transitions=tuple(
                transition
                for transition in catalog_entries.transitions
                if transition.state_model_id == model.state_model_id
            ),
        )
        for model in catalog_entries.state_models
    )
    catalogs = tuple(sorted(catalogs, key=lambda catalog: catalog.state_model.identifier))
    binding_a = baseline_action.trajectory_plan_bindings[0]
    binding_b = baseline_action.trajectory_plan_bindings[1]
    pre_action_states: dict[str, dict[str, JsonValue]] = {
        state_model_a.identifier: {"level": 0, "ratio": 0.0, "status": "idle"},
        state_model_b.identifier: {"count": 3, "weight": 0.5},
    }
    drifted_states: dict[str, dict[str, JsonValue]] = {
        state_model_a.identifier: {"level": 5, "ratio": 9.0, "status": "active"},
        state_model_b.identifier: {"count": 0, "weight": 2.0},
    }
    return _Fixture(
        policy=policy,
        baseline_decision=_decision(policy, "act-1"),
        balanced_decision=_decision(policy, "act-2"),
        baseline_plans=baseline_plans,
        balanced_plans=balanced_plans,
        catalogs=catalogs,
        pre_action_states=pre_action_states,
        drifted_states=drifted_states,
        state_model_a=state_model_a,
        state_model_b=state_model_b,
        transition_a=transition_a,
        transition_b=transition_b,
        binding_a=binding_a,
        binding_b=binding_b,
    )


def _apply(
    fixture: _Fixture,
    *,
    decision: AdaptivePolicyDecisionEvent | None = None,
    plans: tuple[StrategyTrajectoryPlan, ...] | None = None,
    catalogs: tuple[ModelTrajectoryCatalog, ...] | None = None,
    states: dict[str, dict[str, JsonValue]] | None = None,
) -> AdaptiveActionTrajectoryStepResult:
    return apply_selected_adaptive_action(
        tenant_id=TENANT,
        run_id="run-1",
        policy=fixture.policy,
        decision_event=decision if decision is not None else fixture.baseline_decision,
        plans=plans if plans is not None else fixture.baseline_plans,
        catalogs=catalogs if catalogs is not None else fixture.catalogs,
        pre_action_states=states if states is not None else fixture.pre_action_states,
    )


def _assert_base_valid(fixture: _Fixture) -> None:
    result = _apply(fixture)
    assert len(result.trajectory_results) == 2


def _rehash(plan: StrategyTrajectoryPlan) -> StrategyTrajectoryPlan:
    return plan.model_copy(update={"content_hash": trajectory_plan_content_hash(plan)})


# ---------------------------------------------------------------------------
# Group A - successful application and exact evidence
# ---------------------------------------------------------------------------


def test_selected_action_with_multiple_state_model_plans() -> None:
    fixture = _fixture()
    result = _apply(fixture)
    assert isinstance(result, AdaptiveActionTrajectoryStepResult)
    assert len(result.trajectory_results) == 2
    for plan, trajectory in zip(
        fixture.policy.actions[0].trajectory_plan_bindings,
        result.trajectory_results,
        strict=True,
    ):
        assert isinstance(trajectory, RealizedStateTrajectoryResult)
        assert trajectory.trajectory_plan_id == plan.trajectory_plan_id


def test_initial_state_is_the_supplied_pre_action_state_not_the_model_default() -> None:
    fixture = _fixture()
    result = _apply(fixture, states=fixture.drifted_states)
    by_identifier = {
        trajectory.state_model_identifier: trajectory for trajectory in result.trajectory_results
    }
    drifted_a = fixture.drifted_states[fixture.state_model_a.identifier]
    assert by_identifier[fixture.state_model_a.identifier].initial_state == drifted_a
    # The model default for count differs from the supplied drifted value.
    assert by_identifier[fixture.state_model_b.identifier].initial_state == {
        "count": 0,
        "weight": 2.0,
    }


def test_guard_outcomes_and_final_states_come_from_the_real_engine() -> None:
    fixture = _fixture()
    applied = _apply(fixture)
    a_result = next(
        trajectory
        for trajectory in applied.trajectory_results
        if trajectory.state_model_identifier == fixture.state_model_a.identifier
    )
    b_result = next(
        trajectory
        for trajectory in applied.trajectory_results
        if trajectory.state_model_identifier == fixture.state_model_b.identifier
    )
    # t-1 guards on level==0/ratio==0.0: applied once, then the guard no
    # longer matches the patched state.
    assert [attempt.outcome for attempt in a_result.attempts] == ["applied", "guard_not_satisfied"]
    assert a_result.final_state == {"level": 1, "ratio": 1.5, "status": "idle"}
    # The sm-b t-1 guards on count==3: applied once, then the guard no
    # longer matches the patched state.
    assert [attempt.outcome for attempt in b_result.attempts] == ["applied", "guard_not_satisfied"]
    assert b_result.final_state == {"count": 4, "weight": 1.0}
    # The drifted state satisfies no guard: every outcome records the real
    # guard_not_satisfied result and the final state stays the input state.
    guarded = _apply(fixture, states=fixture.drifted_states)
    for trajectory in guarded.trajectory_results:
        assert all(attempt.outcome == "guard_not_satisfied" for attempt in trajectory.attempts)
        assert trajectory.final_state == trajectory.initial_state


def test_exact_attempt_order_repetitions_identities_and_hashes() -> None:
    fixture = _fixture()
    result = _apply(fixture)
    a_result = next(
        trajectory
        for trajectory in result.trajectory_results
        if trajectory.state_model_identifier == fixture.state_model_a.identifier
    )
    transition = fixture.transition_a
    assert [attempt.sequence_position for attempt in a_result.attempts] == [0, 1]
    assert [
        (attempt.transition_identifier, attempt.transition_id, attempt.transition_content_hash)
        for attempt in a_result.attempts
    ] == [(transition.identifier, "t-1", transition.content_hash)] * 2
    assert a_result.attempts[0].before_state_hash == a_result.initial_state_hash
    assert a_result.attempts[0].after_state_hash == a_result.attempts[1].before_state_hash
    assert a_result.attempts[1].after_state_hash == a_result.final_state_hash
    # The first attempt actually applied its target patch; the repeated
    # second attempt recorded guard_not_satisfied and kept the state.
    assert a_result.attempts[0].after_state_hash != a_result.attempts[0].before_state_hash
    assert a_result.attempts[1].after_state_hash == a_result.attempts[1].before_state_hash


def test_canonical_result_ordering_matches_binding_order() -> None:
    fixture = _fixture()
    result = _apply(fixture)
    plan_ids = [trajectory.trajectory_plan_id for trajectory in result.trajectory_results]
    assert plan_ids == [
        binding.trajectory_plan_id for binding in fixture.policy.actions[0].trajectory_plan_bindings
    ]
    identifiers = [trajectory.state_model_identifier for trajectory in result.trajectory_results]
    assert identifiers == sorted(identifiers)


def test_repeated_byte_equivalent_inputs_produce_exactly_equal_results() -> None:
    fixture = _fixture()
    first = _apply(fixture)
    second = _apply(fixture)
    assert first == second
    assert first.trajectory_results == second.trajectory_results
    third = _apply(_fixture())
    assert first == third
    reordered: dict[str, dict[str, JsonValue]] = {
        key: dict(value) for key, value in reversed(list(fixture.pre_action_states.items()))
    }
    fourth = _apply(fixture, states=reordered)
    assert first == fourth


def test_caller_inputs_remain_deep_value_unchanged() -> None:
    fixture = _fixture()
    states = {key: dict(value) for key, value in fixture.pre_action_states.items()}
    policy_before = fixture.policy.model_dump(mode="json")
    decision_before = fixture.baseline_decision.model_dump(mode="json")
    plans_before = tuple(plan.model_dump(mode="json") for plan in fixture.baseline_plans)
    catalogs_before = tuple(
        (
            catalog.state_model.model_dump(mode="json"),
            tuple(transition.model_dump(mode="json") for transition in catalog.transitions),
        )
        for catalog in fixture.catalogs
    )
    _apply(fixture, states=states)
    assert fixture.policy.model_dump(mode="json") == policy_before
    assert fixture.baseline_decision.model_dump(mode="json") == decision_before
    assert tuple(plan.model_dump(mode="json") for plan in fixture.baseline_plans) == plans_before
    assert states == fixture.pre_action_states
    for (model_after, transitions_after), catalog in zip(
        catalogs_before, fixture.catalogs, strict=True
    ):
        assert catalog.state_model.model_dump(mode="json") == model_after
        assert (
            tuple(transition.model_dump(mode="json") for transition in catalog.transitions)
            == transitions_after
        )


def test_different_selected_actions_resolve_different_exact_bound_plans() -> None:
    fixture = _fixture()
    baseline = _apply(fixture, decision=fixture.baseline_decision)
    balanced = _apply(fixture, decision=fixture.balanced_decision, plans=fixture.balanced_plans)
    baseline_ids = [t.trajectory_plan_id for t in baseline.trajectory_results]
    balanced_ids = [t.trajectory_plan_id for t in balanced.trajectory_results]
    assert baseline_ids == [
        binding.trajectory_plan_id for binding in fixture.policy.actions[0].trajectory_plan_bindings
    ]
    assert balanced_ids == [
        binding.trajectory_plan_id for binding in fixture.policy.actions[1].trajectory_plan_bindings
    ]
    assert set(baseline_ids).isdisjoint(balanced_ids)


# ---------------------------------------------------------------------------
# Group B - rejection: caller shape, identity, and validator bypass
# ---------------------------------------------------------------------------


def test_unknown_selected_action_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    foreign_decision = fixture.baseline_decision.model_copy(
        update={"selected_action_id": "act-9", "action_changed": True}
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, decision=foreign_decision)


@pytest.mark.parametrize("field", ["policy_id", "policy_content_hash"])
def test_policy_decision_identity_or_hash_mismatch_rejected(field: str) -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    forged_value = "policy-9" if field == "policy_id" else "b" * 64
    forged_decision = fixture.baseline_decision.model_copy(update={field: forged_value})
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, decision=forged_decision)


def test_validator_bypassed_policy_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    policy_fields = fixture.policy.model_dump()
    policy_fields["minimum_dwell_steps"] = "one"
    forged = AdaptivePolicy.model_construct(**policy_fields)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        apply_selected_adaptive_action(
            tenant_id=TENANT,
            run_id="run-1",
            policy=forged,
            decision_event=fixture.baseline_decision,
            plans=fixture.baseline_plans,
            catalogs=fixture.catalogs,
            pre_action_states=fixture.pre_action_states,
        )


def test_validator_bypassed_decision_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    decision_fields = fixture.baseline_decision.model_dump()
    decision_fields["decision_step"] = "zero"
    forged = AdaptivePolicyDecisionEvent.model_construct(**decision_fields)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        apply_selected_adaptive_action(
            tenant_id=TENANT,
            run_id="run-1",
            policy=fixture.policy,
            decision_event=forged,
            plans=fixture.baseline_plans,
            catalogs=fixture.catalogs,
            pre_action_states=fixture.pre_action_states,
        )


def test_wrong_type_inputs_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    wrong_policy: Callable[..., object] = apply_selected_adaptive_action
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        wrong_policy(
            tenant_id=TENANT,
            run_id="run-1",
            policy="not-a-policy",
            decision_event=fixture.baseline_decision,
            plans=fixture.baseline_plans,
            catalogs=fixture.catalogs,
            pre_action_states=fixture.pre_action_states,
        )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        wrong_policy(
            tenant_id=TENANT,
            run_id="run-1",
            policy=fixture.policy,
            decision_event=fixture.baseline_decision,
            plans=list(fixture.baseline_plans),
            catalogs=fixture.catalogs,
            pre_action_states=fixture.pre_action_states,
        )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        wrong_policy(
            tenant_id=TENANT,
            run_id="run-1",
            policy=fixture.policy,
            decision_event=fixture.baseline_decision,
            plans=fixture.baseline_plans,
            catalogs=fixture.catalogs,
            pre_action_states=list(fixture.pre_action_states.items()),
        )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        wrong_policy(
            tenant_id=TENANT,
            run_id="run-1",
            policy=fixture.policy,
            decision_event=fixture.baseline_decision,
            plans=fixture.baseline_plans,
            catalogs=fixture.catalogs,
            pre_action_states={key: [("level", 0)] for key in fixture.pre_action_states},
        )


# ---------------------------------------------------------------------------
# Group C - rejection: plan and catalog authority
# ---------------------------------------------------------------------------


def test_missing_plan_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=fixture.baseline_plans[:1])


def test_extra_plan_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=fixture.baseline_plans + (fixture.balanced_plans[0],))


def test_reordered_plan_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=tuple(reversed(fixture.baseline_plans)))


def test_wrong_plan_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=fixture.balanced_plans)


def test_forged_plan_content_hash_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    tampered = fixture.baseline_plans[0].model_copy(update={"content_hash": "c" * 64})
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=(tampered, fixture.baseline_plans[1]))


def test_wrong_strategy_binding_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, decision=fixture.balanced_decision, plans=fixture.baseline_plans)


def test_missing_catalog_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, catalogs=fixture.catalogs[:1])


def test_extra_catalog_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    extra_catalog = ModelTrajectoryCatalog(
        state_model=fixture.state_model_b,
        transitions=(fixture.transition_b, fixture.transition_b),
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, catalogs=fixture.catalogs + (extra_catalog,))


def test_reordered_catalog_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, catalogs=tuple(reversed(fixture.catalogs)))


def test_wrong_catalog_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    wrong_catalog = ModelTrajectoryCatalog(
        state_model=fixture.state_model_a,
        transitions=(fixture.transition_a,),
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(
            fixture,
            catalogs=(
                wrong_catalog,
                ModelTrajectoryCatalog(
                    state_model=fixture.state_model_a,
                    transitions=(fixture.transition_a,),
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Group D - rejection: state collection and transition chain
# ---------------------------------------------------------------------------


def test_missing_state_collection_key_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    partial = {
        fixture.state_model_a.identifier: fixture.pre_action_states[
            fixture.state_model_a.identifier
        ]
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _apply(fixture, states=partial)


def test_extra_state_collection_key_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    extra = dict(fixture.pre_action_states)
    extra["foreign-state-model"] = {"level": 0}
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _apply(fixture, states=extra)


def test_invalid_pre_action_state_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    wrong_fields: dict[str, dict[str, JsonValue]] = {
        identifier: {"level": "not-an-int", "ratio": 0.0, "status": "idle"}
        for identifier in fixture.pre_action_states
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _apply(fixture, states=wrong_fields)


def test_boolean_integer_state_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    boolean_integer: dict[str, dict[str, JsonValue]] = {
        identifier: {"level": True, "ratio": 0.0, "status": "idle"}
        for identifier in fixture.pre_action_states
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _apply(fixture, states=boolean_integer)


def test_non_finite_pre_action_state_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    infinite: dict[str, dict[str, JsonValue]] = {
        identifier: {"level": inf, "ratio": 0.0, "status": "idle"}
        for identifier in fixture.pre_action_states
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _apply(fixture, states=infinite)


def test_foreign_transition_reference_rejected() -> None:
    fixture = _fixture()
    _assert_base_valid(fixture)
    reference_type = type(fixture.baseline_plans[0].transition_references[0])
    transition = fixture.transition_a
    forged = _rehash(
        fixture.baseline_plans[0].model_copy(
            update={
                "transition_references": (
                    reference_type(
                        sequence_position=0,
                        transition_identifier="trajectory-transition-missing",
                        transition_id=transition.transition_id,
                        transition_content_hash=transition.content_hash,
                    ),
                )
            }
        )
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=(forged, fixture.baseline_plans[1]))


def test_transition_logical_id_and_hash_cross_mismatch_rejected() -> None:
    """One declared reference cites a foreign logical id and content hash."""
    fixture = _fixture()
    _assert_base_valid(fixture)
    reference_type = type(fixture.baseline_plans[0].transition_references[0])
    forged = _rehash(
        fixture.baseline_plans[0].model_copy(
            update={
                "transition_references": (
                    reference_type(
                        sequence_position=0,
                        transition_identifier=fixture.transition_a.identifier,
                        transition_id="t-9",
                        transition_content_hash="d" * 64,
                    ),
                    reference_type(
                        sequence_position=1,
                        transition_identifier=fixture.transition_a.identifier,
                        transition_id="t-1",
                        transition_content_hash=fixture.transition_a.content_hash,
                    ),
                )
            }
        )
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=(forged, fixture.baseline_plans[1]))


def test_broken_transition_sequence_position_rejected() -> None:
    """A self-consistent plan whose only reference claims position 1."""
    fixture = _fixture()
    _assert_base_valid(fixture)
    reference = fixture.baseline_plans[1].transition_references[0]
    reference_type = type(reference)
    forged = _rehash(
        fixture.baseline_plans[1].model_copy(
            update={
                "transition_references": (
                    reference_type(
                        sequence_position=1,
                        transition_identifier=reference.transition_identifier,
                        transition_id=reference.transition_id,
                        transition_content_hash=reference.transition_content_hash,
                    ),
                )
            }
        )
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _apply(fixture, plans=(fixture.baseline_plans[0], forged))


# ---------------------------------------------------------------------------
# Group E - safety
# ---------------------------------------------------------------------------


def test_public_error_messages_leak_nothing() -> None:
    fixture = _fixture()
    decision_act2 = fixture.balanced_decision
    secrets = (
        fixture.policy.policy_id,
        fixture.policy.content_hash,
        "run-1",
        TENANT,
        fixture.baseline_plans[0].identifier,
        fixture.baseline_plans[0].content_hash,
        fixture.transition_a.identifier,
        str(fixture.pre_action_states),
    )
    adversaries: tuple[tuple[type[Exception], Callable[[], object]], ...] = (
        (
            AdaptiveRunTrajectoryExecutionIntegrityError,
            lambda: _apply(
                fixture,
                decision=fixture.baseline_decision.model_copy(
                    update={"selected_action_id": "act-9", "action_changed": True}
                ),
            ),
        ),
        (
            AdaptiveRunTrajectoryExecutionIntegrityError,
            lambda: _apply(fixture, decision=decision_act2, plans=fixture.baseline_plans),
        ),
        (
            AdaptiveRunTrajectoryExecutionValidationError,
            lambda: _apply(fixture, states={}),
        ),
    )
    observed: list[str] = []
    for expected_error, adversary in adversaries:
        try:
            adversary()
        except expected_error as exc:
            observed.append(str(exc))
        else:
            raise AssertionError("expected a typed rejection")
    assert observed
    for message in observed:
        assert message.strip()
        for secret in secrets:
            assert secret not in message


def test_result_attempts_carry_exact_engine_evidence() -> None:
    fixture = _fixture()
    result = _apply(fixture)
    for trajectory in result.trajectory_results:
        for attempt in trajectory.attempts:
            assert type(attempt) is RunTrajectoryAttemptRecord
        assert trajectory.initial_state_hash is not None
        assert trajectory.final_state_hash is not None
        assert trajectory.trace_hash is not None
        assert trajectory.content_hash is not None
