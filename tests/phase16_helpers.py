"""Shared helpers for Phase 16 trajectory execution and replay tests.

Builds compiler-consistent worlds embedding deterministic state models
and transitions, prepares trajectory-runtime (2.0.0) campaigns, prepares
their immutable trajectory-plan collections through the Phase 15
service, and starts them - the full recorded-input setup a trajectory
run needs. Also provides a scripted LEGION adapter for controlling the
proposed transition sequence (repetitions, partial sequences).
"""

from __future__ import annotations

from collections.abc import Callable

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_state_model_service import (
    state_model_content_hash,
    state_model_identifier,
)
from kalhas.application.domain_state_transition_service import (
    transition_content_hash,
    transition_identifier,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.world_compiler import compile_world
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.trajectory import (
    StrategyTrajectoryPlanDraft,
    StrategyTrajectoryPlanRequest,
)
from kalhas.contracts.v1.transition import DomainStateTransition

from tests.phase4_helpers import (
    NOW,
    TENANT,
    build_scenario,
    build_seed,
    prepare,
    start,
)

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

SM_1_IDENTIFIER = state_model_identifier(
    scenario_id="scenario-1", manifest_id="manifest-1", state_model_id="sm-1"
)
SM_2_IDENTIFIER = state_model_identifier(
    scenario_id="scenario-1", manifest_id="manifest-2", state_model_id="sm-2"
)


class ScriptedTrajectoryLegion(MockLegionAdapter):
    """MockLegionAdapter whose trajectory drafts follow a per-request script.

    The script receives the authoritative request and returns the draft;
    strategy requests keep the deterministic mock behavior.
    """

    def __init__(
        self,
        script: Callable[[StrategyTrajectoryPlanRequest], StrategyTrajectoryPlanDraft],
    ) -> None:
        self._script = script
        self.trajectory_requests: list[StrategyTrajectoryPlanRequest] = []

    def request_trajectory_plan(
        self, request: StrategyTrajectoryPlanRequest
    ) -> StrategyTrajectoryPlanDraft:
        self.trajectory_requests.append(request)
        return self._script(request)


def build_model(
    *,
    state_model_id: str = "sm-1",
    manifest_id: str = "manifest-1",
    field: str = "status",
    value_kind: StateValueKind = StateValueKind.STRING,
    initial_value: JsonValue = "idle",
    allowed_values: tuple[JsonValue, ...] | None = None,
    binding_id: str | None = None,
    pack_id: str | None = None,
) -> DomainStateModel:
    """A state model with a deterministic identifier and self-consistent hash."""
    field_payload: dict[str, object] = {
        "identifier": field,
        "description": "Declared state field",
        "value_kind": value_kind,
        "initial_value": initial_value,
    }
    if allowed_values is not None:
        field_payload["allowed_values"] = allowed_values
    model = DomainStateModel(
        identifier=state_model_identifier(
            scenario_id="scenario-1",
            manifest_id=manifest_id,
            state_model_id=state_model_id,
        ),
        tenant_id=TENANT,
        scenario_id="scenario-1",
        binding_id=binding_id or f"binding-{state_model_id}",
        manifest_id=manifest_id,
        pack_id=pack_id or f"pack-{state_model_id}",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id=state_model_id,
        state_fields=(DomainStateFieldDefinition.model_validate(field_payload),),
        content_hash="0" * 64,
        declared_at=NOW,
        metadata={},
    )
    return model.model_copy(update={"content_hash": state_model_content_hash(model)})


def build_transition(
    model: DomainStateModel,
    *,
    transition_id: str = "t-1",
    guard_values: dict[str, JsonValue] | None = None,
    target_values: dict[str, JsonValue] | None = None,
) -> DomainStateTransition:
    """A transition of the model with a deterministic identifier and hash.

    Guard/target default to the model's first field: ``initial_value``
    -> the string ``"active"`` (or the boolean ``True`` / number ``1``
    for non-string kinds).
    """
    field = model.state_fields[0].identifier
    kind = model.state_fields[0].value_kind
    if kind is StateValueKind.BOOLEAN:
        default_target: JsonValue = True
    elif kind is StateValueKind.INTEGER or kind is StateValueKind.NUMBER:
        default_target = 1
    else:
        default_target = "active"
    if guard_values is None:
        guard_values = {field: model.state_fields[0].initial_value}
    if target_values is None:
        target_values = {field: default_target}
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
        guard_values=guard_values,
        target_values=target_values,
        content_hash="0" * 64,
        declared_at=NOW,
        metadata={},
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


def build_trajectory_store(
    *,
    state_models: tuple[DomainStateModel, ...] = (),
    transitions: tuple[DomainStateTransition, ...] = (),
    legion: MockLegionAdapter | None = None,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
) -> tuple[InMemoryScenarioStore, str]:
    """A started trajectory-runtime campaign with prepared plans.

    Returns ``(store, world_version_id)``. The campaign is prepared under
    runtime version 2.0.0, its complete trajectory-plan collection is
    prepared through the Phase 15 service (the same legion instance
    serves both strategy requests and trajectory drafts), and the
    campaign is started (RUNNING). With no state models the world is
    plain and the prepared plan collection is the empty tuple.
    """
    effective_legion = legion if legion is not None else MockLegionAdapter()
    store = InMemoryScenarioStore()
    store.put_scenario(build_scenario())
    compiled = compile_world(
        build_scenario(),
        state_models=state_models,
        transitions=transitions,
    )
    store.put_world(compiled.version, compiled.manifest)
    prepare(
        store,
        compiled.version.identifier,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=effective_legion,
        seeds=seeds,
        campaign_id=campaign_id,
    )
    prepare_strategy_trajectory_plans(
        store=store,
        legion=effective_legion,
        tenant_id=TENANT,
        campaign_id=campaign_id,
    )
    start(store, campaign_id)
    return store, compiled.version.identifier
