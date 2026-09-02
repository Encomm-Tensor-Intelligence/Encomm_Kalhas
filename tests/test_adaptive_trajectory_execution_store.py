"""Focused runtime-4 adaptive execution store proofs (H28-S06C1-C02B1).

Proves the real ``InMemoryScenarioStore`` canonical
``put_adaptive_run_trajectory_execution`` / ``get_adaptive_run_trajectory_execution``
flow end to end against independently re-derived authority: deterministic
identity, successful lifecycle, every upstream authority rejection, nested
evidence rejection, and store integrity/safety. Each adversarial case first
audits its own base fixture as valid, so each rejection is proven to fire for
exactly the intended invariant. No observation derivation, policy advancement,
transition execution, adaptive orchestration, or replay is invoked. No skips,
xfails, mocks, monkeypatching, or manual schema edits exist in this module.
"""

from __future__ import annotations

import dataclasses
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from math import inf
from typing import Literal

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionAlreadyExistsError,
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionNotFoundError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_input_hash,
    adaptive_run_trajectory_execution_content_hash,
    adaptive_run_trajectory_execution_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_trajectory_runtime import (
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.application.runtime_observation_declaration_service import (
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_identity import (
    runtime_observation_event_content_hash,
    runtime_observation_event_identifier,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.trajectory_integrity import _trace_hash
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
)
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import (
    AdaptiveRunTrajectoryExecution,
)
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
    RuntimeObservationDeclaration,
    RuntimeObservationEvent,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord

from tests.phase4_helpers import NOW, TENANT, prepare
from tests.phase20_helpers import build_observation_store, compile_observation_world

RUNTIME: Literal["4.0.0"] = "4.0.0"
CAMPAIGN = "campaign-1"
FOREIGN_TENANT = "tenant-2"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_TIMING = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)


# ---------------------------------------------------------------------------
# Typed fixture bundle
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """Every independently addressable authority of one canonical run."""

    store: InMemoryScenarioStore
    world_id: str
    campaign_id: str
    execution: AdaptiveRunTrajectoryExecution
    run_id: str
    run_plan: RunPlan
    status: RunStatus
    seed_id: str
    seed_hash: str
    world_content_hash: str
    realization_id: str
    realization_hash: str
    policy_hash: str
    plan_set_hash: str
    baseline_plan_id: str
    balanced_plan_id: str
    declaration_ids: tuple[str, str]


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
                manifest_id="manifest-1", state_model_id="sm-1", state_field_id=field_id
            ),
            timing=_TIMING,
            noise=_NO_NOISE,
            missing_behavior="false",
            declared_at=DECLARED_AT,
            metadata={},
        ),
    )


def _build_environment() -> tuple[InMemoryScenarioStore, str]:
    """Compile the world, campaign, plans, declarations, and bound policy."""
    store = build_observation_store()
    world_id = compile_observation_world(store)
    prepare(
        store,
        world_id,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    from kalhas.application.strategy_trajectory_service import (
        prepare_strategy_trajectory_plans,
    )

    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare(store, world_id, "obs-a", "level", "integer")
    _declare(store, world_id, "obs-b", "ratio", "number")
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_policy_draft(),
        binding_request=_binding_request(),
    )
    return store, world_id


