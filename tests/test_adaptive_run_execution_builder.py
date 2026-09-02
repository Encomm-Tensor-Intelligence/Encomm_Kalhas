"""H28-S06C2C-C02 core proof sections A-E for the adaptive run execution builder.

Ports the already-green C02 builder smoke foundation
(``Temp/h28_builder_smoke.py``) into the permanent test module. Real
stores, compiled world with a declared uncertainty model, deterministic
world realization with the real sm-b.weight override, real declarations,
real bound adaptive policies, complete real action-plan catalogs, real
run authorities, and the real single-step orchestrator behind the
builder. No mocks, monkeypatch, skip, xfail, noqa, or type-ignore; no
faked persistence; no duplicated decision algorithm; no weakened
assertions.

Sections:

- A. successful construction (strict draft, horizons, decision counts,
  exact cardinalities, final authority verifier acceptance);
- B. canonical sequence and causality (contiguous indices/positions,
  canonical declaration-identifier ordering, legal-step evidence use,
  future/delayed/terminal evidence cannot influence earlier decisions);
- C. real adaptive behavior (observation-driven selection, exactly one
  real switch at step 1, switch budgets, stored trajectory-plan
  agreement);
- D. state evolution (realization-derived initial states, the real
  deterministic override, the final-to-next chain, exact model-key
  coverage, recomputed hashes, unchanged caller inputs);
- E. observation and external evidence (delay-0/delay-1/terminal
  ledgers, the exact step-0 external bundle consumption, the typed
  missing-evidence rejection at a later step with full atomicity, and
  the reversed-catalog core integrity rejection);
- F. aggregate identity and provenance (stored authority agreement,
  exact policy identity on every evidence node, canonical plan-set
  ordering and recomputed hashes, the decision-count horizon
  derivation, exact identifier/content-hash recomputation, and the
  rejection of minimally corrupted identity/hash/provenance copies);
- G. determinism and idempotence (byte-identical independent
  environments, repeated construction, mapping-insertion and
  observation-order independence, and identifier rotation only on
  genuine identity/content changes);
- H. purity and failure atomicity (deep fingerprints of the store,
  activity, authorities, catalogs, and drafts across successful and
  rejected calls);
- I. strict rejection matrix (the full builder-boundary family table
  with exact typed errors, non-leaking generic public messages, and
  atomicity, plus forged-evidence and corrupted-aggregate rejections
  by the final authority verifier);
- J. source and architecture boundaries (AST-level assertions that the
  builder stays inside KALHAS responsibilities, delegates to the
  established seams, and performs no store writes, status mutation,
  activity, clock, randomness, network, or callback surface).
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import kalhas.application.adaptive_run_execution_builder as adaptive_builder_module
import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.adaptive_condition_errors import (
    AdaptiveConditionMissingObservationError,
)
from kalhas.application.adaptive_policy_binding_service import (
    ActionStrategyMapping,
    AdaptivePolicyBindingRequest,
    bind_adaptive_policy,
)
from kalhas.application.adaptive_run_execution_builder import (
    RUNTIME_VERSION,
    AdaptiveRunExecutionBuildDraft,
    build_adaptive_run_trajectory_execution,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_input_hash,
    adaptive_run_trajectory_execution_content_hash,
    adaptive_run_trajectory_execution_identifier,
    verify_adaptive_run_trajectory_execution_identity,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    AdaptiveRunExecutionAuthorities,
    verify_adaptive_run_trajectory_execution_authority,
)
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
from kalhas.application.realization_trajectory_runtime import (
    realized_initial_state,
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.application.runtime_observation_declaration_service import (
    ExternalObservationDraft,
    RuntimeObservationDeclarationDraft,
    StateFieldObservationDraft,
    declare_runtime_observation_declaration,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventValidationError,
)
from kalhas.application.runtime_observation_event_service import (
    ObservationStepDraft,
    ObservationStepResult,
    derive_observation_step,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_compiler import compile_world
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.adaptive_policy import (
    AdaptivePolicyDraft,
    AdaptivePolicyRuleDraft,
    ConditionComparisonLeaf,
    TrajectoryPlanBinding,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import (
    AdaptiveRunTrajectoryExecution,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    NoObservationNoise,
    ObservationTiming,
    RuntimeObservationEvent,
)
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateFieldDefinition, StateValueKind
from kalhas.contracts.v1.world_realization import UniformDistribution

from tests.phase4_helpers import NOW, TENANT, build_scenario, prepare

CAMPAIGN = "campaign-1"
SEED_ID = "seed-1"
DECLARED_AT = datetime(2026, 1, 8, 9, 30, 0, tzinfo=UTC)
BOUND_AT = datetime(2026, 1, 9, 12, 0, 0, tzinfo=UTC)
_TIMING_0 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=0)
_TIMING_DELAY1 = ObservationTiming(start_step=0, every_n_steps=1, delay_steps=1)
_NO_NOISE = NoObservationNoise(kind="none", draw_count=0)

#: The real deterministic realization override on sm-b.weight proven by
#: the C02 smoke on the exact compiled world and seed.
SM_B_WEIGHT_OVERRIDE = 7.610971362184338

#: Draft horizons the builder must reject (typed as ``Any`` only so the
#: strict-rejection proof can hand each value to the typed draft).
INVALID_HORIZONS: tuple[Any, ...] = (-1, True, "2")


def _leaf(
    condition_id: str,
    observation_id: str,
    kind: Literal["integer", "number"],
    threshold: int | float,
    missing: Literal["false", "error"] = "false",
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
    kind: Literal["integer", "number"],
    threshold: int | float,
    missing: Literal["false", "error"] = "false",
) -> AdaptivePolicyRuleDraft:
    return AdaptivePolicyRuleDraft(
        rule_id=rule_id,
        priority=priority,
        target_action_id=target,
        enter_condition=_leaf(f"{rule_id}-a", observation_id, kind, threshold, missing),
        retain_condition=_leaf(f"{rule_id}-r", observation_id, kind, threshold, missing),
        per_rule_switch_budget=1,
    )


def _policy_draft() -> AdaptivePolicyDraft:
    return AdaptivePolicyDraft(
        request_id="req-1",
        actions=("act-1", "act-2"),  # bind only the delay-0 declaration
        initial_action_id="act-1",
        fallback_action_id="act-2",
        rules=(
            _rule("rule-1", 0, "act-2", "obs-level", "integer", 0),
            _rule("rule-2", 1, "act-1", "obs-level", "integer", -1000),
        ),
        minimum_dwell_steps=1,
        cooldown_steps=1,
        global_switch_budget=2,
    )


def _binding_request(policy_id: str, request_id_postfix: str = "") -> AdaptivePolicyBindingRequest:
    return AdaptivePolicyBindingRequest(
        policy_id=policy_id + request_id_postfix,
        policy_version="1.0.0",
        action_mappings=(
            ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
            ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
        ),
        bound_at=BOUND_AT,
        metadata={},
    )


def _new_store_with_world() -> tuple[InMemoryScenarioStore, str]:
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
    # The uncertainty model must exist before the world is compiled; the
    # compiled world then embeds it and every realization carries a real
    # deterministic override on sm-b.weight.
    uncertainty_model = declare_world_uncertainty_model(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        bindings=(
            UncertaintyBindingDraft(
                manifest_id="manifest-1",
                state_model_id="sm-b",
                state_field_id="weight",
                distribution=UniformDistribution(kind="uniform", low=5.0, high=10.0),
            ),
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
        uncertainty_model=uncertainty_model,
    )
    store.put_world(compiled.version, compiled.manifest)
    return store, compiled.version.identifier


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


@dataclass(frozen=True)
class Env:
    store: InMemoryScenarioStore
    world_id: str
    catalogs: tuple[ModelTrajectoryCatalog, ...]
    realization_id: str
    realization_hash: str
    sm_a: str
    sm_b: str
    override_value: JsonValue
    bundle_draft: ExternalObservationInputBundleDraft | None = None


def _build_env() -> Env:
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        # Campaign preparation supports only 1.0.0/2.0.0; the runtime-4
        # layer begins at the policy, run plan, and run status chain.
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare_state_field(store, world_id, "obs-level", "level", _TIMING_0)
    # Declared but NOT policy-bound: delay-1 evidence exercises the
    # derivation/terminal ledger in the separate delay environment.
    _declare_state_field(store, world_id, "obs-level-late", "level", _TIMING_DELAY1)
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=_policy_draft(),
        binding_request=_binding_request("policy-1"),
    )
    catalog = extract_world_catalog(store.get_world(TENANT, world_id))
    seed = next(
        s for s in store.get_campaign(TENANT, CAMPAIGN).seed_ensemble if s.identifier == SEED_ID
    )
    realization = build_world_realization(
        world=store.get_world(TENANT, world_id),
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
        seed=seed,
        realized_at=NOW,
    )
    override = next(
        o for o in realization.realized_initial_state_overrides if o.state_field_id == "weight"
    )
    return Env(
        store=store,
        world_id=world_id,
        catalogs=_catalogs_for(store, world_id),
        realization_id=realization.identifier,
        realization_hash=realization.content_hash,
        sm_a=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a").identifier,
        sm_b=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b").identifier,
        override_value=override.value,
    )


def _complete_authorities(env: Env) -> tuple[AdaptiveRunExecutionAuthorities, str]:
    """The full real authority chain per the established store-test idiom."""
    store = env.store
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
        realized_at=NOW,
    )
    plans = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    plans_by_id = {p.identifier: p for p in plans}
    candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
    plan_input_hash = run_input_hash(
        world_content_hash=world.content_hash,
        strategy=candidates["mock-baseline"],
        seed=seed,
        runtime_version=RUNTIME_VERSION,
    )
    run_plan = RunPlan(
        identifier="run-plan-1",
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
        state=RunState.RUNNING,
        runtime_version=RUNTIME_VERSION,
        input_hash=plan_input_hash,
        created_at=NOW,
        changed_at=NOW,
    )
    store.put_run_status(TENANT, run_id, status)
    campaign_status = store.get_campaign_status(TENANT, CAMPAIGN)
    assert campaign_status.state is CampaignState.COMPILED
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
    if env.bundle_draft is not None:
        bundle = store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID
        )
    authorities = AdaptiveRunExecutionAuthorities(
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
    return authorities, run_id


def _build_env_external() -> Env:
    """A real environment whose policy binds three external declarations,
    with a real accepted bundle that covers step 0 only (missing the
    entries every later step requires)."""
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    external_declarations: tuple[
        tuple[str, Literal["integer", "number"], Literal["false", "error"]], ...
    ] = (
        ("obs-a", "integer", "false"),
        ("obs-b", "number", "false"),
        ("obs-c", "integer", "error"),
    )
    for observation_id, kind, missing in external_declarations:
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
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=AdaptivePolicyDraft(
            request_id="req-ext",
            actions=("act-1", "act-2"),
            initial_action_id="act-1",
            fallback_action_id="act-2",
            rules=(
                # Every declared external observation is a real policy
                # observation binding: rule-1 on obs-a (integer), rule-2
                # on obs-b (number), rule-3 on obs-c (integer).
                # Rule-3 declares missing behavior "error" so a later
                # step without supplied external evidence fails with the
                # typed missing-evidence error.
                _rule("rule-1", 0, "act-1", "obs-a", "integer", 0),
                _rule("rule-2", 1, "act-2", "obs-b", "number", 0),
                _rule("rule-3", 2, "act-1", "obs-c", "integer", 0, missing="error"),
            ),
            minimum_dwell_steps=1,
            cooldown_steps=1,
            global_switch_budget=2,
        ),
        binding_request=AdaptivePolicyBindingRequest(
            policy_id="policy-ext",
            policy_version="1.0.0",
            action_mappings=(
                ActionStrategyMapping(action_id="act-1", strategy_candidate_id="mock-baseline"),
                ActionStrategyMapping(action_id="act-2", strategy_candidate_id="mock-balanced"),
            ),
            bound_at=BOUND_AT,
            metadata={},
        ),
    )
    identifiers = {
        observation_id: store.get_runtime_observation_declaration(
            TENANT, "scenario-1", world_id, observation_id
        ).identifier
        for observation_id in ("obs-a", "obs-b", "obs-c")
    }
    ordered = sorted(
        (("obs-a", 8), ("obs-b", 2.0), ("obs-c", 1)),
        key=lambda entry: identifiers[entry[0]],
    )
    draft = ExternalObservationInputBundleDraft(
        entries=tuple(
            ExternalObservationInputValueDraft(
                observation_id=observation_id, source_step_index=0, value=value
            )
            for observation_id, value in ordered
        ),
        accepted_at=BOUND_AT,
    )
    accept_external_observation_input_bundle(
        store, tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID, draft=draft
    )
    catalogs = _catalogs_for(store, world_id)
    return Env(
        store=store,
        world_id=world_id,
        catalogs=catalogs,
        realization_id="",
        realization_hash="",
        sm_a=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a").identifier,
        sm_b=store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-b").identifier,
        override_value=0.0,
        bundle_draft=draft,
    )


def _build_delay_env() -> tuple[InMemoryScenarioStore, str]:
    """A real dedicated environment where the delay-1 declaration is
    policy-bound, so the real derivation primitive sources both
    observations across the three-step ledger."""
    store, world_id = _new_store_with_world()
    prepare(
        store,
        world_id,
        runtime_version="2.0.0",
        legion=MockLegionAdapter(),
        campaign_id=CAMPAIGN,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=MockLegionAdapter(declared_transition_sequences={"mock-baseline": ("t-1", "t-1")}),
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
    )
    _declare_state_field(store, world_id, "obs-level", "level", _TIMING_0)
    _declare_state_field(store, world_id, "obs-level-late", "level", _TIMING_DELAY1)
    bind_adaptive_policy(
        store,
        tenant_id=TENANT,
        campaign_id=CAMPAIGN,
        draft=AdaptivePolicyDraft(
            request_id="req-delay",
            actions=("act-1", "act-2"),
            initial_action_id="act-1",
            fallback_action_id="act-2",
            rules=(
                _rule("rule-1", 0, "act-2", "obs-level", "integer", 0),
                _rule("rule-2", 1, "act-1", "obs-level", "integer", -1000),
                _rule("rule-3", 2, "act-1", "obs-level-late", "integer", 0),
            ),
            minimum_dwell_steps=1,
            cooldown_steps=1,
            global_switch_budget=2,
        ),
        binding_request=_binding_request("policy-delay"),
    )
    return store, world_id


def _execution_count(store: InMemoryScenarioStore) -> int:
    return len(store._adaptive_run_trajectory_executions)


# ---------------------------------------------------------------------------
# Real shared environments (the builder is strictly read-only, so the
# module-scoped stores stay pristine across every proof).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env() -> Env:
    return _build_env()


@pytest.fixture(scope="module")
def authorities(env: Env) -> AdaptiveRunExecutionAuthorities:
    authorities_for_env, _run_id = _complete_authorities(env)
    return authorities_for_env


@pytest.fixture(scope="module")
def delay_env() -> tuple[InMemoryScenarioStore, str]:
    return _build_delay_env()


@pytest.fixture(scope="module")
def delay_events(
    delay_env: tuple[InMemoryScenarioStore, str],
) -> tuple[RuntimeObservationEvent, ...]:
    """The complete three-step sourced-event ledger of both declared
    observations through the real derivation primitive."""
    store, _world_id = delay_env
    sm_a = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-a").identifier
    states_by_step: dict[int, dict[str, dict[str, JsonValue]]] = {
        0: {sm_a: {"level": 0, "ratio": 0.0, "status": "idle"}},
        1: {sm_a: {"level": 1, "ratio": 1.5, "status": "idle"}},
        2: {sm_a: {"level": 1, "ratio": 1.5, "status": "idle"}},
    }
    prior: tuple[RuntimeObservationEvent, ...] = ()
    collected: list[RuntimeObservationEvent] = []
    for step in (0, 1, 2):
        result: ObservationStepResult = derive_observation_step(
            store,
            tenant_id=TENANT,
            campaign_id=CAMPAIGN,
            scenario_seed_id=SEED_ID,
            draft=ObservationStepDraft(
                decision_step=step,
                final_decision_step=2,
                state=states_by_step[step],
                prior_events=prior,
            ),
        )
        collected.extend(result.new_events)
        prior = (*prior, *result.new_events)
    return tuple(collected)


@pytest.fixture(scope="module")
def external_env() -> Env:
    return _build_env_external()


@pytest.fixture(scope="module")
def external_authorities(external_env: Env) -> AdaptiveRunExecutionAuthorities:
    authorities_for_env, _run_id = _complete_authorities(external_env)
    return authorities_for_env


def _build(
    authorities_for_env: AdaptiveRunExecutionAuthorities,
    env_for_build: Env,
    final_decision_step: int,
) -> AdaptiveRunTrajectoryExecution:
    return build_adaptive_run_trajectory_execution(
        env_for_build.store,
        authorities=authorities_for_env,
        catalogs=env_for_build.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=final_decision_step,
            external_bundle_draft=env_for_build.bundle_draft,
        ),
    )


# ---------------------------------------------------------------------------
# A. Successful construction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("final_decision_step", "expected_decision_count"),
    [(0, 1), (1, 2), (2, 3)],
)
def test_a1_decision_count_equals_final_step_plus_one(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    final_decision_step: int,
    expected_decision_count: int,
) -> None:
    aggregate = _build(authorities, env, final_decision_step)
    assert type(aggregate) is AdaptiveRunTrajectoryExecution
    assert len(aggregate.decision_events) == expected_decision_count
    assert len(aggregate.decision_events) == final_decision_step + 1
    assert len(aggregate.policy_state_snapshots) == expected_decision_count
    assert len(aggregate.trajectory_results_by_decision) == expected_decision_count
    assert aggregate.decision_events[0].decision_step == 0
    assert aggregate.decision_events[-1].decision_step == final_decision_step
    assert aggregate.runtime_version == RUNTIME_VERSION


def test_a2_strict_draft_rejects_invalid_horizons(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    for invalid in INVALID_HORIZONS:
        with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
            build_adaptive_run_trajectory_execution(
                env.store,
                authorities=authorities,
                catalogs=env.catalogs,
                draft=AdaptiveRunExecutionBuildDraft(final_decision_step=invalid),
            )
    wrong_type: Any = "not-a-draft"
    with pytest.raises(AdaptiveRunTrajectoryExecutionValidationError):
        build_adaptive_run_trajectory_execution(
            env.store,
            authorities=authorities,
            catalogs=env.catalogs,
            draft=wrong_type,
        )


def test_a3_exact_cardinalities_horizon_two(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert len(aggregate.decision_events) == 3
    assert len(aggregate.policy_state_snapshots) == 3
    assert len(aggregate.switch_events) == 1
    assert len(aggregate.trajectory_results_by_decision) == 3
    assert all(len(results) == 2 for results in aggregate.trajectory_results_by_decision)
    assert len(aggregate.observation_events) == 3
    verify_adaptive_run_trajectory_execution_identity(aggregate)
    verify_adaptive_run_trajectory_execution_authority(aggregate, authorities=authorities)


def test_a4_final_authority_verifier_accepts_produced_aggregates(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    zero = _build(authorities, env, 0)
    multi = _build(authorities, env, 2)
    for aggregate in (zero, multi):
        verify_adaptive_run_trajectory_execution_identity(aggregate)
        verify_adaptive_run_trajectory_execution_authority(aggregate, authorities=authorities)
        assert aggregate.executed_at == authorities.run_plan.created_at


# ---------------------------------------------------------------------------
# B. Canonical sequence and causality
# ---------------------------------------------------------------------------


def test_b1_contiguous_decision_step_indices(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert [event.decision_step for event in aggregate.decision_events] == [0, 1, 2]
    assert [snapshot.decision_step for snapshot in aggregate.policy_state_snapshots] == [0, 1, 2]


def test_b2_globally_contiguous_observation_sequence_positions(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    events = aggregate.observation_events
    assert [event.sequence_position for event in events] == list(range(3))


def test_b3_canonical_declaration_identifier_ordering(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    delay_env: tuple[InMemoryScenarioStore, str],
    delay_events: tuple[RuntimeObservationEvent, ...],
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    # The derivation schedule (and the available-event order) follows the
    # declaration IDENTIFIER order, never the observation-id order.
    delay_store, delay_world = delay_env
    ordered_delay = sorted(
        ("obs-level", "obs-level-late"),
        key=lambda observation_id: (
            delay_store.get_runtime_observation_declaration(
                TENANT, "scenario-1", delay_world, observation_id
            ).identifier
        ),
    )
    for step in (0, 1, 2):
        step_events = [e for e in delay_events if e.source_step_index == step]
        assert [e.observation_id for e in step_events] == ordered_delay
    # The external bundle consumed at step 0 is likewise derived in
    # canonical declaration-identifier order across all three bindings.
    external = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    ordered_external = sorted(
        ("obs-a", "obs-b", "obs-c"),
        key=lambda observation_id: external_authorities.declarations[observation_id].identifier,
    )
    assert [e.observation_id for e in external.observation_events] == ordered_external
    # With a single bound declaration the executed ledger is trivially
    # canonical as well.
    aggregate = _build(authorities, env, 2)
    assert {e.observation_id for e in aggregate.observation_events} == {"obs-level"}


def test_b4_evidence_used_only_at_its_legal_decision_step(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    delay_events: tuple[RuntimeObservationEvent, ...],
) -> None:
    aggregate = _build(authorities, env, 2)
    # Delay-0 evidence: each event is available exactly at its source
    # step, so it can legally influence only that decision.
    for event in aggregate.observation_events:
        assert event.available_decision_step == event.source_step_index
        assert event.available_decision_step == event.sequence_position
        assert not event.terminal
    # The decisions themselves consumed only the value legal at their
    # step: rule-1 (obs-level > 0) did NOT match at step 0 (value 0) and
    # matched at step 1 (value 1) - the step-1 value was never available
    # to the step-0 decision.
    decision_zero = aggregate.decision_events[0]
    first_rule_zero = decision_zero.rule_evaluation_evidence[0]
    assert first_rule_zero[0] == "rule-1"
    assert first_rule_zero[2] is False
    decision_one = aggregate.decision_events[1]
    assert decision_one.rule_evaluation_evidence[-1][0] == "rule-1"
    assert decision_one.rule_evaluation_evidence[-1][2] is True
    assert decision_one.selected_rule_id == "rule-1"
    # Delayed evidence sourced at step 0 is available only at step 1, and
    # the terminal event is available at no decision step: neither can
    # influence an earlier decision.
    late = [e for e in delay_events if e.observation_id == "obs-level-late"]
    first_late = next(e for e in late if e.source_step_index == 0)
    assert first_late.available_decision_step == 1 and not first_late.terminal
    terminal = [e for e in delay_events if e.terminal]
    assert terminal[0].available_decision_step is None


# ---------------------------------------------------------------------------
# C. Real adaptive behavior
# ---------------------------------------------------------------------------


def test_c1_observation_driven_selection(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert [e.exposed_observation_value for e in aggregate.observation_events] == [0, 1, 1]
    assert [e.selected_action_id for e in aggregate.decision_events] == [
        "act-1",
        "act-2",
        "act-2",
    ]
    # rule-1 (>0) matched only once its observation value became 1.
    assert aggregate.decision_events[1].selected_rule_id == "rule-1"
    assert aggregate.decision_events[1].decision_kind == "rule"
    assert aggregate.decision_events[2].decision_kind == "rule"


def test_c2_action_changes_exactly_once_at_step_one(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert [e.action_changed for e in aggregate.decision_events] == [False, True, False]
    assert aggregate.decision_events[1].current_action_id == "act-1"
    assert aggregate.decision_events[1].selected_action_id == "act-2"


def test_c3_switch_event_exists_exactly_for_the_real_change(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert len(aggregate.switch_events) == 1
    switch = aggregate.switch_events[0]
    assert switch.decision_step == 1
    assert switch.old_action_id == "act-1"
    assert switch.new_action_id == "act-2"
    assert switch.trigger_kind == "rule"
    assert switch.triggering_rule_id == "rule-1"


def test_c4_same_action_retention_creates_no_switch_event(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    # Step 0 retained act-1 and step 2 retained act-2; only the step-1
    # real change produced switch evidence.
    assert aggregate.decision_events[0].action_changed is False
    assert aggregate.decision_events[2].action_changed is False
    assert [s.decision_step for s in aggregate.switch_events] == [1]


def test_c5_switch_budgets_change_only_on_real_switches(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    snapshots = aggregate.policy_state_snapshots
    # Pre-decision snapshots: budgets untouched across the step-0 retain
    # and the step-2 same-action retain; decremented exactly once by the
    # step-1 real switch.
    assert [s.remaining_global_switch_budget for s in snapshots] == [2, 2, 1]
    assert snapshots[0].per_rule_remaining_budgets == (("rule-1", 1), ("rule-2", 1))
    assert snapshots[1].per_rule_remaining_budgets == (("rule-1", 1), ("rule-2", 1))
    assert snapshots[2].per_rule_remaining_budgets == (("rule-1", 0), ("rule-2", 1))
    assert snapshots[0].current_action_id == "act-1"
    assert snapshots[2].current_action_id == "act-2"
    assert snapshots[2].last_switch_decision_step == 1
    switch = aggregate.switch_events[0]
    assert switch.global_switch_budget_before == 2
    assert switch.global_switch_budget_after == 1
    assert switch.rule_switch_budget_before == 1
    assert switch.rule_switch_budget_after == 0


def test_c6_selected_action_agrees_with_selected_stored_trajectory_plans(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    for step in (0, 1, 2):
        selected = aggregate.decision_events[step].selected_action_id
        bound_plans = authorities.action_plans[selected]
        bound_by_model = {plan.state_model_identifier: plan.identifier for plan in bound_plans}
        results = aggregate.trajectory_results_by_decision[step]
        assert {r.state_model_identifier for r in results} == set(bound_by_model)
        for result in results:
            assert result.trajectory_plan_id in {plan.identifier for plan in bound_plans}
            assert result.trajectory_plan_id == bound_by_model[result.state_model_identifier]


# ---------------------------------------------------------------------------
# D. State evolution
# ---------------------------------------------------------------------------


def test_d1_initial_states_come_from_the_verified_world_realization(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    catalog_models = {
        model.identifier: model for model in extract_world_catalog(authorities.world).state_models
    }
    first_results = aggregate.trajectory_results_by_decision[0]
    by_model = {r.state_model_identifier: r for r in first_results}
    for model_id in (env.sm_a, env.sm_b):
        expected = realized_initial_state(
            state_model=catalog_models[model_id],
            realization=authorities.realization,
            run_id=authorities.run_id,
        )
        assert by_model[model_id].initial_state == expected
        assert by_model[model_id].initial_state_hash == state_hash(expected)


def test_d2_real_deterministic_override_on_sm_b_weight(env: Env) -> None:
    assert env.override_value == SM_B_WEIGHT_OVERRIDE


def test_d3_every_previous_final_state_becomes_the_next_pre_action_state(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    for position in (0, 1):
        current = aggregate.trajectory_results_by_decision[position]
        following = aggregate.trajectory_results_by_decision[position + 1]
        current_by = {r.state_model_identifier: r for r in current}
        following_by = {r.state_model_identifier: r for r in following}
        for model_id in current_by:
            assert current_by[model_id].final_state == following_by[model_id].initial_state
            assert current_by[model_id].final_state_hash == state_hash(
                current_by[model_id].final_state
            )
            assert current_by[model_id].initial_state_hash == state_hash(
                current_by[model_id].initial_state
            )


def test_d4_exact_and_complete_state_model_key_coverage(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    expected = {env.sm_a, env.sm_b}
    bound_models = {
        binding.state_model_identifier
        for action in authorities.policy.actions
        for binding in action.trajectory_plan_bindings
    }
    assert bound_models == expected
    for results in aggregate.trajectory_results_by_decision:
        assert {r.state_model_identifier for r in results} == expected
        assert sorted(r.state_model_identifier for r in results) == sorted(expected)


def test_d5_state_and_realized_trajectory_hashes_recompute_exactly(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    for results in aggregate.trajectory_results_by_decision:
        for result in results:
            assert result.initial_state_hash == state_hash(result.initial_state)
            assert result.final_state_hash == state_hash(result.final_state)
            assert realized_state_trajectory_result_content_hash(result) == result.content_hash


def test_d6_caller_catalogs_and_state_inputs_remain_unchanged(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    catalogs_before = copy.deepcopy(env.catalogs)
    realization_before = copy.deepcopy(authorities.realization.model_dump(mode="json"))
    action_plans_before = copy.deepcopy(authorities.action_plans)
    _build(authorities, env, 0)
    _build(authorities, env, 2)
    assert copy.deepcopy(env.catalogs) == catalogs_before
    assert authorities.realization.model_dump(mode="json") == realization_before
    assert authorities.action_plans == action_plans_before


# ---------------------------------------------------------------------------
# E. Observation and external evidence
# ---------------------------------------------------------------------------


def test_e1_delay_zero_evidence(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    events = aggregate.observation_events
    assert len(events) == 3
    assert [e.source_step_index for e in events] == [0, 1, 2]
    assert [e.available_decision_step for e in events] == [0, 1, 2]
    assert all(e.observation_id == "obs-level" for e in events)
    assert all(not e.terminal for e in events)
    assert all(
        e.observation_declaration_id == authorities.declarations["obs-level"].identifier
        for e in events
    )


def test_e2_delay_one_evidence_in_the_dedicated_real_environment(
    delay_events: tuple[RuntimeObservationEvent, ...],
) -> None:
    late = [e for e in delay_events if e.observation_id == "obs-level-late"]
    assert len(late) == 3
    first_late = next(e for e in late if e.source_step_index == 0)
    assert first_late.available_decision_step == 1 and not first_late.terminal
    assert next(e for e in late if e.source_step_index == 1).available_decision_step == 2


def test_e3_final_step_delayed_evidence_is_terminal(
    delay_events: tuple[RuntimeObservationEvent, ...],
) -> None:
    terminal = [e for e in delay_events if e.terminal]
    assert len(terminal) == 1
    assert terminal[0].observation_id == "obs-level-late"
    assert terminal[0].source_step_index == 2
    assert terminal[0].available_decision_step is None


def test_e4_exact_step_zero_external_bundle_accepted_and_consumed(
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    step0 = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    verify_adaptive_run_trajectory_execution_identity(step0)
    verify_adaptive_run_trajectory_execution_authority(step0, authorities=external_authorities)
    events = step0.observation_events
    assert len(events) == 3
    assert {event.observation_id for event in events} == {"obs-a", "obs-b", "obs-c"}
    assert all(event.status == "observed" for event in events)
    assert all(event.available_decision_step == 0 for event in events)
    bundle = external_authorities.external_bundle
    assert bundle is not None
    assert step0.external_observation_input_bundle_id == bundle.identifier


def test_e5_all_three_are_genuine_policy_observation_bindings(
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    bound = {binding.observation_id for binding in external_authorities.policy.observation_bindings}
    assert bound == {"obs-a", "obs-b", "obs-c"}


def test_e6_horizon_zero_external_build_consumes_exactly_three_events(
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    step0 = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    assert len(step0.decision_events) == 1
    assert step0.decision_events[0].decision_step == 0
    assert len(step0.observation_events) == 3
    assert {e.observation_id for e in step0.observation_events} == {"obs-a", "obs-b", "obs-c"}


def test_e7_missing_later_step_external_evidence_raises_typed_error(
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    with pytest.raises(AdaptiveConditionMissingObservationError) as excinfo:
        build_adaptive_run_trajectory_execution(
            external_env.store,
            authorities=external_authorities,
            catalogs=external_env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=2, external_bundle_draft=external_env.bundle_draft
            ),
        )
    assert excinfo.value.reason is not None


def test_e8_missing_evidence_rejection_is_atomic(
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    store = external_env.store
    bundle_draft = external_env.bundle_draft
    assert bundle_draft is not None
    executions_before = _execution_count(store)
    activity_before = list(store.list_operational_activity(TENANT))
    plans_before = store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
    policy_before = store.get_adaptive_policy(TENANT, CAMPAIGN)
    status_before = store.get_run_status(TENANT, external_authorities.run_id)
    campaign_before = copy.deepcopy(store.get_campaign(TENANT, CAMPAIGN).model_dump(mode="json"))
    world_before = copy.deepcopy(
        store.get_world(TENANT, external_env.world_id).model_dump(mode="json")
    )
    bundle_before = copy.deepcopy(
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID
        ).model_dump(mode="json")
    )
    catalogs_before = copy.deepcopy(external_env.catalogs)
    draft_before = copy.deepcopy(bundle_draft)

    with pytest.raises(AdaptiveConditionMissingObservationError):
        build_adaptive_run_trajectory_execution(
            store,
            authorities=external_authorities,
            catalogs=external_env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=2, external_bundle_draft=external_env.bundle_draft
            ),
        )

    assert _execution_count(store) == executions_before == 0
    assert list(store.list_operational_activity(TENANT)) == activity_before
    assert store.get_strategy_trajectory_plans(TENANT, CAMPAIGN) == plans_before
    assert store.get_adaptive_policy(TENANT, CAMPAIGN) == policy_before
    assert store.get_run_status(TENANT, external_authorities.run_id) == status_before
    assert store.get_campaign(TENANT, CAMPAIGN).model_dump(mode="json") == campaign_before
    assert store.get_world(TENANT, external_env.world_id).model_dump(mode="json") == world_before
    assert (
        store.get_external_observation_input_bundle(
            tenant_id=TENANT, campaign_id=CAMPAIGN, scenario_seed_id=SEED_ID
        ).model_dump(mode="json")
        == bundle_before
    )
    assert copy.deepcopy(external_env.catalogs) == catalogs_before
    assert bundle_draft == draft_before


def test_e9_reversed_catalogs_rejected_as_core_integrity(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    # The real orchestrator ENFORCES canonical catalog order; a reversed
    # catalog tuple is rejected with the typed integrity error before any
    # step evidence exists.
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        build_adaptive_run_trajectory_execution(
            env.store,
            authorities=authorities,
            catalogs=tuple(reversed(env.catalogs)),
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=0),
        )
    assert _execution_count(env.store) == 0


# ---------------------------------------------------------------------------
# Shared module-level regressions of the isolated proofs (compact:
# determinism and the executed environment's read-only purity).
# ---------------------------------------------------------------------------


def test_module_determinism_of_repeated_builds(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    first = _build(authorities, env, 2)
    second = _build(authorities, env, 2)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert second == first


# ---------------------------------------------------------------------------
# Shared F-J helpers
# ---------------------------------------------------------------------------


def _replace_authorities(
    authorities: AdaptiveRunExecutionAuthorities,
    **updates: Any,
) -> AdaptiveRunExecutionAuthorities:
    """A detached modification of the frozen authority carrier."""
    return dataclasses.replace(authorities, **updates)


def _call_build(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    step: int,
) -> AdaptiveRunTrajectoryExecution:
    """Build through the established helper with the matrix's (env, authorities) order."""
    return _build(authorities, env, step)


