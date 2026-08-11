"""Shared helpers for Phase 24 world-uncertainty tests.

Builds stores with controlled initial-state fields (including
``allowed_values`` variants), declares uncertainty models through the
real Phase 24 declaration service, compiles worlds through the real
mock-NEXUS compilation path, and prepares campaigns under runtime
2.0.0 - so focused tests exercise the exact production seams instead of
hand-built fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from kalhas.application.domain_state_model_service import declare_state_model
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    StateValueKind,
)
from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

from tests.phase4_helpers import TENANT, build_scenario, build_seed, prepare
from tests.phase20_helpers import DECLARED_AT, _register_pack

MODEL_DECLARED_AT = datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)


def state_field(
    identifier: str,
    value_kind: StateValueKind,
    initial_value: JsonValue,
    allowed_values: tuple[JsonValue, ...] = (),
) -> DomainStateFieldDefinition:
    """One controlled state-field definition (with optional allowed values)."""
    return DomainStateFieldDefinition(
        identifier=identifier,
        description="Declared state field",
        value_kind=value_kind,
        initial_value=initial_value,
        allowed_values=allowed_values,
    )


def uncertainty_fields(
    *,
    level_allowed: tuple[JsonValue, ...] = (),
    ratio_allowed: tuple[JsonValue, ...] = (),
) -> tuple[DomainStateFieldDefinition, ...]:
    """Numeric fields (level/ratio) plus a non-numeric field.

    ``level`` is an integer field with initial value 0, ``ratio`` a
    number field with initial value 0.0, and ``status`` a string field
    (never targetable by an uncertainty binding).
    """
    return (
        state_field("level", StateValueKind.INTEGER, 0, level_allowed),
        state_field("ratio", StateValueKind.NUMBER, 0.0, ratio_allowed),
        state_field("status", StateValueKind.STRING, "idle"),
    )


def build_uncertainty_store(
    *,
    store: InMemoryScenarioStore | None = None,
    level_allowed: tuple[JsonValue, ...] = (),
    ratio_allowed: tuple[JsonValue, ...] = (),
) -> InMemoryScenarioStore:
    """A store with scenario, pack binding, and a controlled state model.

    The state model carries ``level`` (integer), ``ratio`` (number),
    and ``status`` (string) with optional ``allowed_values`` on the two
    numeric fields. No transition, metric observation, or evaluation
    profile is declared - Phase 24 needs none of them.
    """
    effective_store = store if store is not None else InMemoryScenarioStore()
    effective_store.put_scenario(build_scenario())
    _register_pack(effective_store)
    declare_state_model(
        effective_store,
        tenant_id=TENANT,
        scenario_id="scenario-1",
        manifest_id="manifest-1",
        state_model_id="sm-1",
        state_fields=uncertainty_fields(level_allowed=level_allowed, ratio_allowed=ratio_allowed),
        declared_at=DECLARED_AT,
    )
    return effective_store


def declare_model(
    store: InMemoryScenarioStore,
    *,
    bindings: tuple[UncertaintyBindingDraft, ...],
    tenant_id: str = TENANT,
    scenario_id: str = "scenario-1",
    declared_at: datetime = MODEL_DECLARED_AT,
    metadata: dict[str, JsonValue] | None = None,
) -> WorldUncertaintyModel:
    """Declare an uncertainty model through the real declaration service."""
    return declare_world_uncertainty_model(
        store,
        tenant_id=tenant_id,
        scenario_id=scenario_id,
        bindings=bindings,
        declared_at=declared_at,
        metadata=metadata,
    )


def prepared_campaign(
    store: InMemoryScenarioStore,
    *,
    world_version_id: str,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
) -> str:
    """Prepare a runtime-2.0.0 campaign on the compiled world.

    Returns the campaign identifier. Uses the real Phase 4 preparation
    seam with the mock LEGION ensemble (which always returns the same
    five deterministic strategy candidates).
    """
    from kalhas.adapters.mocks import MockLegionAdapter
    from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION

    prepare(
        store,
        world_version_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        seeds=seeds,
        campaign_id=campaign_id,
    )
    return campaign_id
