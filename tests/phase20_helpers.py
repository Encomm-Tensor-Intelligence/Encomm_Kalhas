"""Shared helpers for Phase 20 metric-observation extraction tests.

Builds compiler-consistent stores whose compiled world embeds declared
``DomainMetricObservationBinding`` snapshots, prepares trajectory-runtime
(2.0.0) campaigns, prepares their immutable trajectory-plan collections
through the Phase 15 service, starts them, and executes them - the full
recorded-input setup a COMPLETE trajectory run with a stored
``RunTrajectoryExecution`` needs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_metric_observation_service import (
    declare_domain_metric_observation,
)
from kalhas.application.domain_pack_binding_service import bind_manifest
from kalhas.application.domain_pack_registry import register_manifest
from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.domain_state_transition_service import declare_transition
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION, run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.domain_pack import DomainPackCapability
from kalhas.contracts.v1.metric_observation import DomainMetricObservationBinding
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.shared import JsonValue, MetricDefinition
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    StateValueKind,
)
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import NOW, TENANT, build_scenario, prepare, start

BOUND_AT = datetime(2026, 1, 3, 12, 0, 0, tzinfo=UTC)
DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)

_OBSERVATION_METRICS = (
    MetricDefinition(identifier="m-1", name="Primary metric", unit="units"),
    MetricDefinition(identifier="m-2", name="Secondary metric", unit="percent"),
    MetricDefinition(identifier="m-3", name="Tertiary metric"),
)


def build_observation_scenario() -> ScenarioSpec:
    """A scenario declaring three metrics with authoritative units."""
    return build_scenario().model_copy(update={"metrics": list(_OBSERVATION_METRICS)})


def _field(
    identifier: str,
    value_kind: StateValueKind,
    initial_value: JsonValue,
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description="Declared state field",
        value_kind=value_kind,
        initial_value=initial_value,
    )


def observation_fields() -> tuple[DomainStateFieldDefinition, ...]:
    """Numeric fields (level/ratio) plus a non-numeric field."""
    return (
        _field("level", StateValueKind.INTEGER, 0),
        _field("ratio", StateValueKind.NUMBER, 0.0),
        _field("status", StateValueKind.STRING, "idle"),
    )


def _register_pack(store: InMemoryScenarioStore) -> None:
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


def build_observation_store(
    *,
    store: InMemoryScenarioStore | None = None,
    with_bindings: bool = True,
    with_transition: bool = True,
    scenario: ScenarioSpec | None = None,
) -> InMemoryScenarioStore:
    """A store with scenario, pack binding, state model, and (optionally) bindings.

    The observation bindings are declared through the Phase 19 service
    when ``with_bindings`` is true (m-1 -> ``level``, m-2 -> ``ratio``);
    the transition (when ``with_transition``) moves ``level`` 0 -> 1 and
    ``ratio`` 0.0 -> 1.5. The store is returned **before** compilation,
    so callers can compile a world at any point relative to later
    declarations.
    """
    effective_store = store if store is not None else InMemoryScenarioStore()
    effective_scenario = scenario if scenario is not None else build_observation_scenario()
    effective_store.put_scenario(effective_scenario)
    _register_pack(effective_store)
    declare_state_model(
        effective_store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=observation_fields(),
        declared_at=DECLARED_AT,
    )
    if with_transition:
        declare_transition(
            effective_store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            transition_id="t-1",
            description="Advance the numeric fields",
            guard_values={"level": 0, "ratio": 0.0},
            target_values={"level": 1, "ratio": 1.5},
            declared_at=DECLARED_AT,
        )
    if with_bindings:
        declare_domain_metric_observation(
            effective_store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-1",
            state_field_id="level",
            declared_at=DECLARED_AT,
        )
        declare_domain_metric_observation(
            effective_store,
            tenant_id=TENANT,
            scenario_id="scenario-1",
            manifest_id="manifest-1",
            state_model_id="sm-1",
            metric_id="m-2",
            state_field_id="ratio",
            declared_at=DECLARED_AT,
        )
    return effective_store


def compile_observation_world(
    store: InMemoryScenarioStore,
    scenario: ScenarioSpec | None = None,
) -> str:
    """Compile the scenario's world embedding the stored bindings and records.

    Returns the compiled world version identifier. The world embeds the
    exact stored pack binding, state model, transition, and observation
    binding snapshots so the compiled world verifies and replays
    byte-identically.
    """
    effective_scenario = scenario if scenario is not None else build_observation_scenario()
    binding = store.get_domain_pack_binding(TENANT, "scenario-1", "manifest-1")
    state_model = store.get_domain_state_model(TENANT, "scenario-1", "manifest-1", "sm-1")
    stored_transitions = store.list_domain_state_transitions(TENANT, "scenario-1")
    transitions: tuple[DomainStateTransition, ...] = tuple(
        transition for transition in stored_transitions if transition.transition_id == "t-1"
    )
    observations: tuple[DomainMetricObservationBinding, ...] = tuple(
        store.list_domain_metric_observations(TENANT, "scenario-1")
    )
    compiled = compile_world(
        effective_scenario,
        bindings=(binding,),
        state_models=(state_model,),
        transitions=transitions,
        domain_metric_observations=observations,
    )
    store.put_world(compiled.version, compiled.manifest)
    return compiled.version.identifier


def build_complete_observation_run(
    *,
    store: InMemoryScenarioStore | None = None,
    with_bindings: bool = True,
    with_transition: bool = True,
    execute: bool = True,
    scenario: ScenarioSpec | None = None,
) -> tuple[InMemoryScenarioStore, str, str]:
    """A COMPLETE trajectory-runtime run over a world embedding the bindings.

    Returns ``(store, world_version_id, run_id)``. The campaign is
    prepared under runtime version 2.0.0, its trajectory-plan collection
    is prepared through the Phase 15 service, the campaign is started,
    and every planned run is executed (run COMPLETE with a stored
    ``RunTrajectoryExecution``) unless ``execute`` is false.
    """
    effective_store = build_observation_store(
        store=store,
        with_bindings=with_bindings,
        with_transition=with_transition,
        scenario=scenario,
    )
    world_version_id = compile_observation_world(effective_store, scenario=scenario)
    prepare(
        effective_store,
        world_version_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        campaign_id="campaign-1",
    )
    prepare_strategy_trajectory_plans(
        store=effective_store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        campaign_id="campaign-1",
    )
    start(effective_store, "campaign-1")
    if execute:
        execute_campaign(store=effective_store, tenant_id=TENANT, campaign_id="campaign-1")
    run_id = run_identifier(effective_store.get_run_plans(TENANT, "campaign-1")[0])
    return effective_store, world_version_id, run_id