def _recompute_run_input_hash(
    authorities: AdaptiveRunExecutionAuthorities,
    aggregate: AdaptiveRunTrajectoryExecution,
    horizon: int,
) -> str:
    """The frozen runtime-4 input digest recomputed exactly like the builder."""
    return adaptive_run_input_hash(
        run_plan_id=authorities.run_plan.identifier,
        run_plan_input_hash=authorities.run_plan.input_hash,
        campaign_id=authorities.campaign.identifier,
        world_version_id=authorities.world.identifier,
        world_content_hash=authorities.world.content_hash,
        scenario_seed_id=authorities.seed.identifier,
        seed_content_hash_value=seed_content_hash(authorities.seed),
        world_realization_id=authorities.realization.identifier,
        world_realization_content_hash=authorities.realization.content_hash,
        adaptive_policy_identifier=authorities.policy.identifier,
        adaptive_policy_content_hash=authorities.policy.content_hash,
        trajectory_plan_set_hash=aggregate.trajectory_plan_set_hash,
        external_observation_input_bundle_id=aggregate.external_observation_input_bundle_id,
        external_observation_input_bundle_content_hash=(
            aggregate.external_observation_input_bundle_content_hash
        ),
        final_decision_step=horizon,
    )


def _remap(
    aggregate: AdaptiveRunTrajectoryExecution,
    field: str,
    transform: Any,
) -> AdaptiveRunTrajectoryExecution:
    """A detached copy of one evidence tuple with every item transformed."""
    return aggregate.model_copy(
        update={field: tuple(transform(item) for item in getattr(aggregate, field))}
    )