def _build_execution(
    store: InMemoryScenarioStore,
    world_id: str,
    *,
    run_state: RunState = RunState.RUNNING,
) -> tuple[AdaptiveRunTrajectoryExecution, RunPlan, RunStatus, str, str]:
    """Hand-construct the runtime-4 execution through verified authorities.

    Returns the finalized execution, its runtime-4 run plan and run status,
    and the deterministic realization identity/content-hash pair.
    """
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == "seed-1")
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    plans_by_id = {p.identifier: p for p in plans}
    baseline_plan = next(
        p
        for p in plans
        if p.strategy_candidate_id == "mock-baseline" and p.state_model_id == "sm-1"
    )
    candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
    plan_input_hash = run_input_hash(
        world_content_hash=world.content_hash,
        strategy=candidates["mock-baseline"],
        seed=seed,
        runtime_version=RUNTIME,
    )
    run_plan = RunPlan(
        identifier="run-plan-1",
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        world_version_id=world_id,
        strategy_candidate_id="mock-baseline",
        scenario_seed_id=seed.identifier,
        runtime_version=RUNTIME,
        input_hash=plan_input_hash,
        created_at=NOW,
    )
    store.put_run_plans(TENANT, CAMPAIGN, (run_plan,))
    run_id = run_identifier(run_plan)
    status = RunStatus(
        identifier=f"status-{run_id}",
        tenant_id=TENANT,
        run_id=run_id,
        campaign_id=CAMPAIGN,
        run_plan_id=run_plan.identifier,
        state=run_state,
        runtime_version=RUNTIME,
        input_hash=plan_input_hash,
        created_at=NOW,
        changed_at=NOW,
    )
    store.put_run_status(TENANT, run_id, status)

    # Observation events: one per bound declaration, source step 0, observed.
    declarations = tuple(
        store.get_runtime_observation_declaration(TENANT, "scenario-1", world_id, observation_id)
        for observation_id in ("obs-a", "obs-b")
    )
    seed_hash = seed_content_hash(seed)
    event_inputs: tuple[
        tuple[RuntimeObservationDeclaration, int | float, Literal["integer", "number"]], ...
    ] = (
        (declarations[0], 4, "integer"),
        (declarations[1], 2.5, "number"),
    )
    events: list[RuntimeObservationEvent] = []
    for position, (declaration, value, kind) in enumerate(event_inputs):
        event = RuntimeObservationEvent(
            identifier=runtime_observation_event_identifier(
                tenant_id=TENANT,
                campaign_id=CAMPAIGN,
                scenario_seed_id=seed.identifier,
                runtime_observation_declaration_id=declaration.identifier,
                source_step_index=0,
            ),
            runtime_version=RUNTIME,
            observation_declaration_id=declaration.identifier,
            observation_declaration_content_hash=declaration.content_hash,
            observation_id=declaration.observation_id,
            source_kind="state_field",
            world_version_id=world_id,
            world_content_hash=world.content_hash,
            scenario_seed_id=seed.identifier,
            seed_content_hash=seed_hash,
            sequence_position=position,
            source_step_index=0,
            delay_steps=0,
            available_decision_step=0,
            terminal=False,
            status="observed",
            source_state_hash=state_hash({"level": 0, "ratio": 0.0, "status": "idle"}),
            external_input_bundle_id=None,
            external_input_bundle_content_hash=None,
            source_value=value,
            applied_noise_value=None,
            exposed_observation_value=value,
            observed_value_kind=kind,
            observed_value_unit=None,
            noise_domain_literal="kalhas-observation-noise-v1",
            noise_sampler_version="sha256-counter-v1",
            noise_draw_index=None,
            content_hash="0" * 64,
        )
        events.append(
            event.model_copy(update={"content_hash": runtime_observation_event_content_hash(event)})
        )

    snapshot = AdaptivePolicyStateSnapshot(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=0,
        current_action_id="act-1",
        action_installed_at_decision_step=0,
        completed_applications=0,
        last_switch_decision_step=None,
        remaining_global_switch_budget=2,
        per_rule_remaining_budgets=(("rule-1", 1), ("rule-2", 1)),
    )
    decision = AdaptivePolicyDecisionEvent(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=0,
        current_action_id="act-1",
        rule_evaluation_evidence=(),
        selected_rule_id=None,
        selected_action_id="act-1",
        decision_kind="fallback",
        action_changed=False,
        fallback_blocked_reason=None,
    )
    catalog = extract_world_catalog(world)
    embedded_transition = next(t for t in catalog.transitions if t.transition_id == "t-1")
    embedded_model = next(m for m in catalog.state_models if m.state_model_id == "sm-1")
    initial: dict[str, JsonValue] = {"level": 0, "ratio": 0.0, "status": "idle"}
    final: dict[str, JsonValue] = {"level": 1, "ratio": 1.5, "status": "idle"}
    attempt = RunTrajectoryAttemptRecord(
        sequence_position=0,
        transition_identifier=embedded_transition.identifier,
        transition_id="t-1",
        transition_content_hash=embedded_transition.content_hash,
        outcome="applied",
        before_state_hash=state_hash(initial),
        after_state_hash=state_hash(final),
    )
    result = RealizedStateTrajectoryResult(
        trajectory_plan_id=baseline_plan.identifier,
        trajectory_plan_content_hash=baseline_plan.content_hash,
        manifest_id=embedded_model.manifest_id,
        state_model_identifier=embedded_model.identifier,
        state_model_id=embedded_model.state_model_id,
        state_model_content_hash=embedded_model.content_hash,
        initial_state=initial,
        initial_state_hash=state_hash(initial),
        attempts=(attempt,),
        final_state=final,
        final_state_hash=state_hash(final),
        trace_hash=_trace_hash((attempt,)),
        content_hash="0" * 64,
    )
    result = result.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(result)}
    )

    realization = build_world_realization(
        world=world,
        state_models=catalog.state_models,
        model=None,
        seed=seed,
        realized_at=campaign.created_at,
    )
    bound_plans = tuple(
        plans_by_id[binding.trajectory_plan_id]
        for action in policy.actions
        for binding in action.trajectory_plan_bindings
    )
    ordered_plans = tuple(
        sorted(bound_plans, key=lambda p: (p.strategy_candidate_id, p.state_model_identifier))
    )
    plan_set_hash = trajectory_plan_set_hash(ordered_plans)
    input_hash = adaptive_run_input_hash(
        run_plan_id=run_plan.identifier,
        run_plan_input_hash=run_plan.input_hash,
        campaign_id=CAMPAIGN,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=seed.identifier,
        seed_content_hash_value=seed_hash,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        adaptive_policy_identifier=policy.identifier,
        adaptive_policy_content_hash=policy.content_hash,
        trajectory_plan_set_hash=plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    execution = AdaptiveRunTrajectoryExecution(
        identifier="",
        tenant_id=TENANT,
        run_id=run_id,
        campaign_id=CAMPAIGN,
        run_plan_id=run_plan.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=seed.identifier,
        seed_content_hash=seed_hash,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        runtime_version=RUNTIME,
        adaptive_policy_identifier=policy.identifier,
        policy_id=policy.policy_id,
        adaptive_policy_content_hash=policy.content_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        input_hash=input_hash,
        trajectory_plan_set_hash=plan_set_hash,
        observation_events=tuple(events),
        policy_state_snapshots=(snapshot,),
        decision_events=(decision,),
        switch_events=(),
        trajectory_results_by_decision=((result,),),
        content_hash="0" * 64,
        executed_at=run_plan.created_at,
    )
    identifier = adaptive_run_trajectory_execution_identifier(
        run_id=run_id, runtime_version=RUNTIME
    )
    with_identifier = execution.model_copy(update={"identifier": identifier})
    content_hash = adaptive_run_trajectory_execution_content_hash(with_identifier)
    return (
        with_identifier.model_copy(update={"content_hash": content_hash}),
        run_plan,
        status,
        realization.identifier,
        realization.content_hash,
    )


def _fixture(run_state: RunState = RunState.RUNNING) -> _Fixture:
    store, world_id = _build_environment()
    execution, run_plan, status, realization_id, realization_hash = _build_execution(
        store, world_id, run_state=run_state
    )
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == "seed-1")
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    baseline = next(
        p
        for p in plans
        if p.strategy_candidate_id == "mock-baseline" and p.state_model_id == "sm-1"
    )
    balanced = next(
        p
        for p in plans
        if p.strategy_candidate_id == "mock-balanced" and p.state_model_id == "sm-1"
    )
    return _Fixture(
        store=store,
        world_id=world_id,
        campaign_id=CAMPAIGN,
        execution=execution,
        run_id=execution.run_id,
        run_plan=run_plan,
        status=status,
        seed_id=seed.identifier,
        seed_hash=seed_content_hash(seed),
        world_content_hash=world.content_hash,
        realization_id=realization_id,
        realization_hash=realization_hash,
        policy_hash=policy.content_hash,
        plan_set_hash=execution.trajectory_plan_set_hash,
        baseline_plan_id=baseline.identifier,
        balanced_plan_id=balanced.identifier,
        declaration_ids=(
            store.get_runtime_observation_declaration(
                TENANT, "scenario-1", world_id, "obs-a"
            ).identifier,
            store.get_runtime_observation_declaration(
                TENANT, "scenario-1", world_id, "obs-b"
            ).identifier,
        ),
    )


