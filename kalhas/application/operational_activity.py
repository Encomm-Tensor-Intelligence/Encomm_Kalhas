"""Operational activity recording helpers.

Each helper appends exactly one immutable tenant-local
``OperationalActivityEvent`` after a successful operation, deriving the
deterministic ``occurred_at`` from the already-recorded source contract
(scenario ``created_at``, world ``created_at``, manifest ``created_at``,
binding ``bound_at``, declaration ``declared_at``, campaign status
``changed_at``, integrity manifest ``recorded_at``, replay manifest
``created_at``) - never the wall clock.

Payloads carry only safe structural facts for the owning tenant:
identifiers, contract/runtime/compiler versions, event counts, lifecycle
states, and hashes already exposed by the source contracts. Raw
capability input values, policy rules, hidden reasoning, provider data,
outcomes, evidence, recommendations, and executable content are never
recorded.

This feed is operational observability only: it is not a simulation event
stream, not evidence, not hidden reasoning, and not part of any
``WorldVersion``, ``RunPlan``, input-integrity hash, event hash, or replay
guarantee. Recording activity never mutates any other store collection.
"""

from __future__ import annotations

from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.activity import OperationalActivityEvent, OperationalActivityKind
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignStatus
from kalhas.contracts.v1.domain_pack import (
    DomainCapabilityDeclaration,
    DomainPackBinding,
    DomainPackManifest,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunState, RunStatus
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.scenario import ScenarioSpec
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldVersion


def record_scenario_registered(
    store: InMemoryScenarioStore, *, tenant_id: str, scenario: ScenarioSpec
) -> OperationalActivityEvent:
    """Record scenario registration after the scenario was stored."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.SCENARIO_REGISTERED,
        occurred_at=scenario.created_at,
        scenario_id=scenario.identifier,
        payload={"schema_version": scenario.schema_version},
    )


def record_world_compiled(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    scenario_id: str,
    world: WorldVersion,
) -> OperationalActivityEvent:
    """Record world compilation after the world was compiled and stored."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.WORLD_COMPILED,
        occurred_at=world.created_at,
        scenario_id=scenario_id,
        world_version_id=world.identifier,
        payload={
            "compiler_version": world.compiler_version,
            "content_hash": world.content_hash,
        },
    )


def record_domain_pack_registered(
    store: InMemoryScenarioStore, *, tenant_id: str, manifest: DomainPackManifest
) -> OperationalActivityEvent:
    """Record manifest registration after the manifest was stored."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.DOMAIN_PACK_REGISTERED,
        occurred_at=manifest.created_at,
        manifest_id=manifest.identifier,
        payload={
            "pack_id": manifest.pack_id,
            "pack_version": manifest.pack_version,
            "content_hash": manifest.content_hash,
        },
    )


def record_domain_pack_bound(
    store: InMemoryScenarioStore, *, tenant_id: str, binding: DomainPackBinding
) -> OperationalActivityEvent:
    """Record binding after the manifest was bound to the scenario."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.DOMAIN_PACK_BOUND,
        occurred_at=binding.bound_at,
        scenario_id=binding.scenario_id,
        manifest_id=binding.manifest_id,
        binding_id=binding.identifier,
        payload={
            "pack_id": binding.pack_id,
            "pack_version": binding.pack_version,
            "capability_count": len(binding.capability_ids),
        },
    )