def _forge_trajectory_results(
    aggregate: AdaptiveRunTrajectoryExecution,
    transform: Any,
) -> AdaptiveRunTrajectoryExecution:
    return aggregate.model_copy(
        update={
            "trajectory_results_by_decision": tuple(
                tuple(transform(result) for result in results)
                for results in aggregate.trajectory_results_by_decision
            )
        }
    )


#: Minimal identity/hash/provenance corruptions of a produced aggregate
#: (label, corrupt) -> the forged detached copy. Every copy changes at
#: least one recorded identity, hash, or provenance value and nothing else.
AGGREGATE_CORRUPTIONS_F: tuple[tuple[str, Any], ...] = (
    ("identity-identifier", lambda agg, auth: agg.model_copy(update={"identifier": "0" * 16})),
    ("identity-content-hash", lambda agg, auth: agg.model_copy(update={"content_hash": "1" * 64})),
    (
        "identity-runtime-version",
        lambda agg, auth: agg.model_copy(update={"runtime_version": "4.0.1"}),
    ),
    ("hash-input-hash", lambda agg, auth: agg.model_copy(update={"input_hash": "2" * 64})),
    (
        "hash-trajectory-plan-set",
        lambda agg, auth: agg.model_copy(update={"trajectory_plan_set_hash": "3" * 64}),
    ),
    (
        "hash-executed-at",
        lambda agg, auth: agg.model_copy(
            update={"executed_at": agg.executed_at + timedelta(days=1)}
        ),
    ),
    ("provenance-tenant", lambda agg, auth: agg.model_copy(update={"tenant_id": "tenant-foreign"})),
    ("provenance-run-id", lambda agg, auth: agg.model_copy(update={"run_id": "run-foreign"})),
    ("provenance-campaign", lambda agg, auth: agg.model_copy(update={"campaign_id": "campaign-x"})),
    ("provenance-run-plan", lambda agg, auth: agg.model_copy(update={"run_plan_id": "run-plan-x"})),
    ("provenance-scenario", lambda agg, auth: agg.model_copy(update={"scenario_id": "scenario-9"})),
    (
        "provenance-world-id",
        lambda agg, auth: agg.model_copy(update={"world_version_id": "world-9"}),
    ),
    (
        "provenance-world-hash",
        lambda agg, auth: agg.model_copy(update={"world_content_hash": "4" * 64}),
    ),
    ("provenance-seed-id", lambda agg, auth: agg.model_copy(update={"scenario_seed_id": "seed-9"})),
    (
        "provenance-seed-hash",
        lambda agg, auth: agg.model_copy(update={"seed_content_hash": "5" * 64}),
    ),
    (
        "provenance-realization-id",
        lambda agg, auth: agg.model_copy(update={"world_realization_id": "realization-9"}),
    ),
    (
        "provenance-realization-hash",
        lambda agg, auth: agg.model_copy(update={"world_realization_content_hash": "6" * 64}),
    ),
    (
        "provenance-policy-identifier",
        lambda agg, auth: agg.model_copy(update={"adaptive_policy_identifier": "policy-9"}),
    ),
    (
        "provenance-policy-id",
        lambda agg, auth: agg.model_copy(update={"policy_id": "policy-forged"}),
    ),
    (
        "provenance-policy-hash",
        lambda agg, auth: agg.model_copy(update={"adaptive_policy_content_hash": "7" * 64}),
    ),
)