def _stored_executions(store: InMemoryScenarioStore) -> int:
    return len(store._adaptive_run_trajectory_executions)


def _refinalize(execution: AdaptiveRunTrajectoryExecution) -> AdaptiveRunTrajectoryExecution:
    return execution.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(execution)}
    )


def _assert_self_audits(fixture: _Fixture) -> None:
    fixture.store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    got = fixture.store.get_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id
    )
    assert got == fixture.execution
    fixture.store._adaptive_run_trajectory_executions.clear()


def _expect_rejection(
    fixture: _Fixture,
    forged: AdaptiveRunTrajectoryExecution,
    error: type[Exception] = AdaptiveRunTrajectoryExecutionIntegrityError,
) -> None:
    with pytest.raises(error):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


# ---------------------------------------------------------------------------
# Group A - identity / hash proofs
# ---------------------------------------------------------------------------


def test_execution_identifier_is_deterministic() -> None:
    fixture = _fixture()
    identifier = adaptive_run_trajectory_execution_identifier(
        run_id=fixture.run_id, runtime_version=RUNTIME
    )
    assert identifier == fixture.execution.identifier
    assert identifier.startswith("adaptive-run-trajectory-execution-")
    assert identifier == adaptive_run_trajectory_execution_identifier(
        run_id=fixture.run_id, runtime_version=RUNTIME
    )


def test_runtime4_identifier_separated_from_historical_runtimes() -> None:
    fixture = _fixture()
    runtime4 = adaptive_run_trajectory_execution_identifier(
        run_id=fixture.run_id, runtime_version=RUNTIME
    )
    assert not runtime4.startswith("run-trajectory-execution-")
    # The historical runtime-3 identifier shares the non-adaptive prefix family.
    assert not runtime4.startswith("realization-trajectory-execution-")
    assert runtime4.startswith("adaptive-run-trajectory-execution-")


def test_aggregate_content_hash_is_deterministic_and_excludes_itself() -> None:
    fixture = _fixture()
    execution = fixture.execution
    assert execution.content_hash == adaptive_run_trajectory_execution_content_hash(execution)
    tampered = execution.model_copy(update={"content_hash": "1" * 64})
    assert adaptive_run_trajectory_execution_content_hash(tampered) == execution.content_hash


def test_adaptive_input_hash_is_deterministic_and_explicit() -> None:
    fixture = _fixture()
    baseline = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    with_bundle = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id="bundle-1",
        external_observation_input_bundle_content_hash="2" * 64,
        final_decision_step=0,
    )
    assert baseline == fixture.execution.input_hash
    assert with_bundle != fixture.execution.input_hash


@pytest.mark.parametrize(
    ("mutate_realization", "mutate_policy", "mutate_world"),
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ],
)
def test_covered_authority_changes_alter_input_hash(
    mutate_realization: bool, mutate_policy: bool, mutate_world: bool
) -> None:
    fixture = _fixture()
    baseline = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    altered = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash="5" * 64 if mutate_world else fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=(
            "3" * 64 if mutate_realization else fixture.realization_hash
        ),
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash="4" * 64 if mutate_policy else fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    assert altered != baseline


def test_canonical_mapping_order_does_not_alter_input_hash() -> None:
    fixture = _fixture()
    canonical = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    reordered = adaptive_run_input_hash(
        external_observation_input_bundle_content_hash=None,
        external_observation_input_bundle_id=None,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        adaptive_policy_content_hash=fixture.policy_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        world_realization_content_hash=fixture.realization_hash,
        world_realization_id=fixture.realization_id,
        seed_content_hash_value=fixture.seed_hash,
        scenario_seed_id=fixture.seed_id,
        world_content_hash=fixture.world_content_hash,
        world_version_id=fixture.world_id,
        campaign_id=fixture.campaign_id,
        run_plan_input_hash=fixture.run_plan.input_hash,
        run_plan_id=fixture.run_plan.identifier,
        final_decision_step=0,
    )
    assert reordered == canonical == fixture.execution.input_hash


def test_status_and_plan_share_planning_hash_but_execution_differs() -> None:
    fixture = _fixture()
    assert fixture.status.input_hash == fixture.run_plan.input_hash
    assert fixture.execution.input_hash != fixture.run_plan.input_hash


# ---------------------------------------------------------------------------
# Group B - successful lifecycle / store proofs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_state", [RunState.RUNNING, RunState.COMPLETE])
def test_put_then_get_round_trip(run_state: RunState) -> None:
    fixture = _fixture(run_state=run_state)
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    got = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert got == fixture.execution
    assert type(got) is AdaptiveRunTrajectoryExecution
    assert store.get_run_status(TENANT, fixture.run_id).state is run_state


def test_status_may_transition_to_complete_after_put() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    complete = fixture.status.model_copy(update={"state": RunState.COMPLETE, "changed_at": NOW})
    store.put_run_status(TENANT, fixture.run_id, complete)
    got = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert got == fixture.execution
    assert store.get_run_status(TENANT, fixture.run_id).state is RunState.COMPLETE


def test_store_returns_defensive_copies() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    first = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    second = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert first == second == fixture.execution
    assert first is not second
    assert first is not fixture.execution


def test_zero_activity() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


# ---------------------------------------------------------------------------
# Group C - lifecycle / ownership rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("run_state", [RunState.PLANNED, RunState.FAILED])
def test_disallowed_run_states_rejected(run_state: RunState) -> None:
    fixture = _fixture(run_state=run_state)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
    assert _stored_executions(fixture.store) == 0


def test_wrong_runtime_status_rejected() -> None:
    fixture = _fixture()
    drifted = fixture.status.model_copy(update={"runtime_version": "2.0.0"})
    fixture.store.put_run_status(TENANT, fixture.run_id, drifted)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
    assert _stored_executions(fixture.store) == 0


