"""H28-S06C2C-C03A proof sections A-D for the runtime-4 per-run execution service.

Real stores, compiled worlds with a declared uncertainty model,
deterministic world realizations, real declarations, accepted external
bundles, bound adaptive policies, complete real action-plan catalogs,
runtime-4 RunPlan/RunStatus, the real pure builder, and the real store
persistence surface. The proven fixture-building helpers of
``tests/test_adaptive_run_execution_builder.py`` are reused by import
without editing that file. No mocks, monkeypatch, skip, xfail, noqa, or
type-ignore; no faked persistence; no production patching; no
duplicated decision algorithm.

Sections:

- A. successful execution (PLANNED -> RUNNING -> aggregate -> COMPLETE,
  exact-once persistence, reloaded equality, final authority verifier
  after COMPLETE, horizon cardinalities, real observation-driven
  switch/state evolution, external-bundle horizon-0 success, timestamp
  provenance, zero run events/activity/manifests, unchanged authorities
  and caller draft, tenant isolation with defensive-copy retrieval,
  byte-identical independent environments, and plan-set
  order-independence);
- B. typed safe atomic rejections (unknown/foreign runs, wrong runtime,
  RUNNING/COMPLETE/FAILED starting states, invalid status
  identifier/ownership/campaign/run-plan/input hash, missing/reordered/
  extra/corrupt run plans, campaign not exactly COMPILED, corrupt world,
  missing/corrupt policy, missing/corrupt declaration, missing/
  mismatched action plans, missing/mismatched uncertainty authority,
  missing seed authority, missing and mismatched external bundles,
  missing later-step external evidence, invalid horizons and pre-
  existing executions, and invalid caller types);
- C. source-boundary proofs (exactly one builder call site, the exact
  write order after the build, no forbidden store surfaces or adapters,
  no clock/random/UUID/network imports, the exact minimal __all__, the
  exact public signature, and the frozen slotted result dataclass).
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
from typing import Any, get_type_hints

import kalhas.application.adaptive_run_execution_service as service_module
import pytest
from kalhas.application.adaptive_condition_errors import AdaptiveConditionMissingObservationError
from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.adaptive_run_execution_builder import (
    RUNTIME_VERSION,
    AdaptiveRunExecutionBuildDraft,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionNotFoundError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    AdaptiveRunExecutionAuthorities,
    verify_adaptive_run_trajectory_execution_authority,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    RunNotFoundError,
    TrajectoryPlansNotFoundError,
)
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
    ExternalObservationInputValueDraft,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventValidationError,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.campaign import CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import ExternalObservationSource

from tests.phase4_helpers import NOW, TENANT
from tests.test_adaptive_run_execution_builder import (
    CAMPAIGN,
    SEED_ID,
    Env,
    _build_env,
    _build_env_external,
)

#: Draft horizons the service-boundary must reject (typed as ``Any`` only
#: so the strict-rejection proof can hand each value to the typed draft).
INVALID_HORIZONS: tuple[Any, ...] = (-1, True, "2")


def _planned_run(
    env: Env,
    *,
    plan_id: str = "run-plan-c03a",
) -> tuple[InMemoryScenarioStore, str, RunPlan, RunStatus]:
    """Plan exactly one runtime-4 run on a fresh real environment.

    The campaign is prepared (exactly COMPILED) with its compiled world,
    strategy candidates, real stored trajectory plans, real declarations,
    and the real bound adaptive policy; this helper adds exactly the
    deterministic PLANNED runtime-4 RunPlan and RunStatus the service
    may execute. Timestamps derive exclusively from the recorded plan
    creation time.
    """
    store = env.store
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, env.world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
    candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
    plan_input_hash = run_input_hash(
        world_content_hash=world.content_hash,
        strategy=candidates["mock-baseline"],
        seed=seed,
        runtime_version=RUNTIME_VERSION,
    )
    run_plan = RunPlan(
        identifier=plan_id,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        world_version_id=env.world_id,
        strategy_candidate_id="mock-baseline",
        scenario_seed_id=SEED_ID,
        runtime_version=RUNTIME_VERSION,
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
        state=RunState.PLANNED,
        runtime_version=RUNTIME_VERSION,
        input_hash=plan_input_hash,
        event_hash=None,
        created_at=NOW,
        changed_at=NOW,
    )
    store.put_run_status(TENANT, run_id, status)
    return store, run_id, run_plan, status


def _surface(store: InMemoryScenarioStore, run_id: str, world_id: str) -> dict[str, Any]:
    """A deep serializable fingerprint of every store surface the service
    could touch, including run events, input-integrity manifests,
    operational activity, declarations, uncertainty, and bundles.
    Missing or corrupt authority records are fingerprinted as ``None``
    so rejection proofs can compare byte-identical surfaces before and
    after a failed call."""
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    try:
        policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
        policy_dump = policy.model_dump(mode="json")
        declarations = {
            binding.observation_id: _declaration_dump(store, world_id, binding.observation_id)
            for binding in policy.observation_bindings
        }
    except (AdaptivePolicyNotFoundError, AdaptivePolicyIntegrityError):
        policy_dump = None
        declarations = {}
    try:
        run_status = store.get_run_status(TENANT, run_id).model_dump(mode="json")
    except RunNotFoundError:
        run_status = None
    try:
        plans_dump = tuple(
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
        )
    except TrajectoryPlansNotFoundError:
        plans_dump = ()
    try:
        candidates_dump = tuple(
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, CAMPAIGN)
        )
    except CampaignNotFoundError:
        candidates_dump = ()
    snapshot: dict[str, Any] = {
        "executions": tuple(
            execution.model_dump(mode="json")
            for execution in store._adaptive_run_trajectory_executions.values()
        ),
        "run_status": run_status,
        "campaign": campaign.model_dump(mode="json"),
        "campaign_status": store.get_campaign_status(TENANT, CAMPAIGN).model_dump(mode="json"),
        "world": store.get_world(TENANT, world_id).model_dump(mode="json"),
        "manifest": store.get_manifest(TENANT, world_id).model_dump(mode="json"),
        "policy": policy_dump,
        "plans": plans_dump,
        "candidates": candidates_dump,
        "declarations": declarations,
        "uncertainty": tuple(
            model.model_dump(mode="json") for model in store._world_uncertainty_models.values()
        ),
        "bundles": tuple(
            bundle.model_dump(mode="json")
            for bundle in store._external_observation_input_bundles.values()
        ),
        "run_events": tuple(
            event.model_dump(mode="json") for event in store._run_events.get((TENANT, run_id), ())
        ),
        "has_input_manifest": (TENANT, run_id) in store._input_integrity_manifests,
        "activity": tuple(
            event.model_dump(mode="json") for event in store.list_operational_activity(TENANT)
        ),
    }
    return snapshot


def _declaration_dump(
    store: InMemoryScenarioStore, world_id: str, observation_id: str
) -> dict[str, Any] | None:
    """One declaration fingerprint; missing or corrupt records become
    ``None`` so the atomicity surface stays comparable."""
    try:
        return store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, observation_id
        ).model_dump(mode="json")
    except (
        RuntimeObservationDeclarationNotFoundError,
        RuntimeObservationDeclarationIntegrityError,
    ):
        return None


def _assert_atomic_rejection(
    expected: type[BaseException],
    store: InMemoryScenarioStore,
    run_id: str,
    env: Env,
    draft: AdaptiveRunExecutionBuildDraft,
) -> pytest.ExceptionInfo[Any]:
    """Run one service call, require the typed error, and prove the complete
    store surface (authorities, run events, manifests, activity, run
    status) is byte-identical before and after."""
    before = _surface(store, run_id, env.world_id)
    with pytest.raises(expected) as excinfo:
        execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=draft,
        )
    assert _surface(store, run_id, env.world_id) == before
    exception_value: Any = excinfo.value
    assert exception_value.reason is not None
    return excinfo


execute_adaptive_run = service_module.execute_adaptive_run
AdaptiveRunExecutionResult = service_module.AdaptiveRunExecutionResult


def _rebuilt_authorities(
    store: InMemoryScenarioStore,
    env: Env,
    run_id: str,
) -> AdaptiveRunExecutionAuthorities:
    """Independently rebuild the complete authority chain from the store
    after execution, carrying the final COMPLETE status, exactly as the
    established store-verification idiom does."""
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, env.world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    catalog = extract_world_catalog(world)
    realization = build_world_realization(
        world=world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
        seed=seed,
        realized_at=campaign.created_at,
    )
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    plans_by_id = {plan.identifier: plan for plan in plans}
    run_plan = store.get_run_plans(TENANT, CAMPAIGN)[0]
    status = store.get_run_status(TENANT, run_id)
    campaign_status = store.get_campaign_status(TENANT, CAMPAIGN)
    declarations = {
        binding.observation_id: store.get_runtime_observation_declaration(
            TENANT, "scenario-1", env.world_id, binding.observation_id
        )
        for binding in policy.observation_bindings
    }
    action_plans = {
        action.action_id: tuple(
            plans_by_id[binding.trajectory_plan_id] for binding in action.trajectory_plan_bindings
        )
        for action in policy.actions
    }
    bundle = None
    if any(
        isinstance(declaration.observation_source, ExternalObservationSource)
        for declaration in declarations.values()
    ):
        bundle = store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID
        )
    return AdaptiveRunExecutionAuthorities(
        tenant_id=TENANT,
        run_id=run_id,
        campaign=campaign,
        campaign_status=campaign_status,
        run_status=status,
        run_plan=run_plan,
        world=world,
        seed=seed,
        realization=realization,
        uncertainty_model=catalog.uncertainty_model,
        policy=policy,
        declarations=declarations,
        action_plans=action_plans,
        external_bundle=bundle,
    )


# ---------------------------------------------------------------------------
# A. Successful execution
# ---------------------------------------------------------------------------


def test_a1_planned_runtime4_run_executes_to_complete() -> None:
    env = _build_env()
    store, run_id, run_plan, _planned_status = _planned_run(env)
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    result = execute_adaptive_run(store, tenant_id=TENANT, run_id=run_id, draft=draft)
    assert type(result) is AdaptiveRunExecutionResult
    assert type(result.status) is RunStatus
    assert type(result.execution) is AdaptiveRunTrajectoryExecution
    assert result.status.state is RunState.COMPLETE
    assert result.status.runtime_version == RUNTIME_VERSION == "4.0.0"
    assert result.status.identifier == f"status-{run_id}"
    assert result.status.tenant_id == TENANT
    assert result.status.run_id == run_id
    assert result.status.campaign_id == run_plan.campaign_id == CAMPAIGN
    assert result.status.run_plan_id == run_plan.identifier
    assert result.status.input_hash == run_plan.input_hash
    assert result.status.event_hash is None
    stored_status = store.get_run_status(TENANT, run_id)
    assert stored_status == result.status
    assert stored_status.state is RunState.COMPLETE


def test_a2_final_status_event_hash_remains_none() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    # The frozen v1 RunStatus.event_hash is never reinterpreted as the
    # adaptive aggregate content hash: it stays None while the aggregate
    # carries its own self-covering content hash.
    assert result.status.event_hash is None
    assert store.get_run_status(TENANT, run_id).event_hash is None
    assert result.execution.content_hash is not None
    assert len(result.execution.content_hash) == 64


def test_a3_aggregate_persisted_exactly_once_and_reloads_equal() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    assert len(store._adaptive_run_trajectory_executions) == 1
    reloaded = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    assert reloaded == result.execution
    assert reloaded.model_dump(mode="json") == result.execution.model_dump(mode="json")
    assert result.status == store.get_run_status(TENANT, run_id)


def test_a4_aggregate_passes_final_authority_verifier_after_complete() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    reloaded = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    authorities = _rebuilt_authorities(store, env, run_id)
    assert authorities.run_status.state is RunState.COMPLETE
    verify_adaptive_run_trajectory_execution_authority(reloaded, authorities=authorities)
    verify_adaptive_run_trajectory_execution_authority(result.execution, authorities=authorities)


def test_a5_horizon_cardinalities() -> None:
    for horizon, expected_decisions in ((0, 1), (2, 3)):
        env = _build_env()
        store, run_id, _run_plan, _planned_status = _planned_run(env)
        result = execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=horizon),
        )
        assert len(result.execution.decision_events) == expected_decisions
        assert len(result.execution.decision_events) == horizon + 1
        assert len(result.execution.policy_state_snapshots) == expected_decisions
        assert len(result.execution.trajectory_results_by_decision) == expected_decisions
        assert result.execution.decision_events[0].decision_step == 0


def test_a6_observation_driven_switch_and_state_evolution_intact() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    # Exactly one real observation-driven switch at step 1 on the real
    # policy (rule-1 on obs-level), with the real state evolution
    # threaded across the steps (level 0 -> 1 on sm-a).
    assert len(result.execution.switch_events) == 1
    assert result.execution.switch_events[0].decision_step == 1
    assert result.execution.decision_events[1].action_changed is True
    sm_a = env.sm_a
    first_results = result.execution.trajectory_results_by_decision[0]
    sm_a_results = [r for r in first_results if r.state_model_identifier == sm_a]
    assert sm_a_results
    assert sm_a_results[0].initial_state["level"] == 0
    assert sm_a_results[0].final_state["level"] == 1
    # The selected action of every decision agrees with the stored
    # trajectory plans (stored-plan authority, real application).
    store_plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    for _decision, results in zip(
        result.execution.decision_events,
        result.execution.trajectory_results_by_decision,
        strict=True,
    ):
        for trajectory_result in results:
            plan = next(
                plan
                for plan in store_plans
                if plan.identifier == trajectory_result.trajectory_plan_id
            )
            assert plan.state_model_id == trajectory_result.state_model_id
    assert result.status.state is RunState.COMPLETE


def test_a7_external_bundle_horizon_zero_success() -> None:
    env = _build_env_external()
    assert env.bundle_draft is not None
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=env.bundle_draft
        ),
    )
    assert result.status.state is RunState.COMPLETE
    assert len(result.execution.decision_events) == 1
    external_events = [
        event
        for event in result.execution.observation_events
        if event.source_kind == "external_input"
    ]
    # The accepted bundle's three external observations are all consumed
    # at step 0 (canonical declaration-identifier order).
    assert len(external_events) == 3
    reloaded = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    assert reloaded == result.execution
    authorities = _rebuilt_authorities(store, env, run_id)
    verify_adaptive_run_trajectory_execution_authority(reloaded, authorities=authorities)


def test_a8_timestamps_derive_only_from_run_plan_created_at() -> None:
    env = _build_env()
    store, run_id, run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    for status_field in (result.status.created_at, result.status.changed_at):
        assert status_field == run_plan.created_at
    assert result.execution.executed_at == run_plan.created_at
    completed = store.get_run_status(TENANT, run_id)
    assert completed.created_at == run_plan.created_at
    assert completed.changed_at == run_plan.created_at


def test_a9_no_run_event_stream_activity_or_input_manifest() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    with pytest.raises(RunNotFoundError):
        store.get_run_events(TENANT, run_id)
    with pytest.raises(RunNotFoundError):
        store.get_input_integrity_manifest(TENANT, run_id)
    assert store.list_operational_activity(TENANT) == ()
    assert not store._run_events
    assert not store._input_integrity_manifests
    assert not store._operational_activity


def test_a10_campaign_world_policy_plans_declarations_realization_unchanged() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    before = _surface(store, run_id, env.world_id)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    after = _surface(store, run_id, env.world_id)
    for key in (
        "campaign",
        "campaign_status",
        "world",
        "manifest",
        "policy",
        "plans",
        "candidates",
        "declarations",
        "uncertainty",
        "bundles",
        "run_events",
        "has_input_manifest",
        "activity",
    ):
        assert after[key] == before[key]
    assert before["executions"] == ()
    assert after["executions"] == (result.execution.model_dump(mode="json"),)
    assert before["run_status"]["state"] == "planned"
    assert after["run_status"]["state"] == "complete"
    # The deterministic realization is rebuilt byte-identically from the
    # unchanged recorded authorities.
    authorities = _rebuilt_authorities(store, env, run_id)
    assert authorities.realization.identifier == result.execution.world_realization_id
    assert authorities.realization.content_hash == result.execution.world_realization_content_hash


def test_a11_caller_draft_remains_unchanged() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=2)
    draft_before = copy.deepcopy(draft)
    execute_adaptive_run(store, tenant_id=TENANT, run_id=run_id, draft=draft)
    assert draft == draft_before
    assert draft.final_decision_step == 2
    assert draft.external_bundle_draft is None


def test_a12_tenant_isolation_and_defensive_copy_retrieval() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    result = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    # A foreign tenant can never observe the run's execution.
    with pytest.raises(AdaptiveRunTrajectoryExecutionNotFoundError):
        store.get_adaptive_run_trajectory_execution(tenant_id="tenant-other", run_id=run_id)
    reloaded = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    # Defensive copies: mutating the returned objects never alters the
    # stored record or the returned result of the execution.
    reloaded.model_copy(update={"run_id": "mutated"})
    store.get_run_status(TENANT, run_id).model_copy(update={"state": RunState.PLANNED})
    assert store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id) == (
        result.execution
    )
    assert store.get_run_status(TENANT, run_id).state is RunState.COMPLETE
    assert result.status.state is RunState.COMPLETE


def test_a13_deterministic_independent_environments_byte_identical() -> None:
    first = _build_env()
    second = _build_env()
    first_store, first_run_id, _first_plan, _first_status = _planned_run(first)
    second_store, second_run_id, _second_plan, _second_status = _planned_run(second)
    first_result = execute_adaptive_run(
        first_store,
        tenant_id=TENANT,
        run_id=first_run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    second_result = execute_adaptive_run(
        second_store,
        tenant_id=TENANT,
        run_id=second_run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=2),
    )
    assert first_result.execution.model_dump(mode="json") == second_result.execution.model_dump(
        mode="json"
    )
    assert first_result.execution == second_result.execution
    assert first_result.status.model_dump(mode="json") == second_result.status.model_dump(
        mode="json"
    )
    assert first_run_id == second_run_id


def test_a14_reordered_run_plan_set_is_deterministic() -> None:
    # Resolution of the recorded run plan is by deterministic identifier;
    # an extra plan in either order changes nothing.
    def run_with(order: int) -> dict[str, Any]:
        env = _build_env()
        store = env.store
        campaign = store.get_campaign(TENANT, CAMPAIGN)
        world = store.get_world(TENANT, env.world_id)
        seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
        candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
        plan_input_hash = run_input_hash(
            world_content_hash=world.content_hash,
            strategy=candidates["mock-baseline"],
            seed=seed,
            runtime_version=RUNTIME_VERSION,
        )
        run_plan = RunPlan(
            identifier="run-plan-c03a",
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            world_version_id=env.world_id,
            strategy_candidate_id="mock-baseline",
            scenario_seed_id=SEED_ID,
            runtime_version=RUNTIME_VERSION,
            input_hash=plan_input_hash,
            created_at=NOW,
        )
        extra = run_plan.model_copy(update={"identifier": "run-plan-extra"})
        if order == 0:
            store.put_run_plans(TENANT, CAMPAIGN, (extra, run_plan))
        else:
            store.put_run_plans(TENANT, CAMPAIGN, (run_plan, extra))
        run_id = run_identifier(run_plan)
        status = RunStatus(
            identifier=f"status-{run_id}",
            tenant_id=TENANT,
            run_id=run_id,
            campaign_id=CAMPAIGN,
            run_plan_id=run_plan.identifier,
            state=RunState.PLANNED,
            runtime_version=RUNTIME_VERSION,
            input_hash=plan_input_hash,
            event_hash=None,
            created_at=NOW,
            changed_at=NOW,
        )
        store.put_run_status(TENANT, run_id, status)
        result = execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
        )
        assert result.status.state is RunState.COMPLETE
        return result.execution.model_dump(mode="json")

    assert run_with(0) == run_with(1)


# ---------------------------------------------------------------------------
# B. Typed safe atomic rejections
# ---------------------------------------------------------------------------


def test_b1_unknown_and_foreign_run_rejected_atomically() -> None:
    env = _build_env()
    store, _run_id, _run_plan, _planned_status = _planned_run(env)
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError) as unknown:
        execute_adaptive_run(store, tenant_id=TENANT, run_id="run-unknown", draft=draft)
    assert unknown.value.reason is not None
    before = _surface(store, _run_id, env.world_id)
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError) as foreign:
        execute_adaptive_run(store, tenant_id="tenant-other", run_id=_run_id, draft=draft)
    assert foreign.value.reason is not None
    assert _surface(store, _run_id, env.world_id) == before


def test_b2_wrong_runtime_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"runtime_version": "3.0.0"}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


@pytest.mark.parametrize(
    "starting_state",
    [RunState.RUNNING, RunState.COMPLETE, RunState.FAILED],
)
def test_b3_running_complete_failed_starting_state_rejected_atomically(
    starting_state: RunState,
) -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"state": starting_state}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b4_invalid_status_identifier_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"identifier": "status-forged"}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b5_status_run_identity_mismatch_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"run_id": "run-other"}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b6_invalid_campaign_authority_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"campaign_id": "campaign-other"}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b7_missing_run_plan_in_recorded_set_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, run_plan, _status = _planned_run(env)
    # The recorded plan set is replaced by a set without the recorded
    # run plan (missing/extra/reordered-tampered set): resolution by the
    # deterministic run-plan identifier must fail atomically.
    other = run_plan.model_copy(update={"identifier": "run-plan-other"})
    store.put_run_plans(TENANT, CAMPAIGN, (other,))
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b8_corrupt_run_plan_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, run_plan, _status = _planned_run(env)
    store.put_run_plans(
        TENANT,
        CAMPAIGN,
        (run_plan.model_copy(update={"runtime_version": "3.0.0"}),),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b9_status_planning_input_hash_disagreement_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, status = _planned_run(env)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"input_hash": "0" * 64}),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b10_campaign_not_exactly_compiled_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    campaign_status = store.get_campaign_status(TENANT, CAMPAIGN)
    store.update_campaign_status(
        TENANT,
        CAMPAIGN,
        CampaignStatus(
            identifier=campaign_status.identifier,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            state=CampaignState.RUNNING,
            changed_at=NOW,
            message="campaign running",
        ),
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b11_corrupt_world_manifest_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    world = store.get_world(TENANT, env.world_id)
    manifest = store.get_manifest(TENANT, env.world_id)
    # A stored world whose embedded body no longer agrees with the
    # manifest fails the independent snapshot verification atomically.
    forged = world.model_copy(update={"world": {**world.world, "content_hash": "0" * 64}})
    store.put_world(forged, manifest)
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b12_missing_and_corrupt_policy_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    del store._adaptive_policies[(TENANT, CAMPAIGN)]
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )
    store._adaptive_policies[(TENANT, CAMPAIGN)] = policy.model_copy(update={"policy_id": "forged"})
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b13_missing_and_corrupt_declaration_rejected_atomically() -> None:
    # Missing bound declaration: proof on a dedicated fresh store.
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    key = (TENANT, "scenario-1", env.world_id, "obs-level")
    del store._runtime_observation_declarations[key]
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    draft_before = copy.deepcopy(draft)
    excinfo = _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        draft,
    )
    assert excinfo.value.reason == "adaptive policy bound authority missing"
    assert draft == draft_before

    # Corrupt bound declaration: proof on a second dedicated fresh store.
    # The expected store collection key is retained; a genuinely forged
    # declaration is stored at it, and the real declaration getter performs
    # the identity/integrity verification on read.
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    key = (TENANT, "scenario-1", env.world_id, "obs-level")
    declaration = store.get_runtime_observation_declaration(
        TENANT, "scenario-1", env.world_id, "obs-level"
    )
    store._runtime_observation_declarations[key] = declaration.model_copy(
        update={"observation_id": "forged"}
    )
    forged_before = store._runtime_observation_declarations[key].model_dump(mode="json")
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    draft_before = copy.deepcopy(draft)
    excinfo = _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        draft,
    )
    assert excinfo.value.reason == "adaptive policy authority corrupt"
    assert store._runtime_observation_declarations[key].model_dump(mode="json") == forged_before
    assert draft == draft_before


def test_b14_missing_and_mismatched_action_plans_rejected_atomically() -> None:
    # Missing plans collection: proof on a dedicated fresh store.
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    del store._strategy_trajectory_plans[(TENANT, CAMPAIGN)]
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    draft_before = copy.deepcopy(draft)
    excinfo = _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        draft,
    )
    assert excinfo.value.reason == "adaptive policy bound authority missing"
    assert draft == draft_before

    # Mismatched action plans: proof on a second dedicated fresh store. The
    # campaign collection key and referenced plan identifiers are retained;
    # a field is forged so it disagrees with the policy's exact
    # TrajectoryPlanBinding, and the binding-agreement check rejects it.
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    store._strategy_trajectory_plans[(TENANT, CAMPAIGN)] = tuple(
        plan.model_copy(update={"state_model_id": "sm-forged"}) for plan in plans
    )
    forged_before = tuple(
        plan.model_dump(mode="json")
        for plan in store._strategy_trajectory_plans[(TENANT, CAMPAIGN)]
    )
    draft = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    draft_before = copy.deepcopy(draft)
    excinfo = _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        draft,
    )
    assert excinfo.value.reason == "adaptive policy authority corrupt"
    assert (
        tuple(
            plan.model_dump(mode="json")
            for plan in store._strategy_trajectory_plans[(TENANT, CAMPAIGN)]
        )
        == forged_before
    )
    assert draft == draft_before


def test_b15_missing_and_mismatched_uncertainty_authority_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    stored_model = store.get_world_uncertainty_model(TENANT, "scenario-1")
    del store._world_uncertainty_models[(TENANT, "scenario-1")]
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )
    # A stored record whose deterministic identity no longer matches its
    # content is corrupt on read; the derivation never runs.
    store._world_uncertainty_models[(TENANT, "scenario-1")] = stored_model.model_copy(
        update={"bindings": ()}
    )
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionIntegrityError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b16_missing_scenario_seed_authority_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    forged_campaign = campaign.model_copy(
        update={
            "seed_ensemble": tuple(
                seed for seed in campaign.seed_ensemble if seed.identifier != SEED_ID
            )
        }
    )
    store._campaigns[(TENANT, CAMPAIGN)] = forged_campaign
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0),
    )


def test_b17_missing_required_external_bundle_rejected_atomically() -> None:
    env = _build_env_external()
    assert env.bundle_draft is not None
    store, run_id, _run_plan, _status = _planned_run(env)
    del store._external_observation_input_bundles[(TENANT, CAMPAIGN, SEED_ID)]
    _assert_atomic_rejection(
        AdaptiveRunTrajectoryExecutionValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=env.bundle_draft
        ),
    )


def test_b18_mismatched_caller_external_bundle_draft_rejected_atomically() -> None:
    env = _build_env_external()
    assert env.bundle_draft is not None
    store, run_id, _run_plan, _status = _planned_run(env)
    forged_entries = tuple(
        ExternalObservationInputValueDraft(
            observation_id=value.observation_id,
            source_step_index=value.source_step_index,
            value=999 if value.observation_id == "obs-a" else value.value,
        )
        for value in env.bundle_draft.entries
    )
    mismatched = ExternalObservationInputBundleDraft(
        entries=forged_entries,
        accepted_at=env.bundle_draft.accepted_at,
    )
    _assert_atomic_rejection(
        RuntimeObservationEventValidationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(final_decision_step=0, external_bundle_draft=mismatched),
    )


def test_b19_invalid_horizon_types_and_negative_horizon_rejected_atomically() -> None:
    for invalid in INVALID_HORIZONS:
        env = _build_env()
        store, run_id, _run_plan, _status = _planned_run(env)
        draft = AdaptiveRunExecutionBuildDraft(final_decision_step=invalid)
        _assert_atomic_rejection(
            AdaptiveRunTrajectoryExecutionValidationError,
            store,
            run_id,
            env,
            draft,
        )


def test_b20_pre_existing_execution_rejected_and_never_overwritten() -> None:
    env = _build_env()
    store, run_id, _run_plan, _planned_status = _planned_run(env)
    first = execute_adaptive_run(
        store,
        tenant_id=TENANT,
        run_id=run_id,
        draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
    )
    execution_before = store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id)
    status_before = store.get_run_status(TENANT, run_id)
    assert status_before.state is RunState.COMPLETE
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError) as excinfo:
        execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=1),
        )
    assert excinfo.value.reason is not None
    # A duplicate execution is never overwritten or re-derived; the
    # completed run and its artifact are byte-identical.
    assert store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id) == (
        execution_before
    )
    assert store.get_run_status(TENANT, run_id) == status_before
    assert store.get_adaptive_run_trajectory_execution(tenant_id=TENANT, run_id=run_id) == (
        first.execution
    )
    assert len(store._adaptive_run_trajectory_executions) == 1


def test_b21_missing_later_step_external_evidence_rejected_atomically() -> None:
    env = _build_env_external()
    assert env.bundle_draft is not None
    store, run_id, _run_plan, _status = _planned_run(env)
    _assert_atomic_rejection(
        AdaptiveConditionMissingObservationError,
        store,
        run_id,
        env,
        AdaptiveRunExecutionBuildDraft(
            final_decision_step=2, external_bundle_draft=env.bundle_draft
        ),
    )


def test_b22_invalid_caller_types_rejected_atomically() -> None:
    env = _build_env()
    store, run_id, _run_plan, _status = _planned_run(env)
    before = _surface(store, run_id, env.world_id)
    invalid_tenant: Any = 123
    invalid_run: Any = 456
    invalid_draft: Any = object()
    for tenant_value, run_value in ((invalid_tenant, run_id), (TENANT, invalid_run)):
        with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
            execute_adaptive_run(
                store,
                tenant_id=tenant_value,
                run_id=run_value,
                draft=AdaptiveRunExecutionBuildDraft(final_decision_step=0),
            )
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        execute_adaptive_run(
            store,
            tenant_id=TENANT,
            run_id=run_id,
            draft=invalid_draft,
        )
    assert _surface(store, run_id, env.world_id) == before


# ---------------------------------------------------------------------------
# C. Source-boundary proofs
# ---------------------------------------------------------------------------


def _service_source() -> str:
    return inspect.getsource(service_module)


def _service_tree() -> ast.Module:
    return ast.parse(_service_source())


def test_c1_exactly_one_builder_call_site() -> None:
    tree = _service_tree()
    builder_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_adaptive_run_trajectory_execution"
    ]
    assert len(builder_calls) == 1


def test_c2_run_status_and_aggregate_write_order() -> None:
    tree = _service_tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute_adaptive_run"
    )
    status_writes: list[tuple[int, str]] = []
    aggregate_writes: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        value = node.func.value
        if not isinstance(value, ast.Name) or value.id != "store":
            continue
        if node.func.attr == "put_run_status":
            status_name = (
                node.args[-1].id if node.args and isinstance(node.args[-1], ast.Name) else "?"
            )
            status_writes.append((node.lineno, status_name))
        elif node.func.attr == "put_adaptive_run_trajectory_execution":
            aggregate_writes.append(node.lineno)
    builder_lineno = next(
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_adaptive_run_trajectory_execution"
    )
    assert len(status_writes) == 2
    assert len(aggregate_writes) == 1
    assert {name for _line, name in status_writes} == {"running", "complete"}
    assert builder_lineno < status_writes[0][0] < aggregate_writes[0] < status_writes[1][0]


def test_c3_no_forbidden_store_surfaces_and_no_adapters() -> None:
    tree = _service_tree()
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (
        attributes
        & {
            "put_run_events",
            "put_input_integrity_manifest",
            "put_replay_manifest",
            "record_operational_activity",
            "update_campaign_status",
            "put_adaptive_run_trajectory_replay_manifest",
            "delete",
            "upsert",
            "put_world",
            "put_policy",
            "put_campaign",
            "put_run_plans",
            "put_adaptive_policy",
        }
    )
    lowered = _service_source().lower()
    assert "adapters" not in lowered


def test_c4_no_clock_random_uuid_network_or_filesystem_imports() -> None:
    tree = _service_tree()
    roots: set[str] = set()
    kalhas_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("kalhas"):
                kalhas_modules.add(node.module)
    assert roots <= {"__future__", "dataclasses", "typing", "kalhas"}
    forbidden_roots = {
        "datetime",
        "time",
        "random",
        "uuid",
        "os",
        "sys",
        "socket",
        "urllib",
        "requests",
        "subprocess",
        "hashlib",
        "pathlib",
        "json",
        "importlib",
    }
    assert not (roots & forbidden_roots)
    assert all(
        module.startswith("kalhas.application.") or module.startswith("kalhas.contracts.v1.")
        for module in kalhas_modules
    )
    name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (
        name_ids & {"datetime", "time", "uuid", "random", "now", "utcnow", "monotonic", "time_ns"}
    )


def test_c5_exact_minimal_all() -> None:
    assert service_module.__all__ == ["AdaptiveRunExecutionResult", "execute_adaptive_run"]


def test_c6_exact_public_signature_boundary() -> None:
    signature = inspect.signature(execute_adaptive_run)
    parameters = list(signature.parameters.values())
    assert [parameter.name for parameter in parameters] == ["store", "tenant_id", "run_id", "draft"]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters[1:])
    assert not any(
        parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for parameter in parameters
    )


def test_c7_frozen_slotted_result_dataclass() -> None:
    assert dataclasses.is_dataclass(AdaptiveRunExecutionResult)
    assert set(AdaptiveRunExecutionResult.__dataclass_fields__) == {"status", "execution"}
    hints = get_type_hints(AdaptiveRunExecutionResult)
    assert hints["status"] is RunStatus
    assert hints["execution"] is AdaptiveRunTrajectoryExecution
    params: Any = getattr(AdaptiveRunExecutionResult, "__dataclass_params__", None)
    assert params is not None
    assert params.frozen is True
    assert AdaptiveRunExecutionResult.__dataclass_fields__["status"].default is (
        dataclasses.MISSING
    )
    assert AdaptiveRunExecutionResult.__dataclass_fields__["execution"].default is (
        dataclasses.MISSING
    )
    assert hasattr(AdaptiveRunExecutionResult, "__slots__")