#: Evidence-surface and forged-surface corruptions of a produced aggregate
#: (the final authority verifier must reject every one).
AGGREGATE_CORRUPTIONS_I: tuple[tuple[str, Any], ...] = (
    (
        "bundle-id-one-sided",
        lambda agg, auth: agg.model_copy(
            update={"external_observation_input_bundle_id": "bundle-forged"}
        ),
    ),
    (
        "bundle-pair-forged",
        lambda agg, auth: agg.model_copy(
            update={
                "external_observation_input_bundle_id": "bundle-forged",
                "external_observation_input_bundle_content_hash": "8" * 64,
            }
        ),
    ),
    (
        "decision-selected-action",
        lambda agg, auth: _remap(
            agg, "decision_events", lambda d: d.model_copy(update={"selected_action_id": "act-9"})
        ),
    ),
    (
        "decision-policy-id",
        lambda agg, auth: _remap(
            agg, "decision_events", lambda d: d.model_copy(update={"policy_id": "policy-forged"})
        ),
    ),
    (
        "snapshot-policy-content-hash",
        lambda agg, auth: _remap(
            agg,
            "policy_state_snapshots",
            lambda s: s.model_copy(update={"policy_content_hash": "9" * 64}),
        ),
    ),
    (
        "switch-old-action",
        lambda agg, auth: _remap(
            agg, "switch_events", lambda s: s.model_copy(update={"old_action_id": "act-9"})
        ),
    ),
    (
        "observation-exposed-value",
        lambda agg, auth: _remap(
            agg,
            "observation_events",
            lambda e: e.model_copy(update={"exposed_observation_value": 42}),
        ),
    ),
    (
        "result-final-state",
        lambda agg, auth: _forge_trajectory_results(
            agg,
            lambda r: r.model_copy(
                update={
                    "final_state": {
                        key: (value + 1) if isinstance(value, (int, float)) else value
                        for key, value in r.final_state.items()
                    }
                }
            ),
        ),
    ),
    (
        "result-trajectory-plan-id",
        lambda agg, auth: _forge_trajectory_results(
            agg, lambda r: r.model_copy(update={"trajectory_plan_id": "plan-forged"})
        ),
    ),
    (
        "result-non-finite-nested-state",
        lambda agg, auth: _forge_trajectory_results(
            agg,
            lambda r: r.model_copy(update={"final_state": dict(r.final_state, weight=math.nan)}),
        ),
    ),
)