def test_status_plan_input_hash_disagreement_rejected() -> None:
    fixture = _fixture()
    drifted = fixture.status.model_copy(update={"input_hash": "6" * 64})
    fixture.store.put_run_status(TENANT, fixture.run_id, drifted)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
    assert _stored_executions(fixture.store) == 0


@pytest.mark.parametrize("field", ["campaign_id", "run_plan_id"])
def test_wrong_run_identity_fields_rejected(field: str) -> None:
    fixture = _fixture()
    foreign = _refinalize(fixture.execution.model_copy(update={field: "other"}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=foreign
        )
    assert _stored_executions(fixture.store) == 0


@pytest.mark.parametrize(
    ("tenant_id", "run_id"),
    [
        (FOREIGN_TENANT, "missing-run"),
        (TENANT, "missing-run"),
        (FOREIGN_TENANT, "PRESENT-RUN"),
    ],
)
def test_unknown_and_foreign_get_are_indistinguishable(tenant_id: str, run_id: str) -> None:
    fixture = _fixture()
    fixture.store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    target = fixture.run_id if run_id == "PRESENT-RUN" else run_id
    with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError):
        fixture.store.get_adaptive_run_trajectory_execution(tenant_id=tenant_id, run_id=target)


# ---------------------------------------------------------------------------
# Group D - upstream authority rejection
# ---------------------------------------------------------------------------


def _dropped_campaign_status(store: InMemoryScenarioStore, state: CampaignState) -> None:
    store.update_campaign_status(
        TENANT,
        CAMPAIGN,
        CampaignStatus(
            identifier=f"campaign-status-{CAMPAIGN}",
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            state=state,
            changed_at=NOW,
        ),
    )


@pytest.mark.parametrize(
    "state", [CampaignState.DRAFT, CampaignState.VALIDATED, CampaignState.RUNNING]
)
def test_campaign_not_compiled_rejected(state: CampaignState) -> None:
    fixture = _fixture()
    _dropped_campaign_status(fixture.store, state)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
    assert _stored_executions(fixture.store) == 0