def record_capability_inputs_declared(
    store: InMemoryScenarioStore, *, tenant_id: str, declaration: DomainCapabilityDeclaration
) -> OperationalActivityEvent:
    """Record a capability declaration (key count only - never the values)."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.CAPABILITY_INPUTS_DECLARED,
        occurred_at=declaration.declared_at,
        scenario_id=declaration.scenario_id,
        manifest_id=declaration.manifest_id,
        binding_id=declaration.binding_id,
        declaration_id=declaration.identifier,
        payload={
            "pack_version": declaration.pack_version,
            "input_key_count": len(declaration.input_values),
        },
    )


def record_domain_state_model_declared(
    store: InMemoryScenarioStore, *, tenant_id: str, state_model: DomainStateModel
) -> OperationalActivityEvent:
    """Record a state-model declaration (safe identifiers and hashes only).

    The payload carries only safe structural facts: the state-model id,
    the model content hash, and the state-field count. State field
    initial values, allowed values, descriptions, and metadata are never
    recorded.
    """
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.DOMAIN_STATE_MODEL_DECLARED,
        occurred_at=state_model.declared_at,
        scenario_id=state_model.scenario_id,
        manifest_id=state_model.manifest_id,
        binding_id=state_model.binding_id,
        payload={
            "state_model_id": state_model.state_model_id,
            "content_hash": state_model.content_hash,
            "state_field_count": len(state_model.state_fields),
        },
    )


def record_domain_state_transition_declared(
    store: InMemoryScenarioStore, *, tenant_id: str, transition: DomainStateTransition
) -> OperationalActivityEvent:
    """Record a transition declaration (safe identifiers and hashes only).

    The payload carries only safe structural facts: the referenced state
    model id, the transition id, the transition content hash, and the
    guard/target field counts. Descriptions, guard values, target values,
    metadata, and state field values are never recorded.
    """
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.DOMAIN_STATE_TRANSITION_DECLARED,
        occurred_at=transition.declared_at,
        scenario_id=transition.scenario_id,
        manifest_id=transition.manifest_id,
        binding_id=transition.binding_id,
        payload={
            "state_model_id": transition.state_model_id,
            "transition_id": transition.transition_id,
            "content_hash": transition.content_hash,
            "guard_field_count": len(transition.guard_values),
            "target_field_count": len(transition.target_values),
        },
    )


def record_campaign_prepared(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign: CampaignSpec,
    status: CampaignStatus,
    run_plan_count: int,
) -> OperationalActivityEvent:
    """Record campaign preparation after the campaign was stored COMPILED."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.CAMPAIGN_PREPARED,
        occurred_at=status.changed_at,
        campaign_id=campaign.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=campaign.world_version_id,
        payload={
            "lifecycle_state": status.state.value,
            "run_plan_count": run_plan_count,
            "strategy_candidate_count": len(campaign.strategy_candidate_ids),
        },
    )


def record_campaign_started(
    store: InMemoryScenarioStore, *, tenant_id: str, status: CampaignStatus
) -> OperationalActivityEvent:
    """Record the COMPILED -> RUNNING transition after it succeeded."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.CAMPAIGN_STARTED,
        occurred_at=status.changed_at,
        campaign_id=status.campaign_id,
        payload={"lifecycle_state": status.state.value},
    )


def record_campaign_executed(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    status: CampaignStatus,
    run_statuses: tuple[RunStatus, ...],
) -> OperationalActivityEvent:
    """Record successful structural execution of every planned run."""
    completed_count = sum(1 for run_status in run_statuses if run_status.state is RunState.COMPLETE)
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.CAMPAIGN_EXECUTED,
        occurred_at=status.changed_at,
        campaign_id=campaign_id,
        payload={
            "lifecycle_state": status.state.value,
            "run_count": len(run_statuses),
            "completed_run_count": completed_count,
        },
    )


def record_run_inputs_verified(
    store: InMemoryScenarioStore, *, tenant_id: str, manifest: RunInputIntegrityManifest
) -> OperationalActivityEvent:
    """Record successful input verification through the API."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.RUN_INPUTS_VERIFIED,
        occurred_at=manifest.recorded_at,
        run_id=manifest.run_id,
        campaign_id=manifest.campaign_id,
        world_version_id=manifest.world_version_id,
        payload={
            "runtime_version": manifest.runtime_version,
            "verification_classification": manifest.verification_classification,
        },
    )


def record_run_replayed(
    store: InMemoryScenarioStore, *, tenant_id: str, manifest: ReplayManifest
) -> OperationalActivityEvent:
    """Record a successful exact replay."""
    return store.append_operational_activity(
        tenant_id=tenant_id,
        kind=OperationalActivityKind.RUN_REPLAYED,
        occurred_at=manifest.created_at,
        run_id=manifest.run_id,
        campaign_id=manifest.campaign_id,
        world_version_id=manifest.world_version_id,
        payload={
            "runtime_version": manifest.runtime_version,
            "replay_classification": manifest.replay_classification,
        },
    )


def list_activity(
    store: InMemoryScenarioStore,
    tenant_id: str,
    *,
    after_sequence: int | None = None,
    limit: int,
) -> tuple[OperationalActivityEvent, ...]:
    """Bounded, tenant-scoped activity retrieval in ascending sequence order."""
    return store.list_operational_activity(tenant_id, after_sequence=after_sequence, limit=limit)


def latest_sequence(store: InMemoryScenarioStore, tenant_id: str) -> int:
    """The tenant's latest activity sequence (-1 when no activity exists)."""
    return store.latest_activity_sequence(tenant_id)