def _env_snapshot(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> dict[str, Any]:
    """A deep, serializable fingerprint of every store, authority, and
    caller-owned surface the builder could possibly touch."""
    store = env.store
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
    snapshot = {
        "executions": tuple(
            execution.model_dump(mode="json")
            for execution in store._adaptive_run_trajectory_executions.values()
        ),
        "activity": tuple(
            event.model_dump(mode="json") for event in store.list_operational_activity(TENANT)
        ),
        "run_status": store.get_run_status(TENANT, authorities.run_id).model_dump(mode="json"),
        "campaign": campaign.model_dump(mode="json"),
        "campaign_status": store.get_campaign_status(TENANT, CAMPAIGN).model_dump(mode="json"),
        "world": store.get_world(TENANT, env.world_id).model_dump(mode="json"),
        "policy": store.get_adaptive_policy(TENANT, CAMPAIGN).model_dump(mode="json"),
        "run_plan": authorities.run_plan.model_dump(mode="json"),
        "plans": tuple(
            plan.model_dump(mode="json")
            for plan in store.get_strategy_trajectory_plans(TENANT, CAMPAIGN)
        ),
        "candidates": tuple(
            candidate.model_dump(mode="json")
            for candidate in store.get_strategy_candidates(TENANT, CAMPAIGN)
        ),
        "declarations": {
            observation_id: declaration.model_dump(mode="json")
            for observation_id, declaration in authorities.declarations.items()
        },
        "state_models": tuple(
            store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", model_id).model_dump(
                mode="json"
            )
            for model_id in ("sm-a", "sm-b")
        ),
        "transitions": tuple(
            transition.model_dump(mode="json")
            for transition in store.list_domain_state_transitions(TENANT, "scenario-1")
        ),
        "binding": store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1").model_dump(
            mode="json"
        ),
        "realization": authorities.realization.model_dump(mode="json"),
        "seed": seed.model_dump(mode="json"),
        "catalogs": tuple(catalog.state_model.model_dump(mode="json") for catalog in env.catalogs),
        "catalog_transitions": tuple(
            tuple(transition.model_dump(mode="json") for transition in catalog.transitions)
            for catalog in env.catalogs
        ),
        "action_plans": {
            action_id: tuple(plan.model_dump(mode="json") for plan in bound_plans)
            for action_id, bound_plans in authorities.action_plans.items()
        },
        "authorities": copy.deepcopy(authorities),
    }
    if authorities.external_bundle is not None:
        snapshot["external_bundle"] = authorities.external_bundle.model_dump(mode="json")
    return snapshot


# ---------------------------------------------------------------------------
# F. Aggregate identity and provenance
# ---------------------------------------------------------------------------