@pytest.mark.parametrize("field", ["world_version_id", "scenario_seed_id"])
def test_wrong_world_or_seed_identity_rejected(field: str) -> None:
    fixture = _fixture()
    foreign = _refinalize(fixture.execution.model_copy(update={field: "other"}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=foreign
        )
    assert _stored_executions(fixture.store) == 0


def test_wrong_world_content_hash_rejected() -> None:
    fixture = _fixture()
    foreign = _refinalize(fixture.execution.model_copy(update={"world_content_hash": "5" * 64}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=foreign
        )
    assert _stored_executions(fixture.store) == 0


def test_wrong_seed_content_hash_rejected() -> None:
    fixture = _fixture()
    foreign = _refinalize(fixture.execution.model_copy(update={"seed_content_hash": "7" * 64}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=foreign
        )
    assert _stored_executions(fixture.store) == 0


def _forged(
    fixture: _Fixture,
    **authorities: object,
) -> AdaptiveRunTrajectoryExecution:
    """Re-derive the input hash and aggregate hash over self-consistent lies.

    The input-hash arguments carrying the forged authority values are
    passed as explicit keyword arguments so the final record stays
    internally consistent for the intended invariant.
    """
    baseline = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=fixture.plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    assert baseline == fixture.execution.input_hash
    forged = fixture.execution.model_copy(update=dict(authorities))
    input_hash = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=forged.world_realization_id,
        world_realization_content_hash=forged.world_realization_content_hash,
        adaptive_policy_identifier=forged.adaptive_policy_identifier,
        adaptive_policy_content_hash=forged.adaptive_policy_content_hash,
        trajectory_plan_set_hash=forged.trajectory_plan_set_hash,
        external_observation_input_bundle_id=forged.external_observation_input_bundle_id,
        external_observation_input_bundle_content_hash=(
            forged.external_observation_input_bundle_content_hash
        ),
        final_decision_step=0,
    )
    forged = forged.model_copy(update={"input_hash": input_hash})
    return _refinalize(forged)


@pytest.mark.parametrize("field", ["world_realization_id", "world_realization_content_hash"])
def test_wrong_realization_identity_rejected(field: str) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    forged = _forged(fixture, **{field: "other" if field.endswith("id") else "8" * 64})
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        (
            "adaptive_policy_content_hash",
            "9" * 64,
            AdaptiveRunTrajectoryExecutionValidationError,
        ),
        ("policy_id", "policy-9", AdaptiveRunTrajectoryExecutionValidationError),
        (
            "adaptive_policy_identifier",
            "other-identifier",
            AdaptiveRunTrajectoryExecutionIntegrityError,
        ),
    ],
)
def test_wrong_policy_authority_rejected(field: str, value: str, error: type[Exception]) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    forged = _forged(fixture, **{field: value})
    with pytest.raises(error):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_wrong_plan_set_hash_rejected() -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    forged = _forged(fixture, trajectory_plan_set_hash="a" * 64)
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_action_plan_binding_mismatch_rejected() -> None:
    """A baseline-decision result citing the balanced action's plan."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    world = fixture.store.get_world(TENANT, fixture.world_id)
    catalog = extract_world_catalog(world)
    model = next(m for m in catalog.state_models if m.state_model_id == "sm-1")
    transition = next(t for t in catalog.transitions if t.transition_id == "t-1")
    plans = fixture.store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    balanced = next(p for p in plans if p.identifier == fixture.balanced_plan_id)
    initial: dict[str, JsonValue] = {"level": 0, "ratio": 0.0, "status": "idle"}
    final: dict[str, JsonValue] = {"level": 2, "ratio": 2.5, "status": "idle"}
    attempt = RunTrajectoryAttemptRecord(
        sequence_position=0,
        transition_identifier=transition.identifier,
        transition_id="t-1",
        transition_content_hash=transition.content_hash,
        outcome="applied",
        before_state_hash=state_hash(initial),
        after_state_hash=state_hash(final),
    )
    result = RealizedStateTrajectoryResult(
        trajectory_plan_id=balanced.identifier,
        trajectory_plan_content_hash=balanced.content_hash,
        manifest_id=model.manifest_id,
        state_model_identifier=model.identifier,
        state_model_id=model.state_model_id,
        state_model_content_hash=model.content_hash,
        initial_state=initial,
        initial_state_hash=state_hash(initial),
        attempts=(attempt,),
        final_state=final,
        final_state_hash=state_hash(final),
        trace_hash=_trace_hash((attempt,)),
        content_hash="0" * 64,
    )
    result = result.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(result)}
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": ((result,),)})
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_wrong_executed_at_rejected() -> None:
    fixture = _fixture()
    foreign = _refinalize(
        fixture.execution.model_copy(
            update={"executed_at": datetime(2026, 1, 10, 0, 0, 0, tzinfo=UTC)}
        )
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=foreign
        )
    assert _stored_executions(fixture.store) == 0


def test_missing_external_bundle_provenance_fails_closed() -> None:
    """One-sided bundle provenance is rejected by the input-hash helper itself."""
    fixture = _fixture()
    with pytest.raises(ValueError, match="both present or both absent"):
        adaptive_run_input_hash(
            run_plan_id=fixture.run_plan.identifier,
            run_plan_input_hash=fixture.run_plan.input_hash,
            campaign_id=fixture.campaign_id,
            world_version_id=fixture.world_id,
            world_content_hash=fixture.world_content_hash,
            scenario_seed_id=fixture.seed_id,
            seed_content_hash_value=fixture.seed_hash,
            world_realization_id=fixture.realization_id,
            world_realization_content_hash=fixture.realization_hash,
            adaptive_policy_identifier=fixture.execution.adaptive_policy_identifier,
            adaptive_policy_content_hash=fixture.policy_hash,
            trajectory_plan_set_hash=fixture.plan_set_hash,
            external_observation_input_bundle_id="bundle-1",
            external_observation_input_bundle_content_hash=None,
            final_decision_step=0,
        )


# ---------------------------------------------------------------------------
# Group D2 - decision-horizon authority (H28-S06C2C-C01)
# ---------------------------------------------------------------------------


def _baseline_horizon_arguments(fixture: _Fixture) -> dict[str, object]:
    """The canonical horizon-free input-hash keyword arguments of one fixture."""
    return {
        "run_plan_id": fixture.run_plan.identifier,
        "run_plan_input_hash": fixture.run_plan.input_hash,
        "campaign_id": fixture.campaign_id,
        "world_version_id": fixture.world_id,
        "world_content_hash": fixture.world_content_hash,
        "scenario_seed_id": fixture.seed_id,
        "seed_content_hash_value": fixture.seed_hash,
        "world_realization_id": fixture.realization_id,
        "world_realization_content_hash": fixture.realization_hash,
        "adaptive_policy_identifier": fixture.execution.adaptive_policy_identifier,
        "adaptive_policy_content_hash": fixture.policy_hash,
        "trajectory_plan_set_hash": fixture.plan_set_hash,
        "external_observation_input_bundle_id": None,
        "external_observation_input_bundle_content_hash": None,
    }


def test_input_hash_zero_horizon_is_accepted_and_deterministic() -> None:
    """``final_decision_step=0`` is strictly accepted and fully deterministic."""
    fixture = _fixture()
    arguments = _baseline_horizon_arguments(fixture)
    hashed: Callable[..., object] = adaptive_run_input_hash
    first = hashed(**arguments, final_decision_step=0)
    second = hashed(**arguments, final_decision_step=0)
    assert first == second
    assert first == fixture.execution.input_hash


def test_input_hash_horizon_changes_the_digest() -> None:
    """Changing only the horizon from 0 to 1 changes the digest."""
    fixture = _fixture()
    arguments = _baseline_horizon_arguments(fixture)
    hashed: Callable[..., object] = adaptive_run_input_hash
    horizon_zero = hashed(**arguments, final_decision_step=0)
    horizon_one = hashed(**arguments, final_decision_step=1)
    assert horizon_zero != horizon_one


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(True, id="bool-true"),
        pytest.param(False, id="bool-false"),
        pytest.param(0.0, id="float-zero"),
        pytest.param(1.0, id="float-one"),
        pytest.param("0", id="str-zero"),
        pytest.param("1", id="str-one"),
        pytest.param(None, id="none"),
    ],
)
def test_input_hash_rejects_non_exact_int_horizons(value: object) -> None:
    """Bool, float, string, and None horizons raise a generic ValueError."""
    fixture = _fixture()
    arguments = _baseline_horizon_arguments(fixture)
    hashed: Callable[..., object] = adaptive_run_input_hash
    with pytest.raises(ValueError) as excinfo:
        hashed(**arguments, final_decision_step=value)
    message = str(excinfo.value)
    assert message == "final_decision_step must be an exact non-negative integer"
    assert str(value) not in message
    assert repr(value) not in message


def test_input_hash_rejects_negative_horizon() -> None:
    """A negative horizon raises the generic ValueError."""
    fixture = _fixture()
    arguments = _baseline_horizon_arguments(fixture)
    hashed: Callable[..., object] = adaptive_run_input_hash
    with pytest.raises(ValueError) as excinfo:
        hashed(**arguments, final_decision_step=-1)
    message = str(excinfo.value)
    assert message == "final_decision_step must be an exact non-negative integer"
    assert "-1" not in message


def test_input_hash_large_non_negative_horizon_is_deterministic() -> None:
    """A large exact non-negative int horizon is accepted and deterministic."""
    fixture = _fixture()
    arguments = _baseline_horizon_arguments(fixture)
    hashed: Callable[..., object] = adaptive_run_input_hash
    large = 2**64 + 3
    first = hashed(**arguments, final_decision_step=large)
    second = hashed(**arguments, final_decision_step=large)
    assert first == second
    assert first != hashed(**arguments, final_decision_step=0)


def test_single_decision_store_round_trip_derives_zero_horizon() -> None:
    """One decision: the verifier derives horizon 0 and accepts the horizon-0 digest."""
    fixture = _fixture()
    store = fixture.store
    assert len(fixture.execution.decision_events) == 1
    assert [decision.decision_step for decision in fixture.execution.decision_events] == [0]
    hashed: Callable[..., object] = adaptive_run_input_hash
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    got = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert got == fixture.execution
    assert got.input_hash == hashed(
        **_baseline_horizon_arguments(fixture),
        final_decision_step=0,
    )
    store._adaptive_run_trajectory_executions.clear()


def _two_decision_execution(fixture: _Fixture) -> AdaptiveRunTrajectoryExecution:
    """Extend the canonical aggregate with a contract-valid second decision.

    Step 1 retains ``act-1`` by fallback: no switch (``switch_events``
    stays empty exactly as the contract requires for unchanged decisions),
    the snapshot satisfies the temporal invariants for an unswitched
    installation at step 0, and the per-decision result continues the
    state chain from the step-0 final state through the same bound
    baseline plan. Every nested record is freshly self-hashed; the
    aggregate input hash is computed at the derived horizon
    ``final_decision_step=1`` and the content hash is finalized last over
    the identified payload.
    """
    base = fixture.execution
    policy = fixture.store.get_adaptive_policy(TENANT, CAMPAIGN)
    world = fixture.store.get_world(TENANT, fixture.world_id)
    catalog = extract_world_catalog(world)
    embedded_transition = next(t for t in catalog.transitions if t.transition_id == "t-1")
    embedded_model = next(m for m in catalog.state_models if m.state_model_id == "sm-1")
    plans = fixture.store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    baseline_plan = next(
        p
        for p in plans
        if p.strategy_candidate_id == "mock-baseline" and p.state_model_id == "sm-1"
    )
    step1_initial: dict[str, JsonValue] = {"level": 1, "ratio": 1.5, "status": "idle"}
    step1_final: dict[str, JsonValue] = {"level": 2, "ratio": 3.0, "status": "idle"}
    attempt = RunTrajectoryAttemptRecord(
        sequence_position=0,
        transition_identifier=embedded_transition.identifier,
        transition_id="t-1",
        transition_content_hash=embedded_transition.content_hash,
        outcome="applied",
        before_state_hash=state_hash(step1_initial),
        after_state_hash=state_hash(step1_final),
    )
    result1 = RealizedStateTrajectoryResult(
        trajectory_plan_id=baseline_plan.identifier,
        trajectory_plan_content_hash=baseline_plan.content_hash,
        manifest_id=embedded_model.manifest_id,
        state_model_identifier=embedded_model.identifier,
        state_model_id=embedded_model.state_model_id,
        state_model_content_hash=embedded_model.content_hash,
        initial_state=step1_initial,
        initial_state_hash=state_hash(step1_initial),
        attempts=(attempt,),
        final_state=step1_final,
        final_state_hash=state_hash(step1_final),
        trace_hash=_trace_hash((attempt,)),
        content_hash="0" * 64,
    )
    result1 = result1.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(result1)}
    )
    snapshot1 = AdaptivePolicyStateSnapshot(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=1,
        current_action_id="act-1",
        action_installed_at_decision_step=0,
        completed_applications=1,
        last_switch_decision_step=None,
        remaining_global_switch_budget=2,
        per_rule_remaining_budgets=(("rule-1", 1), ("rule-2", 1)),
    )
    decision1 = AdaptivePolicyDecisionEvent(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash=policy.content_hash,
        decision_step=1,
        current_action_id="act-1",
        rule_evaluation_evidence=(),
        selected_rule_id=None,
        selected_action_id="act-1",
        decision_kind="fallback",
        action_changed=False,
        fallback_blocked_reason=None,
    )
    two = base.model_copy(
        update={
            "policy_state_snapshots": (*base.policy_state_snapshots, snapshot1),
            "decision_events": (*base.decision_events, decision1),
            "trajectory_results_by_decision": (
                *base.trajectory_results_by_decision,
                (result1,),
            ),
        }
    )
    input_hash = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=base.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=base.trajectory_plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=1,
    )
    two = two.model_copy(update={"input_hash": input_hash})
    with_identifier = two.model_copy(
        update={
            "identifier": adaptive_run_trajectory_execution_identifier(
                run_id=fixture.run_id, runtime_version=RUNTIME
            )
        }
    )
    return with_identifier.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(with_identifier)}
    )


def test_two_decision_aggregate_round_trip_on_derived_horizon_one() -> None:
    """Two decisions: the store accepts the horizon-1 digest and derives 0/1 steps.

    The horizon is load-bearing in the accepting direction: the recorded
    digest was computed with ``final_decision_step=1``, so the verifier's
    own recompute must derive exactly the same horizon from the aggregate
    evidence for the put to succeed.
    """
    fixture = _fixture()
    _assert_self_audits(fixture)
    two = _two_decision_execution(fixture)
    assert [decision.decision_step for decision in two.decision_events] == [0, 1]
    assert len(two.policy_state_snapshots) == 2
    assert len(two.trajectory_results_by_decision) == 2
    assert len(two.decision_events) == 2
    assert two.input_hash == adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=two.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=two.trajectory_plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=1,
    )
    assert two.input_hash != fixture.execution.input_hash
    fixture.store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=two
    )
    got = fixture.store.get_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id
    )
    assert got == two
    fixture.store._adaptive_run_trajectory_executions.clear()


def test_two_decision_aggregate_rejects_horizon_zero_digest() -> None:
    """A horizon-0 digest on a two-decision aggregate is rejected as forged.

    The horizon is load-bearing in the rejecting direction: only the
    aggregate ``input_hash`` is recomputed with ``final_decision_step=0``
    (the content hash is then honestly refinalized), so strict
    revalidation passes and the verifier itself must reject the record on
    the input-hash mismatch. A correctly hashed horizon-1 record is
    accepted first, proving the rejection is caused by the horizon alone.
    """
    fixture = _fixture()
    _assert_self_audits(fixture)
    correct = _two_decision_execution(fixture)
    fixture.store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=correct
    )
    assert (
        fixture.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
        == correct
    )
    fixture.store._adaptive_run_trajectory_executions.clear()
    horizon_zero_input = adaptive_run_input_hash(
        run_plan_id=fixture.run_plan.identifier,
        run_plan_input_hash=fixture.run_plan.input_hash,
        campaign_id=fixture.campaign_id,
        world_version_id=fixture.world_id,
        world_content_hash=fixture.world_content_hash,
        scenario_seed_id=fixture.seed_id,
        seed_content_hash_value=fixture.seed_hash,
        world_realization_id=fixture.realization_id,
        world_realization_content_hash=fixture.realization_hash,
        adaptive_policy_identifier=correct.adaptive_policy_identifier,
        adaptive_policy_content_hash=fixture.policy_hash,
        trajectory_plan_set_hash=correct.trajectory_plan_set_hash,
        external_observation_input_bundle_id=None,
        external_observation_input_bundle_content_hash=None,
        final_decision_step=0,
    )
    assert horizon_zero_input != correct.input_hash
    tampered = correct.model_copy(update={"input_hash": horizon_zero_input})
    tampered = tampered.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(tampered)}
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=tampered
        )
    assert _stored_executions(fixture.store) == 0


# ---------------------------------------------------------------------------
# Group E - nested evidence rejection (each first audits the base as valid)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "error"),
    [
        ("content_hash", AdaptiveRunTrajectoryExecutionIntegrityError),
        ("seed_content_hash", AdaptiveRunTrajectoryExecutionValidationError),
    ],
)
def test_forged_observation_event_identity_rejected(field: str, error: type[Exception]) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    events = list(fixture.execution.observation_events)
    events[0] = events[0].model_copy(update={field: "a" * 64})
    forged = _refinalize(fixture.execution.model_copy(update={"observation_events": tuple(events)}))
    _expect_rejection(fixture, forged, error)


def test_forged_observation_provenance_rejected() -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    events = list(fixture.execution.observation_events)
    events[0] = events[0].model_copy(update={"observation_declaration_id": "decl-other"})
    forged = _refinalize(fixture.execution.model_copy(update={"observation_events": tuple(events)}))
    _expect_rejection(fixture, forged)


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        pytest.param(
            lambda snapshot: snapshot.model_copy(update={"policy_content_hash": "b" * 64}),
            AdaptiveRunTrajectoryExecutionValidationError,
            id="snapshot-policy-hash",
        ),
        pytest.param(
            lambda snapshot: snapshot.model_copy(update={"current_action_id": "act-9"}),
            AdaptiveRunTrajectoryExecutionIntegrityError,
            id="snapshot-unknown-action",
        ),
    ],
)
def test_snapshot_mismatch_rejected(
    mutate: Callable[[AdaptivePolicyStateSnapshot], object],
    error: type[Exception],
) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    snapshots = tuple(mutate(snapshot) for snapshot in fixture.execution.policy_state_snapshots)
    forged = _refinalize(fixture.execution.model_copy(update={"policy_state_snapshots": snapshots}))
    _expect_rejection(fixture, forged, error)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda decision: decision.model_copy(update={"policy_content_hash": "c" * 64}),
            id="decision-policy-hash",
        ),
        pytest.param(
            lambda decision: decision.model_copy(update={"selected_action_id": "act-9"}),
            id="decision-unknown-action",
        ),
    ],
)
def test_decision_mismatch_rejected(
    mutate: Callable[[AdaptivePolicyDecisionEvent], object],
) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    decisions = tuple(mutate(decision) for decision in fixture.execution.decision_events)
    forged = _refinalize(fixture.execution.model_copy(update={"decision_events": tuple(decisions)}))
    _expect_rejection(fixture, forged, AdaptiveRunTrajectoryExecutionValidationError)


def test_forged_switch_mismatch_rejected() -> None:
    """A forged switch carrying an unknown action and foreign policy hash."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    policy = fixture.store.get_adaptive_policy(TENANT, CAMPAIGN)
    switch = AdaptivePolicySwitchEvent(
        runtime_version=RUNTIME,
        policy_id=policy.policy_id,
        policy_content_hash="d" * 64,
        decision_step=1,
        old_action_id="act-1",
        new_action_id="act-9",
        trigger_kind="fallback",
        triggering_rule_id=None,
        global_switch_budget_before=2,
        global_switch_budget_after=1,
        rule_switch_budget_before=None,
        rule_switch_budget_after=None,
    )
    forged = _refinalize(fixture.execution.model_copy(update={"switch_events": (switch,)}))
    _expect_rejection(fixture, forged, AdaptiveRunTrajectoryExecutionValidationError)


