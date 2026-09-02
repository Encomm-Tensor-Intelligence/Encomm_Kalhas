"""Focused H28-S06C2B tests for the runtime-4 causal decision orchestrator.

Every test drives the real :func:`execute_adaptive_decision_step` over real
repository authorities only: a real ``InMemoryScenarioStore``, a real
compiled two-state-model world, real stored declarations, the real bound
``AdaptivePolicy``, the real initialized policy snapshot, and the three real
runtime-4 primitives (observation derivation, policy-state advancement,
selected-action application). No mocks and no production monkeypatching
anywhere. Callers supply the complete action-plan catalog for every bound
action; the orchestrator validates the complete catalog before any causal
work, derives the observations exactly once, advances the policy exactly
once, and resolves the selected action's plan tuple internally - the tests
never pre-run observation or policy work to decide which plans to supply,
and no preview evaluation exists in any helper.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_decision_step_service import (
    ActionPlanCatalog,
    AdaptiveDecisionStepDraft,
    AdaptiveDecisionStepResult,
    _verified_plan_catalog,
    _verified_seed_hash,
    execute_adaptive_decision_step,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_policy_identity import adaptive_policy_content_hash
from kalhas.application.adaptive_policy_state_machine import (
    initialize_adaptive_policy_state,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.domain_errors import KalhasDomainError
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
    accept_external_observation_input_bundle,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventCausalOrderError,
    RuntimeObservationEventValidationError,
)
from kalhas.application.runtime_observation_event_service import (
    ObservationStepDraft,
    derive_observation_step,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    prepare_strategy_trajectory_plans,
    trajectory_plan_content_hash,
)
from kalhas.application.world_compiler import compile_world
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicy,
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    BoundAdaptiveAction,
    ConditionComparisonLeaf,
    TrajectoryPlanBinding,
)
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
    RuntimeObservationEvent,
)
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, StateValueKind
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan

from tests.phase4_helpers import NOW, TENANT, build_scenario, prepare

CAMPAIGN = "campaign-1"
SEED_ID = "seed-1"
RUN_ID = "run-1"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
ACCEPTED_AT = datetime(2026, 1, 10, 9, 0, 0, tzinfo=UTC)
_TIMING_0 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_TIMING_DELAY1 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=1)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)
_MISSING_BEHAVIOR = Literal["false", "error"]
_EXT_KIND = Literal["integer", "number"]

PolicyKey = Literal["state", "delay", "external"]


@dataclass(frozen=True, slots=True)
class _Env:
    """One fully prepared real two-state-model environment."""

    store: InMemoryScenarioStore
    world_id: str
    policy: AdaptivePolicy
    stored_plans: tuple[StrategyTrajectoryPlan, ...]
    catalogs: tuple[ModelTrajectoryCatalog, ...]
    state_model_a: str
    state_model_b: str

    def complete_states(self, level: int, ratio: float) -> dict[str, dict[str, JsonValue]]:
        return {
            self.state_model_a: {"level": level, "ratio": ratio, "status": "idle"},
            self.state_model_b: {"count": 3, "weight": 0.5},
        }


def _leaf(
    condition_id: str,
    observation_id: str,
    kind: _EXT_KIND,
    threshold: float,
    missing: _MISSING_BEHAVIOR = "false",
) -> ConditionComparisonLeaf:
    return ConditionComparisonLeaf(
        kind="comparison",
        condition_id=condition_id,
        observation_id=observation_id,
        observed_value_kind=kind,
        unit=None,
        operator="gt",
        threshold=threshold,
        missing_behavior=missing,
    )


def _rule(
    rule_id: str,
    priority: int,
    target: str,
    observation_id: str,
    kind: _EXT_KIND,
    missing: _MISSING_BEHAVIOR = "false",
) -> AdaptivePolicyRuleDraft:
    return AdaptivePolicyRuleDraft(
        rule_id=rule_id,
        priority=priority,
        target_action_id=target,
        enter_condition=_leaf(f"{rule_id}-a", observation_id, kind, 0, missing),
        retain_condition=_leaf(f"{rule_id}-r", observation_id, kind, 0, missing),
        per_rule_switch_budget=1,
    )


def _policy_draft(key: PolicyKey) -> AdaptivePolicyDraft:
    rules: tuple[AdaptivePolicyRuleDraft, ...]
    if key == "external":
        rules = (
            _rule("rule-1", 0, "act-1", "obs-a", "integer"),
            _rule("rule-2", 1, "act-2", "obs-b", "number"),
            _rule("rule-3", 2, "act-1", "obs-c", "integer", "error"),
        )
    else:
        rules = (
            _rule("rule-1", 0, "act-1", "obs-level", "integer"),
            _rule("rule-2", 1, "act-2", "obs-ratio-noisy", "number"),
        )
        if key == "delay":
            rules = (*rules, _rule("rule-3", 2, "act-1", "obs-level-late", "integer"))
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=rules,
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


def _declare_state_field(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    field_id: str,
    timing: ObservationTiming,
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            state_source=StateFieldObservationDraft(
                manifest_id="manifest-1", state_model_id="sm-a", state_field_id=field_id
            ),
            timing=timing,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )


def _declare_external(
    store: InMemoryScenarioStore,
    world_id: str,
    observation_id: str,
    kind: _EXT_KIND,
    missing: _MISSING_BEHAVIOR = "false",
) -> None:
    declare_runtime_observation_declaration(
        store,
        tenant_id=TENANT,
        draft=RuntimeObservationDeclarationDraft(
            scenario_id="scenario-1",
            world_version_id=world_id,
            observation_id=observation_id,
            external_source=ExternalObservationDraft(
                external_channel_id="channel-1", external_value_kind=kind
            ),
            timing=_TIMING_0,
            noise=_NO_NOISE,
            missing_behavior=missing,
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )


def _new_store_with_world() -> tuple[InMemoryScenarioStore, str]:
    """A real store with a compiled world embedding two state models.

    Both state models declare the logical transition ``t-1``, so every
    strategy's declared transition sequence resolves independently in
    each catalog and every bound plan carries real repetitions.
    """
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
    bind_manifest(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        bound_at=BOUND_AT,
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

    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-a",
        state_fields=(
            _field("level", StateValueKind.INTEGER, 0),
            _field("ratio", StateValueKind.NUMBER, 0.0),
            _field("status", StateValueKind.STRING, "idle"),
        ),
        declared_at=DECLARED_AT,
    )
    declare_state_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-b",
        state_fields=(
            _field("count", StateValueKind.INTEGER, 3),
            _field("weight", StateValueKind.NUMBER, 0.5),
        ),
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
    return store, compiled.version.identifier


def _declare_models(
    store: InMemoryScenarioStore,
    world_id: str,
    key: PolicyKey,
) -> None:
    if key == "external":
        external_pairs: tuple[tuple[str, _EXT_KIND, _MISSING_BEHAVIOR], ...] = (
            ("obs-a", "integer", "false"),
            ("obs-b", "number", "false"),
            ("obs-c", "integer", "error"),
        )
        for observation_id, kind, missing in external_pairs:
            _declare_external(store, world_id, observation_id, kind, missing)
    else:
        _declare_state_field(store, world_id, "obs-level", "level", _TIMING_0)
        _declare_state_field(store, world_id, "obs-ratio-noisy", "ratio", _TIMING_0)
        if key == "delay":
            _declare_state_field(store, world_id, "obs-level-late", "level", _TIMING_DELAY1)


def _catalogs_for(
    store: InMemoryScenarioStore, world_id: str
) -> tuple[ModelTrajectoryCatalog, ...]:
    entries = extract_world_catalog(store.get_world(TENANT, world_id))
    return tuple(
        sorted(
            (
                ModelTrajectoryCatalog(
                    state_model=model,
                    transitions=tuple(
                        transition
                        for transition in entries.transitions
                        if transition.state_model_id == model.state_model_id
                    ),
                )
                for model in entries.state_models
            ),
            key=lambda catalog: catalog.state_model.identifier,
        )
    )


def _build_env(key: PolicyKey) -> _Env:
    """Build one complete real environment from empty store to bound policy."""
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare_models(store, world_id, key)
    policy = bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_policy_draft(key),
        binding_request=_binding_request(),
    )
    state_model_a = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a")
    state_model_b = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b")
    return _Env(
        store=store,
        world_id=world_id,
        policy=policy,
        stored_plans=store.get_strategy_trajectory_plans(TENANT, CAMPAIGN),
        catalogs=_catalogs_for(store, world_id),
        state_model_a=state_model_a.identifier,
        state_model_b=state_model_b.identifier,
    )


def _bound_plans(
    action: BoundAdaptiveAction, all_plans: tuple[StrategyTrajectoryPlan, ...]
) -> tuple[StrategyTrajectoryPlan, ...]:
    return tuple(
        next(plan for plan in all_plans if plan.identifier == binding.trajectory_plan_id)
        for binding in action.trajectory_plan_bindings
    )


def _action_catalog(env: _Env) -> dict[str, tuple[StrategyTrajectoryPlan, ...]]:
    """The complete plan catalog: one canonically ordered tuple per action."""
    return {
        action.action_id: _bound_plans(action, env.stored_plans) for action in env.policy.actions
    }


def _ordered_catalog(env: _Env, *, reverse: bool) -> dict[str, tuple[StrategyTrajectoryPlan, ...]]:
    base = _action_catalog(env)
    return {key: base[key] for key in sorted(base, reverse=reverse)}


def _run(
    env: _Env,
    draft: AdaptiveDecisionStepDraft,
    policy_state: AdaptivePolicyStateSnapshot,
    *,
    tenant_id: str = TENANT,
    run_id: str = RUN_ID,
    campaign_id: str = CAMPAIGN,
    scenario_seed_id: str = SEED_ID,
    action_plans: ActionPlanCatalog | None = None,
    catalogs: tuple[ModelTrajectoryCatalog, ...] | None = None,
    policy: AdaptivePolicy | None = None,
) -> AdaptiveDecisionStepResult:
    return execute_adaptive_decision_step(
        env.store,
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=campaign_id,
        scenario_seed_id=scenario_seed_id,
        policy=env.policy if policy is None else policy,
        policy_state=policy_state,
        action_plans=_action_catalog(env) if action_plans is None else action_plans,
        catalogs=env.catalogs if catalogs is None else catalogs,
        draft=draft,
    )


def _execute_raw(env: _Env, **overrides: object) -> object:
    """Call the orchestrator through an untyped binding for exact-type tests."""
    kwargs: dict[str, object] = {
        "store": env.store,
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "campaign_id": CAMPAIGN,
        "scenario_seed_id": SEED_ID,
        "policy": env.policy,
        "policy_state": initialize_adaptive_policy_state(env.policy),
        "action_plans": _action_catalog(env),
        "catalogs": env.catalogs,
        "draft": _state_step(env, 0, 3, 5, 2.5),
    }
    kwargs.update(overrides)
    caller: Callable[..., object] = execute_adaptive_decision_step
    return caller(**kwargs)


def _state_step(
    env: _Env,
    decision_step: int,
    final_decision_step: int,
    level: int,
    ratio: float,
    prior: tuple[RuntimeObservationEvent, ...] = (),
) -> AdaptiveDecisionStepDraft:
    return AdaptiveDecisionStepDraft(
        decision_step=decision_step,
        final_decision_step=final_decision_step,
        pre_action_states=env.complete_states(level, ratio),
        prior_observation_events=prior,
    )


def _external_bundle(
    env: _Env,
    *entries: tuple[str, int, int | float],
) -> ExternalObservationInputBundleDraft:
    """A bundle draft in the real store's canonical declaration order.

    Each entry's authoritative declaration identifier is loaded from the
    real stored declaration behind its policy binding (identifiers are
    hash-derived and do not follow observation_id order), and the value
    drafts are ordered by the exact canonical
    ``(source_step_index, runtime_observation_declaration_id)`` key the
    bundle service requires. Nothing is hardcoded or assumed.
    """
    identifiers = {
        observation_id: env.store.get_runtime_observation_declaration(
            TENANT, "scenario-1", env.world_id, observation_id
        ).identifier
        for observation_id, _step, _value in entries
    }
    ordered = sorted(entries, key=lambda entry: (entry[1], identifiers[entry[0]]))
    return ExternalObservationInputBundleDraft(
        entries=tuple(
            ExternalObservationInputValueDraft(
                observation_id=observation_id, source_step_index=step, value=value
            )
            for observation_id, step, value in ordered
        ),
        accepted_at=ACCEPTED_AT,
    )


def _accept(
    env: _Env,
    *entries: tuple[str, int, int | float],
) -> ExternalObservationInputBundleDraft:
    draft = _external_bundle(env, *entries)
    accept_external_observation_input_bundle(
        env.store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        scenario_seed_id=SEED_ID,
        draft=draft,
    )
    return draft


def _external_step(
    decision_step: int,
    final_decision_step: int,
    env: _Env,
    bundle: ExternalObservationInputBundleDraft,
    prior: tuple[RuntimeObservationEvent, ...] = (),
) -> AdaptiveDecisionStepDraft:
    return AdaptiveDecisionStepDraft(
        decision_step=decision_step,
        final_decision_step=final_decision_step,
        pre_action_states=env.complete_states(4, 2.5),
        prior_observation_events=prior,
        external_bundle_draft=bundle,
    )


def _two_step(
    env: _Env,
    level0: int,
    level1: int,
) -> tuple[AdaptiveDecisionStepResult, AdaptiveDecisionStepResult]:
    """Two real orchestrator steps over the fully available state environment.

    Both steps receive the complete action-plan catalog; the orchestrator
    resolves the plan tuple of the action it selected internally, so the
    helper performs no observation or policy work of its own.
    """
    snapshot = initialize_adaptive_policy_state(env.policy)
    step0 = _run(env, _state_step(env, 0, 3, level0, 2.5), snapshot)
    step1 = _run(
        env,
        _state_step(env, 1, 3, level1, 2.5, prior=step0.new_observation_events),
        step0.next_policy_state,
    )
    return step0, step1


def _rehash(plan: StrategyTrajectoryPlan) -> StrategyTrajectoryPlan:
    return plan.model_copy(update={"content_hash": trajectory_plan_content_hash(plan)})


def _selected_binding_ids(result: AdaptiveDecisionStepResult, policy: AdaptivePolicy) -> list[str]:
    selected = next(
        action
        for action in policy.actions
        if action.action_id == result.decision_event.selected_action_id
    )
    return [binding.trajectory_plan_id for binding in selected.trajectory_plan_bindings]


# ---------------------------------------------------------------------------
# Groups 1-7 - causal order, evidence shapes, retention and switch
# ---------------------------------------------------------------------------


def test_delay0_observation_is_derived_before_policy_evaluation() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot)
    by_observation = {event.observation_id: event for event in result.new_observation_events}
    assert set(by_observation) == {"obs-level", "obs-ratio-noisy"}
    level_event = by_observation["obs-level"]
    assert level_event.exposed_observation_value == 5
    assert level_event.source_step_index == 0
    assert level_event.available_decision_step == 0
    assert level_event.terminal is False
    noisy = by_observation["obs-ratio-noisy"].exposed_observation_value
    assert isinstance(noisy, float) and 2.0 <= noisy <= 3.0
    assert result.available_observation_events == result.new_observation_events
    assert result.decision_event.decision_step == 0
    assert result.decision_event.selected_action_id == "act-1"
    assert result.decision_event.selected_rule_id == "rule-1"
    assert result.pre_decision_policy_state == snapshot


def test_observation_value_changes_the_selected_action_through_the_real_machine() -> None:
    env = _build_env("state")
    step0, step1 = _two_step(env, 0, 0)
    assert step0.decision_event.selected_action_id == "act-1"
    assert step0.switch_event is None
    assert step1.decision_event.selected_action_id == "act-2"
    assert step1.decision_event.selected_rule_id == "rule-2"
    assert step1.decision_event.action_changed is True
    assert [traj.trajectory_plan_id for traj in step1.trajectory_results] == (
        _selected_binding_ids(step1, env.policy)
    )


def test_selected_action_exact_bound_plans_are_applied_afterward() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    states = env.complete_states(5, 2.5)
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot)
    selected = next(
        action
        for action in env.policy.actions
        if action.action_id == result.decision_event.selected_action_id
    )
    assert len(result.trajectory_results) == len(selected.trajectory_plan_bindings)
    for trajectory, binding in zip(
        result.trajectory_results, selected.trajectory_plan_bindings, strict=True
    ):
        assert isinstance(trajectory, RealizedStateTrajectoryResult)
        assert trajectory.trajectory_plan_id == binding.trajectory_plan_id
        assert trajectory.trajectory_plan_content_hash == binding.trajectory_plan_content_hash
        assert trajectory.initial_state == states[trajectory.state_model_identifier]
    assert result.next_policy_state.completed_applications == (snapshot.completed_applications + 1)
    assert result.next_policy_state.current_action_id == result.decision_event.selected_action_id


def test_observation_and_application_use_the_same_pre_action_values() -> None:
    env = _build_env("state")
    states = env.complete_states(7, 0.5)
    result = _run(env, _state_step(env, 0, 3, 7, 0.5), initialize_adaptive_policy_state(env.policy))
    level_event = next(
        event for event in result.new_observation_events if event.observation_id == "obs-level"
    )
    assert level_event.exposed_observation_value == states[env.state_model_a]["level"]
    for trajectory in result.trajectory_results:
        assert trajectory.initial_state == states[trajectory.state_model_identifier]


def test_exact_frozen_result_shapes() -> None:
    env = _build_env("state")
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    assert isinstance(result, AdaptiveDecisionStepResult)
    assert isinstance(result.new_observation_events, tuple)
    assert all(
        isinstance(event, RuntimeObservationEvent) for event in result.new_observation_events
    )
    assert isinstance(result.available_observation_events, tuple)
    assert isinstance(result.pre_decision_policy_state, AdaptivePolicyStateSnapshot)
    assert isinstance(result.decision_event, AdaptivePolicyDecisionEvent)
    assert result.switch_event is None or isinstance(result.switch_event, AdaptivePolicySwitchEvent)
    assert isinstance(result.next_policy_state, AdaptivePolicyStateSnapshot)
    assert isinstance(result.trajectory_results, tuple)


def test_same_action_retention_produces_no_switch_event() -> None:
    env = _build_env("state")
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    assert result.decision_event.action_changed is False
    assert result.switch_event is None
    assert [traj.trajectory_plan_id for traj in result.trajectory_results] == (
        _selected_binding_ids(result, env.policy)
    )


def test_real_switch_produces_exactly_one_matching_switch_event() -> None:
    env = _build_env("state")
    step0, step1 = _two_step(env, 0, 0)
    assert step0.switch_event is None
    switch = step1.switch_event
    assert switch is not None
    assert switch.decision_step == 1
    assert switch.old_action_id == "act-1"
    assert switch.new_action_id == "act-2"
    assert switch.triggering_rule_id == "rule-2"
    assert switch.policy_id == env.policy.policy_id
    assert switch.policy_content_hash == env.policy.content_hash
    assert step1.next_policy_state.current_action_id == "act-2"
    assert [traj.trajectory_plan_id for traj in step1.trajectory_results] == (
        _selected_binding_ids(step1, env.policy)
    )


# ---------------------------------------------------------------------------
# Groups 8, 9, 10 - declared missing evidence, delays, terminality
# ---------------------------------------------------------------------------


def test_missing_external_evidence_follows_declared_false_and_switches() -> None:
    env = _build_env("external")
    bundle = _accept(
        env,
        ("obs-a", 0, 8),
        ("obs-b", 0, 2.0),
        ("obs-c", 0, 1),
        ("obs-a", 1, 0),
        ("obs-b", 1, 2.5),
        ("obs-c", 1, 1),
    )
    step0 = _run(
        env, _external_step(0, 3, env, bundle), initialize_adaptive_policy_state(env.policy)
    )
    assert step0.decision_event.selected_action_id == "act-1"
    assert step0.switch_event is None
    step1 = _run(
        env,
        _external_step(1, 3, env, bundle, prior=step0.new_observation_events),
        step0.next_policy_state,
    )
    assert step1.decision_event.selected_action_id == "act-2"
    assert step1.switch_event is not None


def test_declared_error_missing_evidence_fails_typed() -> None:
    env = _build_env("external")
    bundle = _accept(
        env,
        ("obs-a", 0, 8),
        ("obs-b", 0, 2.0),
        ("obs-c", 0, 1),
        ("obs-a", 1, 0),
        ("obs-b", 1, 0.0),
    )
    step0 = _run(
        env, _external_step(0, 3, env, bundle), initialize_adaptive_policy_state(env.policy)
    )
    with pytest.raises(KalhasDomainError):
        _run(
            env,
            _external_step(1, 3, env, bundle, prior=step0.new_observation_events),
            step0.next_policy_state,
        )


def test_delayed_prior_event_becomes_available_exactly_one_step_later() -> None:
    env = _build_env("delay")
    step0 = derive_observation_step(
        env.store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        scenario_seed_id=SEED_ID,
        draft=ObservationStepDraft(
            decision_step=0,
            final_decision_step=3,
            state={env.state_model_a: env.complete_states(5, 2.5)[env.state_model_a]},
            prior_events=(),
        ),
    )
    assert {event.observation_id for event in step0.available_events} == {
        "obs-level",
        "obs-ratio-noisy",
    }
    step1 = derive_observation_step(
        env.store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        scenario_seed_id=SEED_ID,
        draft=ObservationStepDraft(
            decision_step=1,
            final_decision_step=3,
            state={env.state_model_a: env.complete_states(0, 0.0)[env.state_model_a]},
            prior_events=step0.new_events,
        ),
    )
    by_observation = {event.observation_id: event for event in step1.available_events}
    assert set(by_observation) == {"obs-level", "obs-level-late", "obs-ratio-noisy"}
    delayed = by_observation["obs-level-late"]
    assert delayed.source_step_index == 0
    assert delayed.available_decision_step == 1
    assert delayed.exposed_observation_value == 5
    fresh = by_observation["obs-level"]
    assert fresh.source_step_index == 1


def test_terminal_observation_is_recorded_but_never_becomes_decision_input() -> None:
    env = _build_env("delay")
    step0 = derive_observation_step(
        env.store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        scenario_seed_id=SEED_ID,
        draft=ObservationStepDraft(
            decision_step=0,
            final_decision_step=0,
            state={env.state_model_a: env.complete_states(5, 2.5)[env.state_model_a]},
            prior_events=(),
        ),
    )
    terminal = [event for event in step0.new_events if event.terminal]
    assert len(terminal) == 1
    assert terminal[0].observation_id == "obs-level-late"
    assert terminal[0].source_step_index == 0
    assert terminal[0].available_decision_step is None
    assert terminal[0] in step0.new_events
    assert all(event.terminal is False for event in step0.available_events)
    assert all(event.observation_id != "obs-level-late" for event in step0.available_events)


# ---------------------------------------------------------------------------
# Group 11 - external influence only through the real bundle path
# ---------------------------------------------------------------------------


def test_external_input_influences_only_through_the_accepted_bundle() -> None:
    env = _build_env("external")
    bundle = _accept(
        env,
        ("obs-a", 0, 8),
        ("obs-b", 0, 2.0),
        ("obs-c", 0, 1),
        ("obs-a", 1, 9),
        ("obs-b", 1, 0.0),
        ("obs-c", 1, 1),
    )
    step0 = _run(
        env, _external_step(0, 3, env, bundle), initialize_adaptive_policy_state(env.policy)
    )
    by_observation = {event.observation_id: event for event in step0.new_observation_events}
    assert by_observation["obs-a"].exposed_observation_value == 8
    assert by_observation["obs-a"].external_input_bundle_id is not None
    assert step0.decision_event.selected_action_id == "act-1"
    step1 = _run(
        env,
        _external_step(1, 3, env, bundle, prior=step0.new_observation_events),
        step0.next_policy_state,
    )
    assert step1.decision_event.selected_action_id == "act-1"
    assert step1.switch_event is None


# ---------------------------------------------------------------------------
# Groups 12-15 - determinism, immutability, store neutrality
# ---------------------------------------------------------------------------


def test_independent_byte_equivalent_environments_exactly_equal() -> None:
    first = _build_env("state")
    second = _build_env("state")
    result_first = _run(
        first, _state_step(first, 0, 3, 5, 2.5), initialize_adaptive_policy_state(first.policy)
    )
    result_second = _run(
        second, _state_step(second, 0, 3, 5, 2.5), initialize_adaptive_policy_state(second.policy)
    )
    assert result_first == result_second


def test_catalog_insertion_order_does_not_affect_the_result() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    forward = _ordered_catalog(env, reverse=False)
    backward = _ordered_catalog(env, reverse=True)
    assert list(forward) != list(backward)
    result_forward = _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=forward)
    result_backward = _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=backward)
    assert result_forward == result_backward
    assert result_forward.decision_event.selected_action_id == "act-1"


def test_caller_inputs_and_nested_state_values_remain_unchanged() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    states = env.complete_states(5, 2.5)
    draft = AdaptiveDecisionStepDraft(
        decision_step=0,
        final_decision_step=3,
        pre_action_states=copy.deepcopy(states),
    )
    catalog = _action_catalog(env)
    frozen_states = copy.deepcopy(states)
    frozen_policy = copy.deepcopy(env.policy)
    frozen_snapshot = copy.deepcopy(snapshot)
    frozen_catalog = copy.deepcopy(catalog)
    frozen_catalogs = copy.deepcopy(env.catalogs)
    _run(env, draft, snapshot, action_plans=catalog)
    assert draft.pre_action_states == frozen_states
    assert env.policy == frozen_policy
    assert snapshot == frozen_snapshot
    assert catalog == frozen_catalog
    assert env.catalogs == frozen_catalogs


def _authority_fingerprint(env: _Env) -> tuple[object, object, object]:
    return (
        env.store.get_strategy_trajectory_plans(TENANT, CAMPAIGN),
        env.store.get_adaptive_policy(TENANT, CAMPAIGN),
        env.store.list_operational_activity(TENANT),
    )


def test_store_content_and_activity_feed_unchanged_on_success() -> None:
    env = _build_env("state")
    before = _authority_fingerprint(env)
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    assert result.decision_event.selected_action_id == "act-1"
    assert _authority_fingerprint(env) == before
    assert env.store.list_operational_activity(TENANT) == ()


def test_store_content_and_activity_feed_unchanged_on_failure() -> None:
    env = _build_env("state")
    before = _authority_fingerprint(env)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, _state_step(env, 2, 1, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    assert _authority_fingerprint(env) == before
    assert env.store.list_operational_activity(TENANT) == ()


# ---------------------------------------------------------------------------
# Group 16 - typed rejections: provenance, drafts, forged authority
# ---------------------------------------------------------------------------


def test_rejects_wrong_tenant_campaign_and_seed_provenance() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    with pytest.raises(KalhasDomainError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, tenant_id="tenant-2")
    with pytest.raises(KalhasDomainError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, campaign_id="campaign-9")
    with pytest.raises(KalhasDomainError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, scenario_seed_id="seed-9")


def test_rejects_empty_run_context() -> None:
    env = _build_env("state")
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(
            env,
            _state_step(env, 0, 3, 5, 2.5),
            initialize_adaptive_policy_state(env.policy),
            run_id="",
        )


def _forged_policy(env: _Env) -> AdaptivePolicy:
    """A well-formed policy with one falsified plan binding: authority mismatch."""
    actions = [action.model_copy(deep=True) for action in env.policy.actions]
    bindings = list(actions[0].trajectory_plan_bindings)
    bindings[0] = bindings[0].model_copy(update={"trajectory_plan_content_hash": "f" * 64})
    actions[0] = actions[0].model_copy(update={"trajectory_plan_bindings": tuple(bindings)})
    forged = env.policy.model_copy(update={"actions": tuple(actions)})
    return forged.model_copy(update={"content_hash": adaptive_policy_content_hash(forged)})


def test_rejects_policy_differing_from_stored_authority() -> None:
    env = _build_env("state")
    with pytest.raises(KalhasDomainError):
        _run(
            env,
            _state_step(env, 0, 3, 5, 2.5),
            initialize_adaptive_policy_state(env.policy),
            policy=_forged_policy(env),
        )


def test_rejects_snapshot_draft_step_mismatch() -> None:
    env = _build_env("state")
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, _state_step(env, 1, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))


def test_rejects_decision_step_beyond_final_decision_step() -> None:
    env = _build_env("state")
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, _state_step(env, 2, 1, 5, 2.5), initialize_adaptive_policy_state(env.policy))


@pytest.mark.parametrize(
    ("decision_step", "final_decision_step"),
    [(True, 3), ("0", 3), (1.0, 3), (0, True), (0, "3"), (0, 1.0)],
)
def test_rejects_bool_string_and_float_step_values(
    decision_step: object, final_decision_step: object
) -> None:
    env = _build_env("state")
    draft = AdaptiveDecisionStepDraft(
        decision_step=cast("int", decision_step),
        final_decision_step=cast("int", final_decision_step),
        pre_action_states=env.complete_states(5, 2.5),
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, draft, initialize_adaptive_policy_state(env.policy))


def test_rejects_validator_bypassed_policy() -> None:
    env = _build_env("state")
    forged = env.policy.model_copy(update={"actions": [{"action_id": "act-1", "raw": True}]})
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(
            env,
            _state_step(env, 0, 3, 5, 2.5),
            initialize_adaptive_policy_state(env.policy),
            policy=forged,
        )


def test_rejects_validator_bypassed_snapshot() -> None:
    env = _build_env("state")
    forged = initialize_adaptive_policy_state(env.policy).model_copy(update={"decision_step": "0"})
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), forged)


def test_rejects_reordered_prior_events() -> None:
    env = _build_env("state")
    step0 = _run(env, _state_step(env, 0, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    events = step0.new_observation_events
    assert len(events) >= 2
    reordered = (events[1], events[0], *events[2:])
    with pytest.raises(RuntimeObservationEventCausalOrderError):
        _run(
            env,
            _state_step(env, 1, 3, 0, 0.0, prior=reordered),
            step0.next_policy_state,
        )


def test_rejects_forged_prior_events() -> None:
    env = _build_env("state")
    step0 = _run(env, _state_step(env, 0, 3, 5, 2.5), initialize_adaptive_policy_state(env.policy))
    forged = step0.new_observation_events[0].model_copy(update={"scenario_seed_id": "seed-9"})
    with pytest.raises(KalhasDomainError):
        _run(
            env,
            _state_step(env, 1, 3, 0, 0.0, prior=(forged,)),
            step0.next_policy_state,
        )


def test_rejects_missing_extra_and_foreign_pre_action_states() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    missing: dict[str, dict[str, JsonValue]] = {}
    extra: dict[str, dict[str, JsonValue]] = env.complete_states(5, 2.5)
    extra["sm-unknown"] = {"level": 1}
    foreign: dict[str, dict[str, JsonValue]] = {"sm-unknown": {"level": 5, "ratio": 2.5}}
    for states in (missing, extra, foreign):
        with pytest.raises(KalhasDomainError):
            _run(
                env,
                AdaptiveDecisionStepDraft(
                    decision_step=0, final_decision_step=3, pre_action_states=states
                ),
                snapshot,
            )


def test_rejects_declared_observation_state_absent_from_complete_state() -> None:
    env = _build_env("state")
    states = env.complete_states(5, 2.5)
    del states[env.state_model_a]
    with pytest.raises(RuntimeObservationEventValidationError):
        _run(
            env,
            AdaptiveDecisionStepDraft(
                decision_step=0, final_decision_step=3, pre_action_states=states
            ),
            initialize_adaptive_policy_state(env.policy),
        )


def test_rejects_non_finite_and_wrong_typed_nested_state() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    non_finite = env.complete_states(5, 2.5)
    non_finite[env.state_model_a]["ratio"] = float("inf")
    with pytest.raises(RuntimeObservationEventValidationError):
        _run(
            env,
            AdaptiveDecisionStepDraft(
                decision_step=0, final_decision_step=3, pre_action_states=non_finite
            ),
            snapshot,
        )
    wrong_type = env.complete_states(5, 2.5)
    wrong_type[env.state_model_a]["level"] = "high"
    with pytest.raises(KalhasDomainError):
        _run(
            env,
            AdaptiveDecisionStepDraft(
                decision_step=0, final_decision_step=3, pre_action_states=wrong_type
            ),
            snapshot,
        )


def test_missing_campaign_and_unknown_seed_convert_to_safe_typed_errors() -> None:
    env = _build_env("state")
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _verified_seed_hash(
            env.store,
            tenant_id=TENANT,
            campaign_id="campaign-404",
            scenario_seed_id=SEED_ID,
        )
    with pytest.raises(KalhasDomainError):
        _run(
            env,
            _state_step(env, 0, 3, 5, 2.5),
            initialize_adaptive_policy_state(env.policy),
            scenario_seed_id="seed-9",
        )


# ---------------------------------------------------------------------------
# Group 17 - complete action-plan catalog rejections
# ---------------------------------------------------------------------------


def test_rejects_wrong_plans_for_the_selected_action() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    catalog = _action_catalog(env)
    swapped = {"act-1": catalog["act-2"], "act-2": catalog["act-1"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=swapped)
    with pytest.raises(KalhasDomainError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, catalogs=())


def test_missing_action_catalog_key_rejected_before_causal_execution() -> None:
    env = _build_env("state")
    catalog = _action_catalog(env)
    del catalog["act-1"]
    states = env.complete_states(5, 2.5)
    del states[env.state_model_a]
    draft = AdaptiveDecisionStepDraft(
        decision_step=0, final_decision_step=3, pre_action_states=states
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, draft, initialize_adaptive_policy_state(env.policy), action_plans=catalog)


def test_extra_action_catalog_key_rejected_before_causal_execution() -> None:
    env = _build_env("state")
    catalog = _action_catalog(env)
    catalog["act-foreign"] = catalog["act-2"]
    states = env.complete_states(5, 2.5)
    del states[env.state_model_a]
    draft = AdaptiveDecisionStepDraft(
        decision_step=0, final_decision_step=3, pre_action_states=states
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _run(env, draft, initialize_adaptive_policy_state(env.policy), action_plans=catalog)


def test_rejects_wrong_typed_action_catalog_values() -> None:
    env = _build_env("state")
    base = _action_catalog(env)
    as_list = {"act-1": list(base["act-1"]), "act-2": base["act-2"]}
    as_dict = {"act-1": {}, "act-2": base["act-2"]}
    as_elements = {"act-1": ({"nope": True},), "act-2": base["act-2"]}
    for wrong in (as_list, as_dict, as_elements):
        with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
            _execute_raw(env, action_plans=wrong)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        _execute_raw(env, action_plans=["act-1"])


def test_rejects_reordered_action_plan_tuple() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    base = _action_catalog(env)
    assert len(base["act-1"]) == 2
    reordered = dict(base)
    reordered["act-1"] = tuple(reversed(base["act-1"]))
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=reordered)


def test_rejects_forged_plan_identifier_and_content_hash() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    base = _action_catalog(env)
    selected_plan = base["act-1"][0]
    renamed = _rehash(selected_plan.model_copy(update={"identifier": "plan-forged"}))
    renamed_catalog = {"act-1": (renamed,), "act-2": base["act-2"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=renamed_catalog)
    tampered = selected_plan.model_copy(update={"content_hash": "c" * 64})
    tampered_catalog = {"act-1": (tampered,), "act-2": base["act-2"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=tampered_catalog)


def test_rejects_wrong_strategy_candidate_or_hash() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    base = _action_catalog(env)
    candidate_forged = _rehash(
        base["act-1"][0].model_copy(update={"strategy_candidate_id": "mock-balanced"})
    )
    candidate_catalog = {"act-1": (candidate_forged,), "act-2": base["act-2"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=candidate_catalog)
    hash_forged = _rehash(base["act-1"][0].model_copy(update={"strategy_content_hash": "b" * 64}))
    hash_catalog = {"act-1": (hash_forged,), "act-2": base["act-2"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=hash_catalog)


@pytest.mark.parametrize(
    "field_update",
    (
        {"state_model_id": "sm-b"},
        {"state_model_content_hash": "a" * 64},
        {"state_model_identifier": "state-model-deadbeefdeadbeef"},
    ),
)
def test_rejects_wrong_state_model_binding(field_update: dict[str, str]) -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    base = _action_catalog(env)
    forged = _rehash(base["act-1"][0].model_copy(update=field_update))
    forged_catalog = {"act-1": (forged,), "act-2": base["act-2"]}
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=forged_catalog)


def test_unselected_action_corruption_rejected_before_causal_execution() -> None:
    env = _build_env("state")
    base = _action_catalog(env)
    corrupted = base["act-2"][0].model_copy(update={"content_hash": "d" * 64})
    catalog = {"act-1": base["act-1"], "act-2": (corrupted,)}
    states = env.complete_states(5, 2.5)
    del states[env.state_model_a]
    draft = AdaptiveDecisionStepDraft(
        decision_step=0, final_decision_step=3, pre_action_states=states
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        _run(env, draft, initialize_adaptive_policy_state(env.policy), action_plans=catalog)


def test_same_state_model_coverage_across_actions_is_accepted() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    base = _action_catalog(env)
    act_1_models = [plan.state_model_identifier for plan in base["act-1"]]
    act_2_models = [plan.state_model_identifier for plan in base["act-2"]]
    assert act_1_models == act_2_models
    assert len(set(act_1_models)) == len(act_1_models)
    result = _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot)
    assert result.decision_event.selected_action_id == "act-1"


def test_rejects_duplicate_plan_entry_inside_one_action() -> None:
    env = _build_env("state")
    base = _action_catalog(env)
    action = env.policy.actions[0]
    duplicated_bindings = (*action.trajectory_plan_bindings, action.trajectory_plan_bindings[0])
    duplicated_action = action.model_copy(update={"trajectory_plan_bindings": duplicated_bindings})
    other_actions = tuple(
        bound for bound in env.policy.actions if bound.action_id != action.action_id
    )
    duplicated_policy = env.policy.model_copy(
        update={"actions": (duplicated_action, *other_actions)}
    )
    duplicated_catalog = {
        **base,
        action.action_id: (*base[action.action_id], base[action.action_id][0]),
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError) as excinfo:
        _verified_plan_catalog(
            tenant_id=TENANT,
            run_id=RUN_ID,
            policy=duplicated_policy,
            action_plans=duplicated_catalog,
        )
    assert "plan identifier" in (excinfo.value.reason or "")


def test_rejects_duplicate_state_model_entry_inside_one_action() -> None:
    env = _build_env("state")
    base = _action_catalog(env)
    action = env.policy.actions[0]
    bindings = action.trajectory_plan_bindings
    renamed = _rehash(
        base[action.action_id][0].model_copy(update={"identifier": "plan-renamed-unique"})
    )
    duplicate_model_binding = TrajectoryPlanBinding(
        trajectory_plan_id=renamed.identifier,
        trajectory_plan_content_hash=renamed.content_hash,
        manifest_id=bindings[0].manifest_id,
        state_model_identifier=bindings[0].state_model_identifier,
        state_model_id=bindings[0].state_model_id,
        state_model_content_hash=bindings[0].state_model_content_hash,
    )
    assert renamed.state_model_identifier == bindings[0].state_model_identifier
    assert renamed.identifier not in {plan.identifier for plan in base[action.action_id]}
    same_model_action = action.model_copy(
        update={"trajectory_plan_bindings": (*bindings, duplicate_model_binding)}
    )
    other_actions = tuple(
        bound for bound in env.policy.actions if bound.action_id != action.action_id
    )
    same_model_policy = env.policy.model_copy(
        update={"actions": (same_model_action, *other_actions)}
    )
    same_model_catalog = {
        **base,
        action.action_id: (*base[action.action_id], renamed),
    }
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError) as excinfo:
        _verified_plan_catalog(
            tenant_id=TENANT,
            run_id=RUN_ID,
            policy=same_model_policy,
            action_plans=same_model_catalog,
        )
    assert "state-model identifier" in (excinfo.value.reason or "")


# ---------------------------------------------------------------------------
# Group 18 - exactly-once causal execution without preview evaluation
# ---------------------------------------------------------------------------


def test_each_causal_primitive_runs_exactly_once() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    step0 = _run(env, _state_step(env, 0, 3, 9, 2.5), snapshot)
    assert step0.decision_event.selected_action_id == "act-1"
    assert step0.switch_event is None
    assert step0.next_policy_state.completed_applications == snapshot.completed_applications + 1
    assert step0.next_policy_state.decision_step == snapshot.decision_step + 1
    assert step0.next_policy_state.current_action_id == "act-1"
    step1 = _run(
        env,
        _state_step(env, 1, 3, 0, 2.5, prior=step0.new_observation_events),
        step0.next_policy_state,
    )
    assert step1.switch_event is not None
    switch = step1.switch_event
    assert switch.global_switch_budget_before == (
        step0.next_policy_state.remaining_global_switch_budget
    )
    assert switch.global_switch_budget_after == switch.global_switch_budget_before - 1
    # On a switch step the machine installs the new action, so the
    # per-action application count restarts instead of adding one: it
    # equals decision_step - action_installed_at_decision_step, the
    # machine's own enforced invariant (its dedicated suite proves switch
    # steps never increment completed_applications).
    assert step1.next_policy_state.completed_applications == (
        step1.next_policy_state.decision_step
        - step1.next_policy_state.action_installed_at_decision_step
    )
    assert step1.next_policy_state.current_action_id == "act-2"
    assert [traj.trajectory_plan_id for traj in step1.trajectory_results] == (
        _selected_binding_ids(step1, env.policy)
    )
    independent = derive_observation_step(
        env.store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        scenario_seed_id=SEED_ID,
        draft=ObservationStepDraft(
            decision_step=1,
            final_decision_step=3,
            state={env.state_model_a: env.complete_states(0, 2.5)[env.state_model_a]},
            prior_events=step0.new_observation_events,
        ),
    )
    assert step1.new_observation_events == independent.new_events
    assert step1.available_observation_events == independent.available_events
    assert all(event.source_step_index == 1 for event in step1.new_observation_events)


# ---------------------------------------------------------------------------
# Group 19 - safe generic public error messages
# ---------------------------------------------------------------------------

_FORBIDDEN_SUBSTRINGS = (
    TENANT,
    CAMPAIGN,
    SEED_ID,
    RUN_ID,
    "policy-1",
    "act-1",
    "act-2",
    "rule-1",
    "obs-level",
    "obs-a",
    "seed-9",
    "campaign-404",
    "campaign-9",
    "tenant-2",
    "sm-unknown",
    "ValidationError",
    "KeyError",
    "AttributeError",
    "IndexError",
    "CampaignNotFoundError",
)


def test_public_error_messages_stay_safe() -> None:
    env = _build_env("state")
    snapshot = initialize_adaptive_policy_state(env.policy)
    forged_policy = env.policy.model_copy(update={"actions": [{"action_id": "act-1", "raw": True}]})
    forged_snapshot = snapshot.model_copy(update={"decision_step": "0"})
    foreign_states: dict[str, dict[str, JsonValue]] = {"sm-unknown": {"level": 5, "ratio": 2.5}}
    catalog = _action_catalog(env)
    swapped = {"act-1": catalog["act-2"], "act-2": catalog["act-1"]}
    calls: tuple[tuple[str, Callable[[], object]], ...] = (
        (
            "unknown_seed",
            lambda: _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, scenario_seed_id="seed-9"),
        ),
        (
            "forged_policy",
            lambda: _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, policy=forged_policy),
        ),
        (
            "forged_snapshot",
            lambda: _run(env, _state_step(env, 0, 3, 5, 2.5), forged_snapshot),
        ),
        ("bad_steps", lambda: _run(env, _state_step(env, 2, 1, 5, 2.5), snapshot)),
        (
            "foreign_states",
            lambda: _run(
                env,
                AdaptiveDecisionStepDraft(
                    decision_step=0, final_decision_step=3, pre_action_states=foreign_states
                ),
                snapshot,
            ),
        ),
        (
            "wrong_selected_catalog",
            lambda: _run(env, _state_step(env, 0, 3, 5, 2.5), snapshot, action_plans=swapped),
        ),
        (
            "wrong_catalog_shape",
            lambda: _execute_raw(env, action_plans={"act-1": "plans", "act-2": ()}),
        ),
        (
            "missing_campaign",
            lambda: _verified_seed_hash(
                env.store, tenant_id=TENANT, campaign_id="campaign-404", scenario_seed_id=SEED_ID
            ),
        ),
    )
    for _name, call in calls:
        with pytest.raises(KalhasDomainError) as excinfo:
            call()
        message = str(excinfo.value)
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in message
