"""Shared helpers for Phase 25 runtime-3 preparation/preflight and lifecycle tests.

Builds runtime-3.0.0 prepared campaigns through the real Phase 25
preparation service, the transition-capable execution fixture used by
the lifecycle tests, and exposes the private test seam used to simulate
corrupted recorded unsupported-runtime state (an explicit non-application
path documented at the helper).
"""

from __future__ import annotations

from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    prepare_realization_campaign,
)
from kalhas.application.realization_execution import execute_realization_campaign
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_uncertainty_service import UncertaintyBindingDraft
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world_realization import UniformDistribution

from tests.phase4_helpers import NOW, TENANT, build_request, build_seed, start
from tests.phase20_helpers import (
    DECLARED_AT,
    _register_pack,
    build_observation_scenario,
)
from tests.phase24_helpers import (
    build_uncertainty_store,
    declare_model,
    uncertainty_fields,
)

RUNTIME_THREE_SEEDS = (
    build_seed(identifier="seed-1"),
    build_seed(identifier="seed-2"),
)

#: One deterministic level-independent transition of sm-1 (status idle ->
#: active); the canonical LEGION draft applies it on every run.
_TRANSITION_ID = "t-1"
_TRANSITION_GUARD: dict[str, JsonValue] = {"status": "idle"}
_TRANSITION_TARGET: dict[str, JsonValue] = {"status": "active"}


def level_binding() -> UncertaintyBindingDraft:
    """One uniform(0, 3) nearest-ties-to-even binding on the integer level field."""
    return UncertaintyBindingDraft(
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_field_id="level",
        distribution=UniformDistribution(kind="uniform", low=0.0, high=3.0),
        rounding_policy="nearest_ties_to_even",
    )


def runtime_three_store(*, with_model: bool = True) -> InMemoryScenarioStore:
    """A store with a compiled world and a runtime-3.0.0 prepared campaign.

    The campaign is prepared through the real
    ``prepare_realization_campaign`` service (the Phase 25 preparation
    seam) with the mock LEGION ensemble (five deterministic strategy
    candidates) and two seeds, so the stored records are exactly what
    production writes.
    """
    store = build_uncertainty_store()
    if with_model:
        declare_model(store, bindings=(level_binding(),))
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    return store


def runtime_three_execution_store() -> InMemoryScenarioStore:
    """A RUNNING runtime-3 campaign with one transition-capable model.

    The world embeds sm-1 (level/ratio/status) plus one deterministic
    level-independent transition (status idle -> active), prepared
    through the real preparation and trajectory-plan services with the
    canonical LEGION drafts and started through the real campaign-start
    seam: every stored run is PLANNED and the campaign is RUNNING, so
    ``execute_realization_campaign`` can preflight and execute all ten
    runs (five strategies x two seeds) with non-empty realization
    execution artifacts. Fully deterministic and domain-neutral.
    """
    store = build_uncertainty_store()
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id=_TRANSITION_ID,
        ),
        tenant_id=state_model.tenant_id,
        scenario_id=state_model.scenario_id,
        binding_id=state_model.binding_id,
        manifest_id=state_model.manifest_id,
        pack_id=state_model.pack_id,
        pack_version=state_model.pack_version,
        manifest_content_hash=state_model.manifest_content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=_TRANSITION_ID,
        description="Declared state change",
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three execution campaign",
        seed_ensemble=RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    return store


def runtime_three_observation_store(
    *,
    seeds: tuple[ScenarioSeed, ScenarioSeed] | None = None,
) -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign with observation bindings.

    The scenario declares metrics m-1 (unit ``units``) and m-2 (unit
    ``percent``); the world embeds observation bindings m-1 -> level and
    m-2 -> ratio, the uncertainty model on level, and one deterministic
    level-independent transition (status idle -> active) that leaves the
    realized level untouched in the final state. After real preparation,
    trajectory-plan preparation, start, and full campaign execution every
    run is COMPLETE with a stored realization execution, so metric
    observations can be extracted directly. Fully deterministic and
    domain-neutral.
    """
    store = InMemoryScenarioStore()
    store.put_scenario(build_observation_scenario())
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
    declare_domain_metric_observation(
        store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        metric_id="m-2",
        state_field_id="ratio",
        declared_at=DECLARED_AT,
    )
    declare_model(store, bindings=(level_binding(),))
    state_model = store.list_domain_state_models(TENANT, "scenario-1")[0]
    transition = DomainStateTransition(
        identifier=transition_identifier(
            scenario_id=state_model.scenario_id,
            manifest_id=state_model.manifest_id,
            state_model_id=state_model.state_model_id,
            transition_id=_TRANSITION_ID,
        ),
        tenant_id=state_model.tenant_id,
        scenario_id=state_model.scenario_id,
        binding_id=state_model.binding_id,
        manifest_id=state_model.manifest_id,
        pack_id=state_model.pack_id,
        pack_version=state_model.pack_version,
        manifest_content_hash=state_model.manifest_content_hash,
        state_model_id=state_model.state_model_id,
        state_model_content_hash=state_model.content_hash,
        transition_id=_TRANSITION_ID,
        description="Declared state change",
        guard_values=_TRANSITION_GUARD,
        target_values=_TRANSITION_TARGET,
        content_hash="0" * 64,
        declared_at=NOW,
    )
    transition = transition.model_copy(update={"content_hash": transition_content_hash(transition)})
    store.put_domain_state_transition(transition)
    compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
    prepare_realization_campaign(
        store=store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        world_version_id=compiled.version.identifier,
        strategy_request=build_request(TENANT),
        campaign_id="campaign-1",
        campaign_name="Runtime three observation campaign",
        seed_ensemble=seeds if seeds is not None else RUNTIME_THREE_SEEDS,
        created_at=NOW,
    )
    prepare_strategy_trajectory_plans(
        store=store, legion=MockLegionAdapter(), tenant_id=TENANT, campaign_id="campaign-1"
    )
    start(store)
    execute_realization_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    return store


def inject_unsupported_recorded_runtime(
    store: InMemoryScenarioStore,
    *,
    campaign_id: str,
    plan: RunPlan,
    unsupported_version: str = "9.9.9",
) -> str:
    """Simulate corrupted recorded state through private test seams.

    This is deliberately **not** an application preparation path: a run
    prepared as runtime 2.0.0 is re-stamped with an unsupported recorded
    runtime in both its stored ``RunPlan`` and its matching ``RunStatus``,
    keeping every field unrelated to the version mutually consistent.
    Downstream services must reject the run with the typed
    unsupported-runtime error exactly as they would reject externally
    corrupted or foreign recorded state.
    """
    run_id = run_identifier(plan)
    tampered_plan = plan.model_copy(update={"runtime_version": unsupported_version})
    stored_plans = store.get_run_plans(TENANT, campaign_id)
    store._run_plans[(TENANT, campaign_id)] = tuple(
        tampered_plan if candidate.identifier == plan.identifier else candidate
        for candidate in stored_plans
    )
    status = store.get_run_status(TENANT, run_id)
    store.put_run_status(
        TENANT,
        run_id,
        status.model_copy(update={"runtime_version": unsupported_version}),
    )
    return run_id