def test_wrong_per_decision_plan_authority_rejected() -> None:
    """A decision flipped to act-2 leaves its baseline result plan unauthorized."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    decision = fixture.execution.decision_events[0].model_copy(
        update={"selected_action_id": "act-2", "action_changed": True}
    )
    forged = _refinalize(fixture.execution.model_copy(update={"decision_events": (decision,)}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trajectory_plan_content_hash", "e" * 64),
        ("state_model_content_hash", "f" * 64),
    ],
)
def test_result_authority_hash_rejected(field: str, value: str) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    results = tuple(
        tuple(result.model_copy(update={field: value}) for result in branch)
        for branch in fixture.execution.trajectory_results_by_decision
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": results})
    )
    _expect_rejection(fixture, forged)


@pytest.mark.parametrize("field", ["initial_state_hash", "final_state_hash"])
def test_wrong_state_hash_rejected(field: str) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    results = tuple(
        tuple(result.model_copy(update={field: "0" * 63 + "1"}) for result in branch)
        for branch in fixture.execution.trajectory_results_by_decision
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": results})
    )
    _expect_rejection(fixture, forged)


def test_broken_attempt_chain_rejected() -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    results: list[tuple[RealizedStateTrajectoryResult, ...]] = []
    for branch in fixture.execution.trajectory_results_by_decision:
        branch_results: list[RealizedStateTrajectoryResult] = []
        for result in branch:
            attempts = list(result.attempts)
            attempts[0] = attempts[0].model_copy(update={"after_state_hash": "1" * 64})
            branch_results.append(
                result.model_copy(
                    update={
                        "attempts": tuple(attempts),
                        "trace_hash": _trace_hash(tuple(attempts)),
                    }
                )
            )
        results.append(tuple(branch_results))
    refinalized_results = tuple(
        tuple(
            result.model_copy(
                update={"content_hash": realized_state_trajectory_result_content_hash(result)}
            )
            for result in branch
        )
        for branch in results
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": refinalized_results})
    )
    _expect_rejection(fixture, forged)


@pytest.mark.parametrize(
    ("field", "value"),
    [("trace_hash", "2" * 64), ("content_hash", "3" * 64)],
)
def test_wrong_trace_or_result_hash_rejected(field: str, value: str) -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    results = tuple(
        tuple(result.model_copy(update={field: value}) for result in branch)
        for branch in fixture.execution.trajectory_results_by_decision
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": results})
    )
    _expect_rejection(fixture, forged)


def test_non_finite_state_rejected() -> None:
    """The verifier rejects non-finite numbers nested in a finalized record."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    results = tuple(
        tuple(
            result.model_copy(
                update={
                    "initial_state": {"level": inf},
                    "initial_state_hash": state_hash(
                        {"level": inf, "ratio": 0.0, "status": "idle"}
                    ),
                }
            )
            for result in branch
        )
        for branch in fixture.execution.trajectory_results_by_decision
    )
    forged = _refinalize(
        fixture.execution.model_copy(update={"trajectory_results_by_decision": results})
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


# ---------------------------------------------------------------------------
# Group F - store integrity / safety
# ---------------------------------------------------------------------------


def test_duplicate_identical_write_rejected_and_preserves_original() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionAlreadyExistsError):
        store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
    got = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert got == fixture.execution
    assert _stored_executions(store) == 1