def test_f1_identities_agree_with_stored_verified_authorities(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    store = env.store
    campaign = store.get_campaign(TENANT, CAMPAIGN)
    world = store.get_world(TENANT, env.world_id)
    seed = next(s for s in campaign.seed_ensemble if s.identifier == SEED_ID)
    policy = store.get_adaptive_policy(TENANT, CAMPAIGN)
    aggregate = _build(authorities, env, 2)
    # The authority carrier agrees with the stored verified records...
    assert authorities.campaign.identifier == campaign.identifier
    assert authorities.world.identifier == world.identifier
    assert authorities.world.content_hash == world.content_hash
    assert authorities.seed.identifier == seed.identifier
    assert authorities.policy.identifier == policy.identifier
    # ...and the aggregate carries exactly those identities.
    assert aggregate.tenant_id == authorities.tenant_id == TENANT
    assert aggregate.run_id == authorities.run_id
    assert aggregate.campaign_id == campaign.identifier
    assert aggregate.run_plan_id == authorities.run_plan.identifier
    assert aggregate.scenario_id == campaign.scenario_id
    assert aggregate.world_version_id == world.identifier
    assert aggregate.world_content_hash == world.content_hash
    assert aggregate.scenario_seed_id == seed.identifier
    assert aggregate.seed_content_hash == seed_content_hash(seed)
    assert aggregate.world_realization_id == authorities.realization.identifier
    assert aggregate.world_realization_content_hash == authorities.realization.content_hash
    assert aggregate.runtime_version == RUNTIME_VERSION


def test_f2_policy_identity_agrees_with_stored_bound_policy(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    stored = env.store.get_adaptive_policy(TENANT, CAMPAIGN)
    aggregate = _build(authorities, env, 2)
    assert authorities.policy.identifier == stored.identifier
    assert authorities.policy.policy_id == stored.policy_id
    assert authorities.policy.content_hash == stored.content_hash
    assert authorities.policy.runtime_version == RUNTIME_VERSION
    assert aggregate.adaptive_policy_identifier == stored.identifier
    assert aggregate.policy_id == stored.policy_id
    assert aggregate.adaptive_policy_content_hash == stored.content_hash


def test_f3_every_decision_snapshot_and_switch_references_exact_policy(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    policy = authorities.policy
    bound_actions = {action.action_id for action in policy.actions}
    for decision in aggregate.decision_events:
        assert decision.runtime_version == RUNTIME_VERSION
        assert decision.policy_id == policy.policy_id
        assert decision.policy_content_hash == policy.content_hash
        assert decision.current_action_id in bound_actions
        assert decision.selected_action_id in bound_actions
    for snapshot in aggregate.policy_state_snapshots:
        assert snapshot.runtime_version == RUNTIME_VERSION
        assert snapshot.policy_id == policy.policy_id
        assert snapshot.policy_content_hash == policy.content_hash
        assert snapshot.current_action_id in bound_actions
    for switch in aggregate.switch_events:
        assert switch.runtime_version == RUNTIME_VERSION
        assert switch.policy_id == policy.policy_id
        assert switch.policy_content_hash == policy.content_hash
        assert switch.old_action_id in bound_actions
        assert switch.new_action_id in bound_actions


def test_f4_every_selected_action_agrees_with_canonical_action_plan_catalog(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    bound_actions = {action.action_id for action in authorities.policy.actions}
    flat_plans = [plan for bound in authorities.action_plans.values() for plan in bound]
    flat_ids = {plan.identifier for plan in flat_plans}
    for decision, results in zip(
        aggregate.decision_events, aggregate.trajectory_results_by_decision, strict=True
    ):
        selected = decision.selected_action_id
        assert selected in bound_actions
        bound_plans = authorities.action_plans[selected]
        assert {result.trajectory_plan_id for result in results} == {
            plan.identifier for plan in bound_plans
        }
        assert len(results) == len(bound_plans)
        assert {result.trajectory_plan_id for result in results} <= flat_ids
        for result in results:
            plan = next(p for p in bound_plans if p.identifier == result.trajectory_plan_id)
            assert result.trajectory_plan_content_hash == plan.content_hash


def test_f5_strategy_plan_manifest_and_state_model_authorities_agree_with_stored(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    store = env.store
    aggregate = _build(authorities, env, 2)
    candidates = {c.identifier: c for c in store.get_strategy_candidates(TENANT, CAMPAIGN)}
    models = {m.identifier: m for m in extract_world_catalog(authorities.world).state_models}
    binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
    assert binding.manifest_id == "manifest-1"
    for decision, results in zip(
        aggregate.decision_events, aggregate.trajectory_results_by_decision, strict=True
    ):
        action = next(
            a for a in authorities.policy.actions if a.action_id == decision.selected_action_id
        )
        plans_by_id = {
            p.identifier: p for p in authorities.action_plans[decision.selected_action_id]
        }
        action_bindings = {b.trajectory_plan_id: b for b in action.trajectory_plan_bindings}
        for result in results:
            plan = plans_by_id[result.trajectory_plan_id]
            plan_binding = action_bindings[plan.identifier]
            candidate = candidates[plan.strategy_candidate_id]
            model = models[result.state_model_identifier]
            assert plan.strategy_candidate_id == action.strategy_candidate_id
            assert candidate.identifier == plan.strategy_candidate_id
            assert plan.strategy_content_hash == action.strategy_content_hash
            assert (
                plan.manifest_id
                == plan_binding.manifest_id
                == result.manifest_id
                == model.manifest_id
                == binding.manifest_id
            )
            assert plan.state_model_identifier == result.state_model_identifier == model.identifier
            assert (
                plan.state_model_id
                == plan_binding.state_model_id
                == result.state_model_id
                == model.state_model_id
            )
            assert (
                plan.state_model_content_hash
                == plan_binding.state_model_content_hash
                == result.state_model_content_hash
                == model.content_hash
            )
            assert result.trajectory_plan_id == plan.identifier
            assert result.trajectory_plan_content_hash == plan.content_hash


def test_f6_plan_set_ordering_is_canonical_and_hash_recomputes_exactly(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    plans = [plan for bound in authorities.action_plans.values() for plan in bound]
    ordered = sorted(
        plans, key=lambda plan: (plan.strategy_candidate_id, plan.state_model_identifier)
    )
    keys = [(plan.strategy_candidate_id, plan.state_model_identifier) for plan in ordered]
    assert keys == sorted(keys)
    assert len(ordered) == len(plans)
    assert aggregate.trajectory_plan_set_hash == trajectory_plan_set_hash(tuple(ordered))


def test_f7_run_input_hash_recomputes_exactly(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    assert aggregate.input_hash == _recompute_run_input_hash(
        authorities, aggregate, len(aggregate.decision_events) - 1
    )


def test_f8_input_hash_horizon_is_decision_count_minus_one(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    horizon = len(aggregate.decision_events) - 1
    assert aggregate.input_hash == _recompute_run_input_hash(authorities, aggregate, horizon)
    assert aggregate.input_hash != _recompute_run_input_hash(authorities, aggregate, horizon + 1)
    # The same horizon derivation holds for the external-bundle aggregate.
    step0 = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    assert step0.input_hash == _recompute_run_input_hash(external_authorities, step0, 0)


def test_f9_aggregate_identifier_and_content_hash_recompute_exactly(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    for horizon in (0, 1, 2):
        aggregate = _build(authorities, env, horizon)
        assert aggregate.identifier == adaptive_run_trajectory_execution_identifier(
            run_id=aggregate.run_id, runtime_version=aggregate.runtime_version
        )
        assert aggregate.content_hash == adaptive_run_trajectory_execution_content_hash(aggregate)
        assert aggregate.content_hash != aggregate.input_hash
        assert aggregate.identifier != aggregate.input_hash


def test_f10_executed_at_matches_run_plan_and_untouched_aggregates_verify(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    for horizon in (0, 1, 2):
        aggregate = _build(authorities, env, horizon)
        assert aggregate.executed_at == authorities.run_plan.created_at
        verify_adaptive_run_trajectory_execution_identity(aggregate)
        verify_adaptive_run_trajectory_execution_authority(aggregate, authorities=authorities)
    step0 = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    assert step0.executed_at == external_authorities.run_plan.created_at
    verify_adaptive_run_trajectory_execution_identity(step0)
    verify_adaptive_run_trajectory_execution_authority(step0, authorities=external_authorities)


@pytest.mark.parametrize(
    ("label", "corrupt"),
    AGGREGATE_CORRUPTIONS_F,
    ids=[case[0] for case in AGGREGATE_CORRUPTIONS_F],
)
def test_f11_minimally_corrupted_identity_hash_provenance_copies_are_rejected(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    label: str,
    corrupt: Any,
) -> None:
    aggregate = _build(authorities, env, 2)
    corrupted = corrupt(aggregate, authorities)
    assert corrupted != aggregate
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError):
        verify_adaptive_run_trajectory_execution_authority(corrupted, authorities=authorities)


# ---------------------------------------------------------------------------
# G. Determinism and idempotence
# ---------------------------------------------------------------------------


def test_g1_two_independent_byte_equivalent_environments_are_byte_identical(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    env2 = _build_env()
    authorities2, _run_id2 = _complete_authorities(env2)
    first = _build(authorities, env, 2)
    second = _build(authorities2, env2, 2)
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert second.identifier == first.identifier
    assert second.content_hash == first.content_hash
    assert second.input_hash == first.input_hash
    assert [d.model_dump(mode="json") for d in second.decision_events] == [
        d.model_dump(mode="json") for d in first.decision_events
    ]
    assert [s.model_dump(mode="json") for s in second.policy_state_snapshots] == [
        s.model_dump(mode="json") for s in first.policy_state_snapshots
    ]
    assert [s.model_dump(mode="json") for s in second.switch_events] == [
        s.model_dump(mode="json") for s in first.switch_events
    ]
    assert [e.model_dump(mode="json") for e in second.observation_events] == [
        e.model_dump(mode="json") for e in first.observation_events
    ]
    assert [
        [r.model_dump(mode="json") for r in results]
        for results in second.trajectory_results_by_decision
    ] == [
        [r.model_dump(mode="json") for r in results]
        for results in first.trajectory_results_by_decision
    ]
    assert [
        [r.final_state for r in results] for results in second.trajectory_results_by_decision
    ] == [[r.final_state for r in results] for results in first.trajectory_results_by_decision]


def test_g2_repeated_construction_over_unchanged_authority_is_byte_identical(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    first = _build(authorities, env, 2)
    for _ in range(2):
        rebuilt = _build(authorities, env, 2)
        assert rebuilt.model_dump(mode="json") == first.model_dump(mode="json")
        assert rebuilt.identifier == first.identifier
        assert rebuilt.content_hash == first.content_hash
        assert rebuilt.trajectory_plan_set_hash == first.trajectory_plan_set_hash


def test_g3_no_order_depends_on_mapping_insertion_or_observation_lexical_order(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    reversed_declarations = {
        observation_id: authorities.declarations[observation_id]
        for observation_id in reversed(tuple(authorities.declarations))
    }
    reversed_plans = {
        action_id: authorities.action_plans[action_id]
        for action_id in reversed(tuple(authorities.action_plans))
    }
    reordered = _replace_authorities(
        authorities, declarations=reversed_declarations, action_plans=reversed_plans
    )
    reordered_aggregate = _build(reordered, env, 2)
    assert reordered_aggregate.model_dump(mode="json") == aggregate.model_dump(mode="json")
    assert reordered_aggregate.identifier == aggregate.identifier
    assert reordered_aggregate.content_hash == aggregate.content_hash
    assert reordered_aggregate.trajectory_plan_set_hash == aggregate.trajectory_plan_set_hash
    # Observation ordering follows the declaration IDENTIFIER - never the
    # lexical observation-id order and never mapping insertion order.
    step0 = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=external_authorities,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    identifier_order = sorted(
        ("obs-a", "obs-b", "obs-c"),
        key=lambda observation_id: external_authorities.declarations[observation_id].identifier,
    )
    assert [e.observation_id for e in step0.observation_events] == identifier_order
    swapped_auth = _replace_authorities(
        external_authorities,
        declarations={
            observation_id: external_authorities.declarations[observation_id]
            for observation_id in reversed(tuple(external_authorities.declarations))
        },
    )
    step0_swapped = build_adaptive_run_trajectory_execution(
        external_env.store,
        authorities=swapped_auth,
        catalogs=external_env.catalogs,
        draft=AdaptiveRunExecutionBuildDraft(
            final_decision_step=0, external_bundle_draft=external_env.bundle_draft
        ),
    )
    assert step0_swapped.model_dump(mode="json") == step0.model_dump(mode="json")
    # The caller catalog order is enforced canonical: the canonical tuple
    # is the only accepted order, so no output can depend on caller order.
    assert env.catalogs == tuple(
        sorted(env.catalogs, key=lambda catalog: catalog.state_model.identifier)
    )


def test_g4_identifiers_change_only_on_genuine_identity_or_content_inputs(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    base = _build(authorities, env, 2)
    repeated = _build(authorities, env, 2)
    assert repeated.identifier == base.identifier
    assert repeated.content_hash == base.content_hash
    # The causal horizon is a genuine content input: the identifier stays,
    # the content hash and evidence rotate.
    shorter = _build(authorities, env, 1)
    assert shorter.identifier == base.identifier
    assert shorter.content_hash != base.content_hash
    assert shorter.model_dump(mode="json") != base.model_dump(mode="json")
    # A genuine run-identity change (a different run-plan identity) rotates
    # both the identifier and the content hash.
    new_plan = authorities.run_plan.model_copy(update={"identifier": "run-plan-2"})
    new_run_id = run_identifier(new_plan)
    new_status = authorities.run_status.model_copy(
        update={
            "identifier": f"status-{new_run_id}",
            "run_id": new_run_id,
            "run_plan_id": new_plan.identifier,
        }
    )
    reidentified = _replace_authorities(
        authorities, run_plan=new_plan, run_status=new_status, run_id=new_run_id
    )
    reidentified_aggregate = _build(reidentified, env, 2)
    assert reidentified_aggregate.identifier != base.identifier
    assert reidentified_aggregate.content_hash != base.content_hash


# ---------------------------------------------------------------------------
# H. Purity and failure atomicity
# ---------------------------------------------------------------------------


def test_h1_successful_build_leaves_no_trace(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    before = _env_snapshot(env, authorities)
    aggregate = _build(authorities, env, 2)
    verify_adaptive_run_trajectory_execution_identity(aggregate)
    after = _env_snapshot(env, authorities)
    assert after == before
    assert _execution_count(env.store) == 0


def test_h2_repeated_successful_builds_do_not_accumulate(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    before = _env_snapshot(env, authorities)
    for horizon in (0, 1, 2, 2, 1):
        _build(authorities, env, horizon)
    assert _env_snapshot(env, authorities) == before
    assert _execution_count(env.store) == 0


def test_h3_rejected_calls_preserve_every_fingerprint(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    draft_zero = AdaptiveRunExecutionBuildDraft(final_decision_step=0)
    draft_invalid = AdaptiveRunExecutionBuildDraft(final_decision_step=-1)
    draft_external = AdaptiveRunExecutionBuildDraft(
        final_decision_step=2, external_bundle_draft=external_env.bundle_draft
    )
    cases: tuple[
        tuple[
            Env,
            AdaptiveRunExecutionAuthorities,
            Any,
            AdaptiveRunExecutionBuildDraft,
            type[Exception],
        ],
        ...,
    ] = (
        # preflight validation family
        (
            env,
            authorities,
            env.catalogs,
            draft_invalid,
            AdaptiveRunTrajectoryExecutionValidationError,
        ),
        # cross-authority integrity family
        (
            env,
            _replace_authorities(authorities, tenant_id="tenant-foreign"),
            env.catalogs,
            draft_zero,
            AdaptiveRunTrajectoryExecutionIntegrityError,
        ),
        # final-verifier lifecycle family
        (
            env,
            _replace_authorities(
                authorities,
                run_status=authorities.run_status.model_copy(update={"state": RunState.PLANNED}),
            ),
            env.catalogs,
            draft_zero,
            AdaptiveRunTrajectoryExecutionIntegrityError,
        ),
        # orchestrator catalog-integrity family
        (
            env,
            authorities,
            tuple(reversed(env.catalogs)),
            draft_zero,
            AdaptiveRunTrajectoryExecutionIntegrityError,
        ),
        # condition missing-evidence family (external env)
        (
            external_env,
            external_authorities,
            external_env.catalogs,
            draft_external,
            AdaptiveConditionMissingObservationError,
        ),
    )
    for env_for, authorities_for, catalogs_for, draft_for, expected in cases:
        before = _env_snapshot(env_for, authorities_for)
        with pytest.raises(expected):
            build_adaptive_run_trajectory_execution(
                env_for.store,
                authorities=authorities_for,
                catalogs=catalogs_for,
                draft=draft_for,
            )
        assert _env_snapshot(env_for, authorities_for) == before
        assert _execution_count(env_for.store) == 0


# ---------------------------------------------------------------------------
# I. Strict rejection matrix
# ---------------------------------------------------------------------------

_GENERIC_MESSAGES: dict[type[Exception], str] = {
    AdaptiveRunTrajectoryExecutionValidationError: (
        "Adaptive run trajectory execution input is invalid"
    ),
    AdaptiveRunTrajectoryExecutionIntegrityError: (
        "Adaptive run trajectory execution failed integrity verification"
    ),
    RuntimeObservationEventValidationError: (
        "Runtime observation event derivation input is invalid"
    ),
}


def _assert_generic_public_message(exc: Exception, expected_type: type[Exception]) -> None:
    assert type(exc) is expected_type
    assert str(exc) == _GENERIC_MESSAGES[expected_type]
    reason = getattr(exc, "reason", None)
    if reason is not None:
        assert reason not in str(exc)


def _assert_no_sensitive_leak(
    exc: Exception,
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    message = str(exc)
    tokens = [
        TENANT,
        CAMPAIGN,
        SEED_ID,
        "scenario-1",
        "manifest-1",
        "sm-a",
        "sm-b",
        "act-1",
        "act-2",
        "obs-level",
        "obs-a",
        "obs-b",
        "obs-c",
        "rule-1",
        "rule-2",
        "rule-3",
        "run-plan-1",
        authorities.run_id,
        authorities.world.identifier,
        authorities.world.content_hash,
        authorities.seed.identifier,
        authorities.realization.identifier,
        authorities.realization.content_hash,
        authorities.policy.identifier,
        authorities.policy.policy_id,
        authorities.policy.content_hash,
        authorities.run_plan.identifier,
        authorities.run_plan.input_hash,
    ]
    tokens.extend(plan.identifier for bound in authorities.action_plans.values() for plan in bound)
    tokens.extend(declaration.identifier for declaration in authorities.declarations.values())
    tokens.extend(declaration.content_hash for declaration in authorities.declarations.values())
    if authorities.external_bundle is not None:
        tokens.extend(
            (
                authorities.external_bundle.identifier,
                authorities.external_bundle.content_hash,
            )
        )
    for token in tokens:
        assert token not in message
    assert re.search(r"[0-9a-f]{64}", message) is None
    assert re.search(r"[0-9a-f]{16}", message) is None


#: The complete builder-boundary rejection families over the shared real
#: environment (label, call(env, authorities) -> raises, exact typed error).
#: Where the policy or realization CONTRACT rejects the corruption during
#: detached strict revalidation before the builder's own check could run,
#: the validation family is observed and the boundary is documented inline.
_BUILDER_REJECTIONS: tuple[tuple[str, Any, type[Exception]], ...] = (
    # cross-authority provenance agreement - integrity family
    (
        "wrong-tenant",
        lambda env, auth: _call_build(
            env, _replace_authorities(auth, tenant_id="tenant-foreign"), 0
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-run-identifier",
        lambda env, auth: _call_build(env, _replace_authorities(auth, run_id="run-foreign"), 0),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-run-plan-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, run_plan=auth.run_plan.model_copy(update={"identifier": "run-plan-x"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-run-plan-input-hash",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, run_plan=auth.run_plan.model_copy(update={"input_hash": "0" * 64})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-campaign-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, campaign=auth.campaign.model_copy(update={"identifier": "campaign-x"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-scenario-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, campaign=auth.campaign.model_copy(update={"scenario_id": "scenario-9"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-world-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, world=auth.world.model_copy(update={"identifier": "world-9"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-world-content-hash",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, world=auth.world.model_copy(update={"content_hash": "1" * 64})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-seed-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(auth, seed=auth.seed.model_copy(update={"identifier": "seed-9"})),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-seed-value",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(auth, seed=auth.seed.model_copy(update={"seed_value": "forged"})),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-realization-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                realization=auth.realization.model_copy(update={"identifier": "realization-9"}),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-realization-world-provenance",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                realization=auth.realization.model_copy(update={"world_version_id": "world-9"}),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-policy-tenant",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, policy=auth.policy.model_copy(update={"tenant_id": "tenant-foreign"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-policy-world-content-hash",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, policy=auth.policy.model_copy(update={"world_content_hash": "2" * 64})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    # runtime and lifecycle agreement
    (
        "wrong-runtime-version-run-plan",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, run_plan=auth.run_plan.model_copy(update={"runtime_version": "3.0.0"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "wrong-runtime-version-run-status",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, run_status=auth.run_status.model_copy(update={"runtime_version": "3.0.0"})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "campaign-status-not-compiled",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                campaign_status=env.store.get_campaign_status(TENANT, CAMPAIGN).model_copy(
                    update={"state": CampaignState.DRAFT}
                ),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "run-status-not-running-or-complete",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth, run_status=auth.run_status.model_copy(update={"state": RunState.PLANNED})
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    # exact types and validator bypass
    (
        "validator-bypassed-policy",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                policy=type(auth.policy).model_construct(
                    identifier=auth.policy.identifier, tenant_id=TENANT
                ),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "wrong-policy-exact-type",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(auth, policy=auth.run_plan),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "action-plans-missing-key",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: plans
                    for action_id, plans in auth.action_plans.items()
                    if action_id != "act-1"
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "action-plans-extra-key",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={**auth.action_plans, "act-9": ()},
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "action-plans-non-tuple-values",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: list(plans) for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    # action-plan and state-model coverage
    (
        "duplicate-action-plan",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: (plans[0], plans[0])
                    for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "mismatched-strategy-candidate",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: tuple(
                        plan.model_copy(update={"strategy_candidate_id": "mock-other"})
                        for plan in plans
                    )
                    for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "mismatched-plan-content-hash",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: tuple(
                        plan.model_copy(update={"content_hash": "3" * 64}) for plan in plans
                    )
                    for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "mismatched-plan-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: tuple(
                        plan.model_copy(update={"identifier": "plan-forged"}) for plan in plans
                    )
                    for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "mismatched-plan-manifest",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                action_plans={
                    action_id: tuple(
                        plan.model_copy(update={"manifest_id": "manifest-9"}) for plan in plans
                    )
                    if action_id == "act-1"
                    else plans
                    for action_id, plans in auth.action_plans.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        # The policy CONTRACT's own complete-coverage validator rejects the
        # extra binding during detached strict revalidation before the
        # builder's state-model authority check could observe it.
        "extra-state-model-coverage",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                policy=auth.policy.model_copy(
                    update={
                        "actions": tuple(
                            action.model_copy(
                                update={
                                    "trajectory_plan_bindings": (
                                        action.trajectory_plan_bindings
                                        + (
                                            TrajectoryPlanBinding(
                                                trajectory_plan_id="plan-phantom",
                                                trajectory_plan_content_hash="4" * 64,
                                                manifest_id="manifest-1",
                                                state_model_identifier="sm-nonexistent",
                                                state_model_id="sm-nonexistent",
                                                state_model_content_hash="5" * 64,
                                            ),
                                        )
                                    )
                                }
                            )
                            if action.action_id == "act-1"
                            else action
                            for action in auth.policy.actions
                        )
                    }
                ),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "incomplete-state-model-coverage",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                policy=auth.policy.model_copy(
                    update={
                        "actions": tuple(
                            action.model_copy(
                                update={
                                    "trajectory_plan_bindings": tuple(
                                        binding
                                        for binding in action.trajectory_plan_bindings
                                        if binding.state_model_id != "sm-b"
                                    )
                                }
                            )
                            if action.action_id == "act-1"
                            else action
                            for action in auth.policy.actions
                        )
                    }
                ),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    # declaration authorities
    (
        "corrupted-declaration-identifier",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                declarations={
                    observation_id: (
                        declaration.model_copy(update={"identifier": "decl-forged"})
                        if observation_id == "obs-level"
                        else declaration
                    )
                    for observation_id, declaration in auth.declarations.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "corrupted-declaration-content-hash",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                declarations={
                    observation_id: (
                        declaration.model_copy(update={"content_hash": "6" * 64})
                        if observation_id == "obs-level"
                        else declaration
                    )
                    for observation_id, declaration in auth.declarations.items()
                },
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    # non-canonical catalogs
    (
        "reversed-catalogs",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=auth,
            catalogs=tuple(reversed(env.catalogs)),
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=0),
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        # The realization CONTRACT rejects non-finite override values during
        # detached strict revalidation before the builder's own finite-state
        # guard could run (that guard is covered at the aggregate level by
        # the forged non-finite nested-state rejection).
        "non-finite-realization-override",
        lambda env, auth: _call_build(
            env,
            _replace_authorities(
                auth,
                realization=auth.realization.model_copy(
                    update={
                        "realized_initial_state_overrides": tuple(
                            override.model_copy(update={"value": math.nan})
                            if override.state_field_id == "weight"
                            else override
                            for override in auth.realization.realized_initial_state_overrides
                        )
                    }
                ),
            ),
            0,
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
)


@pytest.mark.parametrize(
    ("label", "call_build", "expected_type"),
    _BUILDER_REJECTIONS,
    ids=[case[0] for case in _BUILDER_REJECTIONS],
)
def test_i1_builder_boundary_rejection_matrix(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    label: str,
    call_build: Any,
    expected_type: type[Exception],
) -> None:
    with pytest.raises(expected_type) as excinfo:
        call_build(env, authorities)
    _assert_generic_public_message(excinfo.value, expected_type)
    _assert_no_sensitive_leak(excinfo.value, env, authorities)
    assert _execution_count(env.store) == 0


_BUILDER_REJECTIONS_EXTERNAL: tuple[tuple[str, Any, type[Exception]], ...] = (
    (
        "bundle-presence-draft-missing",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=auth,
            catalogs=env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(final_decision_step=0, external_bundle_draft=None),
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "bundle-presence-authority-missing",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=_replace_authorities(auth, external_bundle=None),
            catalogs=env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=0, external_bundle_draft=env.bundle_draft
            ),
        ),
        AdaptiveRunTrajectoryExecutionValidationError,
    ),
    (
        "forged-bundle-content-hash",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=_replace_authorities(
                auth,
                external_bundle=auth.external_bundle.model_copy(update={"content_hash": "7" * 64}),
            ),
            catalogs=env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=0, external_bundle_draft=env.bundle_draft
            ),
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "forged-bundle-campaign-provenance",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=_replace_authorities(
                auth,
                external_bundle=auth.external_bundle.model_copy(
                    update={"campaign_id": "campaign-x"}
                ),
            ),
            catalogs=env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=0, external_bundle_draft=env.bundle_draft
            ),
        ),
        AdaptiveRunTrajectoryExecutionIntegrityError,
    ),
    (
        "wrong-bundle-draft-value",
        lambda env, auth: build_adaptive_run_trajectory_execution(
            env.store,
            authorities=auth,
            catalogs=env.catalogs,
            draft=AdaptiveRunExecutionBuildDraft(
                final_decision_step=0,
                external_bundle_draft=dataclasses.replace(
                    env.bundle_draft,
                    entries=tuple(
                        dataclasses.replace(entry, value=9)
                        if entry.observation_id == "obs-a"
                        else entry
                        for entry in env.bundle_draft.entries
                    ),
                ),
            ),
        ),
        RuntimeObservationEventValidationError,
    ),
)


@pytest.mark.parametrize(
    ("label", "call_build", "expected_type"),
    _BUILDER_REJECTIONS_EXTERNAL,
    ids=[case[0] for case in _BUILDER_REJECTIONS_EXTERNAL],
)
def test_i2_external_bundle_boundary_rejection_matrix(
    external_env: Env,
    external_authorities: AdaptiveRunExecutionAuthorities,
    label: str,
    call_build: Any,
    expected_type: type[Exception],
) -> None:
    with pytest.raises(expected_type) as excinfo:
        call_build(external_env, external_authorities)
    _assert_generic_public_message(excinfo.value, expected_type)
    _assert_no_sensitive_leak(excinfo.value, external_env, external_authorities)
    assert _execution_count(external_env.store) == 0


@pytest.mark.parametrize(
    ("label", "corrupt"),
    AGGREGATE_CORRUPTIONS_I,
    ids=[case[0] for case in AGGREGATE_CORRUPTIONS_I],
)
def test_i3_forged_evidence_and_corrupted_aggregates_rejected_by_final_authority(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
    label: str,
    corrupt: Any,
) -> None:
    aggregate = _build(authorities, env, 2)
    corrupted = corrupt(aggregate, authorities)
    assert corrupted != aggregate
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError) as excinfo:
        verify_adaptive_run_trajectory_execution_authority(corrupted, authorities=authorities)
    _assert_generic_public_message(excinfo.value, AdaptiveRunTrajectoryExecutionIntegrityError)
    _assert_no_sensitive_leak(excinfo.value, env, authorities)
    assert _execution_count(env.store) == 0


def test_i4_mismatched_final_horizon_authority_is_rejected(
    env: Env,
    authorities: AdaptiveRunExecutionAuthorities,
) -> None:
    aggregate = _build(authorities, env, 2)
    horizon = len(aggregate.decision_events) - 1
    forged = aggregate.model_copy(
        update={"input_hash": _recompute_run_input_hash(authorities, aggregate, horizon + 1)}
    )
    forged = forged.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(forged)}
    )
    with pytest.raises(AdaptiveRunTrajectoryExecutionIntegrityError) as excinfo:
        verify_adaptive_run_trajectory_execution_authority(forged, authorities=authorities)
    assert excinfo.value.reason == "input hash mismatch"
    assert _execution_count(env.store) == 0


# ---------------------------------------------------------------------------
# J. Source and architecture boundaries
# ---------------------------------------------------------------------------

_J_FORBIDDEN_IMPORT_ROOTS = {
    "socket",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "asyncio",
    "ssl",
    "ftplib",
    "smtplib",
    "subprocess",
    "os",
    "sys",
    "pathlib",
    "shutil",
    "datetime",
    "time",
    "random",
    "secrets",
    "uuid",
    "json",
    "pickle",
    "sqlite3",
    "csv",
    "email",
    "signal",
    "threading",
    "multiprocessing",
}

_J_NO_CLOCK_OR_RNG_NAMES = {
    "datetime",
    "utcnow",
    "now",
    "perf_counter",
    "monotonic",
    "time_ns",
    "getrandbits",
    "randint",
    "randrange",
    "sample",
    "shuffle",
    "choice",
    "gethostname",
    "getenv",
    "environ",
}

_J_REQUIRED_SEAM_NAMES = {
    "execute_adaptive_decision_step",
    "initialize_adaptive_policy_state",
    "realized_initial_state",
    "validate_state",
    "verify_adaptive_run_trajectory_execution_authority",
    "trajectory_plan_set_hash",
    "adaptive_run_input_hash",
    "adaptive_run_trajectory_execution_identifier",
    "adaptive_run_trajectory_execution_content_hash",
    "seed_content_hash",
    "extract_world_catalog",
}

_J_FORBIDDEN_DYNAMIC_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "import_module",
    "getattr",
    "setattr",
    "delattr",
    "globals",
    "locals",
    "vars",
}


def _builder_source_tree() -> tuple[str, Any]:
    source = inspect.getsource(adaptive_builder_module)
    return source, ast.parse(source)


def test_j1_imports_stay_within_kalhas_responsibilities() -> None:
    _source, tree = _builder_source_tree()
    roots: set[str] = set()
    kalhas_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            roots.add(node.module.split(".")[0])
            if node.module.startswith("kalhas"):
                kalhas_modules.add(node.module)
    assert roots <= {"__future__", "warnings", "dataclasses", "typing", "pydantic", "kalhas"}
    assert all(
        module.startswith("kalhas.application.") or module.startswith("kalhas.contracts.v1.")
        for module in kalhas_modules
    )
    lowered = " ".join(sorted(kalhas_modules)).lower()
    assert "nexus" not in lowered
    assert "legion" not in lowered
    # No domain pack is imported: the kernel consumes no domain content.
    assert not any(module.startswith("kalhas.domain_packs") for module in kalhas_modules)


def test_j2_no_network_provider_clock_or_uncontrolled_randomness() -> None:
    _source, tree = _builder_source_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            roots.add(node.module.split(".")[0])
    assert not (roots & _J_FORBIDDEN_IMPORT_ROOTS)
    name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (name_ids & _J_NO_CLOCK_OR_RNG_NAMES)
    attribute_names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not (
        attribute_names
        & {
            "random",
            "randint",
            "randrange",
            "uniform",
            "sample",
            "shuffle",
            "choice",
            "request",
            "urlopen",
            "getaddrinfo",
            "sendto",
            "connect",
        }
    )


def test_j3_no_store_persistence_no_status_mutation_no_activity_writes() -> None:
    _source, tree = _builder_source_tree()
    attributes = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
    # The builder never performs ANY member access on the store instance:
    # the store is only passed through to the orchestrator.
    assert not [
        node for node in attributes if isinstance(node.value, ast.Name) and node.value.id == "store"
    ]
    # No attribute (member) assignment exists anywhere in the module, so no
    # RunStatus, policy state, or any caller object can be mutated.
    assert not [node for node in attributes if isinstance(node.ctx, ast.Store)]
    name_ids = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not (
        name_ids
        & {
            "operational_activity",
            "list_operational_activity",
            "record_operational_activity",
            "activity",
        }
    )


def test_j4_delegation_seams_present_and_no_duplicated_algorithms() -> None:
    _source, tree = _builder_source_tree()
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert called_names >= _J_REQUIRED_SEAM_NAMES
    dynamic_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (dynamic_calls & _J_FORBIDDEN_DYNAMIC_CALLS)
    # The exact module-level import surface pins the delegation:
    # the builder imports only the established seams from each owning
    # module and never imports the duplicated algorithm modules.
    kalhas_imports: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("kalhas")
        ):
            kalhas_imports.setdefault(node.module, set()).update(alias.name for alias in node.names)
    assert "kalhas.application.adaptive_condition_evaluator" not in kalhas_imports
    assert "kalhas.application.adaptive_action_trajectory_runtime" not in kalhas_imports
    assert kalhas_imports["kalhas.application.adaptive_policy_state_machine"] == {
        "initialize_adaptive_policy_state"
    }
    assert kalhas_imports["kalhas.application.state_transition_engine"] == {"validate_state"}
    assert kalhas_imports["kalhas.application.realization_trajectory_runtime"] == {
        "realized_initial_state"
    }
    assert kalhas_imports["kalhas.application.run_trajectory_runtime"] == {
        "trajectory_plan_set_hash"
    }
    assert kalhas_imports["kalhas.application.adaptive_decision_step_service"] == {
        "RUNTIME_VERSION",
        "AdaptiveDecisionStepDraft",
        "execute_adaptive_decision_step",
    }
    assert kalhas_imports["kalhas.application.adaptive_trajectory_execution_identity"] == {
        "adaptive_run_input_hash",
        "adaptive_run_trajectory_execution_content_hash",
        "adaptive_run_trajectory_execution_identifier",
    }
    assert kalhas_imports["kalhas.application.adaptive_trajectory_execution_integrity"] == {
        "AdaptiveRunExecutionAuthorities",
        "verify_adaptive_run_trajectory_execution_authority",
    }
    top_level_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    # The run-trajectory hash seam is imported function-scoped (the
    # established late-binding doctrine), never at module level.
    assert "kalhas.application.run_trajectory_runtime" not in top_level_modules
    # No delegated seam is reimplemented and no new public function exists.
    defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    public_defined = {name for name in defined if not name.startswith("_")}
    assert public_defined == {"build_adaptive_run_trajectory_execution"}
    assert not (defined & _J_REQUIRED_SEAM_NAMES)
    # No callbacks or arbitrary expressions: the builder's only lambda is
    # the canonical plan-set sort key (a pure sort comparator for the
    # established ordering predicate), never a callback or integration hook.
    lambda_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)]
    assert len(lambda_nodes) == 1
    sorted_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sorted"
    ]
    assert any(
        isinstance(keyword.value, ast.Lambda)
        for node in sorted_calls
        for keyword in node.keywords
        if keyword.arg == "key"
    )
    assert adaptive_builder_module.__all__ == [
        "RUNTIME_VERSION",
        "AdaptiveRunExecutionBuildDraft",
        "build_adaptive_run_trajectory_execution",
    ]
    assert "Callable" not in _source