def test_duplicate_different_write_rejected_and_preserves_original() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    events = list(fixture.execution.observation_events)
    events[0] = events[0].model_copy(update={"content_hash": "b" * 64})
    forged = _refinalize(fixture.execution.model_copy(update={"observation_events": tuple(events)}))
    with pytest.raises(AdaptiveRunTrajectoryExecutionAlreadyExistsError):
        store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    got = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    assert got == fixture.execution
    assert _stored_executions(store) == 1


def test_exact_execution_type_only() -> None:
    """A non-contract object is rejected by exact type at the store boundary."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    store = fixture.store
    put: Callable[..., object] = store.put_adaptive_run_trajectory_execution
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        put(tenant_id=TENANT, run_id=fixture.run_id, execution="not-an-execution")
    assert _stored_executions(fixture.store) == 0


def test_model_construct_forgery_rejected() -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)
    forged = AdaptiveRunTrajectoryExecution.model_construct(**fixture.execution.model_dump())
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_subclass_forgery_rejected() -> None:
    fixture = _fixture()
    _assert_self_audits(fixture)

    class _Sub(AdaptiveRunTrajectoryExecution):
        pass

    forged = _Sub.model_construct(**fixture.execution.model_dump())
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_self_consistently_rehashed_upstream_corruption_rejected() -> None:
    """Rehashing the aggregate cannot rescue a false world-realization claim."""
    fixture = _fixture()
    _assert_self_audits(fixture)
    forged = _forged(fixture, world_realization_content_hash="7" * 64)
    assert forged.content_hash == adaptive_run_trajectory_execution_content_hash(forged)
    assert forged.input_hash != fixture.execution.input_hash
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=forged
        )
    assert _stored_executions(fixture.store) == 0


def test_private_stored_corruption_rejected_on_get_and_never_repaired() -> None:
    fixture = _fixture()
    store = fixture.store
    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    corrupted = fixture.execution.model_copy(update={"input_hash": "c" * 64})
    store._adaptive_run_trajectory_executions[(TENANT, fixture.run_id)] = corrupted
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
    stored = store._adaptive_run_trajectory_executions[(TENANT, fixture.run_id)]
    assert stored == corrupted
    assert stored != fixture.execution


def test_public_error_messages_leak_nothing() -> None:
    fixture = _fixture()
    store = fixture.store
    identifiers = (
        fixture.execution.identifier,
        fixture.run_id,
        fixture.execution.input_hash,
        fixture.execution.content_hash,
        fixture.execution.trajectory_plan_set_hash,
        fixture.seed_hash,
        fixture.realization_id,
    )
    observed: list[str] = []

    def _capture(exc: BaseException) -> None:
        observed.append(str(exc))

    store.put_adaptive_run_trajectory_execution(
        tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
    )
    store._adaptive_run_trajectory_executions.clear()
    drifted = fixture.status.model_copy(update={"input_hash": "6" * 64})
    store.put_run_status(TENANT, fixture.run_id, drifted)
    adversaries = (
        lambda: store.get_adaptive_run_trajectory_execution(
            tenant_id=FOREIGN_TENANT, run_id=fixture.run_id
        ),
        lambda: store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id="missing-run"),
        lambda: store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        ),
    )
    for adversary in adversaries:
        try:
            adversary()
        except (
            AdaptiveRunTrajectoryExecutionAlreadyExistsError,
            AdaptiveRunTrajectoryExecutionNotFoundError,
            AdaptiveRunTrajectoryExecutionValidationError,
            AdaptiveRunTrajectoryExecutionIntegrityError,
        ) as exc:
            _capture(exc)
        else:
            raise AssertionError(f"expected a typed rejection from {adversary}")
    assert all(message.strip() for message in observed)
    for message in observed:
        for secret in identifiers:
            assert secret not in message


def test_no_mutation_surfaces_exist() -> None:
    assert not hasattr(InMemoryScenarioStore, "list_adaptive_run_trajectory_executions")
    assert not hasattr(InMemoryScenarioStore, "update_adaptive_run_trajectory_execution")
    assert not hasattr(InMemoryScenarioStore, "delete_adaptive_run_trajectory_execution")
    assert not hasattr(InMemoryScenarioStore, "upsert_adaptive_run_trajectory_execution")


def test_failure_atomicity() -> None:
    fixture = _fixture()
    store = fixture.store
    before = _stored_executions(store)
    statuses_before = dict(store._run_statuses)
    broken = fixture.execution.model_copy(update={"input_hash": "d" * 64})
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=broken
        )
    assert _stored_executions(store) == before
    assert store._run_statuses == statuses_before
    assert store._operational_activity == {}
    assert store._activity_sequences == {}


def test_warnings_not_emitted_by_the_canonical_flow() -> None:
    fixture = _fixture()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fixture.store.put_adaptive_run_trajectory_execution(
            tenant_id=TENANT, run_id=fixture.run_id, execution=fixture.execution
        )
        fixture.store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=fixture.run_id)
