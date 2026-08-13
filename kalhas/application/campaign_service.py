"""Deterministic campaign preparation and lifecycle operations.

Preparation is pure orchestration over the in-memory store and the
``LegionAdapter`` protocol: it verifies inputs, plans runs, and stores a
COMPILED status. It never executes runs, never marks a campaign COMPLETE,
and never fabricates outcomes, evidence, or events. Starting a campaign
performs only the COMPILED -> RUNNING transition.

The service depends on the ``LegionAdapter`` protocol, never on a concrete
adapter class; concrete adapters appear only in composition/wiring code.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalhas.adapters.legion import LegionAdapter
from kalhas.application.campaign_lifecycle import transition
from kalhas.application.domain_errors import (
    CampaignPreparationError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldScenarioMismatchError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    plan_runs,
    run_identifier,
)
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime
from kalhas.contracts.v1.strategy import StrategyRequest

EXPECTED_STRATEGY_SET_SIZE = 5


@dataclass(frozen=True)
class PreparedCampaign:
    """Campaign plus its COMPILED status and the full ordered run plan set."""

    campaign: CampaignSpec
    status: CampaignStatus
    run_plans: tuple[RunPlan, ...]


def prepare_campaign(
    *,
    store: InMemoryScenarioStore,
    legion: LegionAdapter,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
    strategy_request: StrategyRequest,
    campaign_id: str,
    campaign_name: str,
    seed_ensemble: tuple[ScenarioSeed, ...],
    created_at: AwareDatetime,
    runtime_version: str = RUNTIME_VERSION,
) -> PreparedCampaign:
    """Prepare a campaign: verify inputs, plan runs, store COMPILED state.

    The stored world must pass compiled-world integrity verification
    (``verify_world_snapshot``) before LEGION is called and before any
    campaign or run state is written; a corrupted world raises
    :class:`WorldSnapshotIntegrityError`.

    Tenant invariants are enforced here with typed domain errors: the
    explicit tenant must own the scenario, the world, the strategy request,
    every seed, and every returned strategy candidate.

    This service supports exactly the structural (1.0.0) and trajectory
    (2.0.0) runtime versions. Runtime 3.0.0 campaigns are prepared by
    ``prepare_realization_campaign`` in ``realization_campaign_service``;
    any other recorded value is rejected with a typed
    :class:`UnsupportedRuntimeVersionError` before any store read, world
    verification, LEGION call, or write.
    """
    if runtime_version not in (LEGACY_STRUCTURAL_RUNTIME_VERSION, TRAJECTORY_RUNTIME_VERSION):
        raise UnsupportedRuntimeVersionError(runtime_version, operation="campaign preparation")
    scenario = store.get_scenario(tenant_id, scenario_id)
    world = store.get_world(tenant_id, world_version_id)
    if world.source_scenario_id != scenario.identifier:
        raise WorldScenarioMismatchError(world_version_id, scenario.identifier)
    # Compiled-world integrity is verified before LEGION is called and
    # before any campaign/run state is written: a corrupted or
    # non-compiler world must never be planned against.
    try:
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError:
        raise WorldSnapshotIntegrityError(
            world_version_id, reason="world manifest missing"
        ) from None
    verify_world_snapshot(world, manifest)
    if strategy_request.scenario_id != scenario.identifier:
        raise CampaignPreparationError(
            f"strategy_request.scenario_id {strategy_request.scenario_id!r} does not match "
            f"scenario {scenario.identifier!r}"
        )
    if strategy_request.tenant_id != tenant_id:
        raise CampaignPreparationError(
            f"strategy_request tenant_id {strategy_request.tenant_id!r} does not match "
            f"tenant {tenant_id!r}"
        )
    for seed in seed_ensemble:
        if seed.tenant_id != tenant_id:
            raise CampaignPreparationError(
                f"seed {seed.identifier!r} tenant_id {seed.tenant_id!r} does not match "
                f"tenant {tenant_id!r}"
            )

    candidates = legion.request_strategies(strategy_request)
    if len(candidates) != EXPECTED_STRATEGY_SET_SIZE:
        raise CampaignPreparationError(
            f"expected {EXPECTED_STRATEGY_SET_SIZE} strategy candidates, got {len(candidates)}"
        )
    candidate_ids = [candidate.identifier for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise CampaignPreparationError("returned strategy candidate identifiers must be unique")
    expected_observations = [obs.model_dump() for obs in strategy_request.required_observations]
    for candidate in candidates:
        if candidate.tenant_id != tenant_id:
            raise CampaignPreparationError(
                f"candidate {candidate.identifier!r} tenant_id {candidate.tenant_id!r} does not "
                f"match tenant {tenant_id!r}"
            )
        if [obs.model_dump() for obs in candidate.required_observations] != expected_observations:
            raise CampaignPreparationError(
                f"candidate {candidate.identifier!r} does not share identical ordered "
                "observation permissions with the requested strategy set"
            )

    campaign = CampaignSpec(
        identifier=campaign_id,
        tenant_id=tenant_id,
        name=campaign_name,
        scenario_id=scenario.identifier,
        world_version_id=world.identifier,
        strategy_candidate_ids=candidate_ids,
        seed_ensemble=seed_ensemble,
        created_at=created_at,
    )
    status = CampaignStatus(
        identifier=f"status-{campaign_id}",
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        state=CampaignState.COMPILED,
        changed_at=created_at,
        message="campaign prepared",
    )
    plans = plan_runs(
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=candidates,
        seeds=seed_ensemble,
        created_at=created_at,
        runtime_version=runtime_version,
    )
    store.put_campaign(campaign, status)
    store.put_run_plans(tenant_id, campaign_id, plans)
    store.put_strategy_candidates(tenant_id, campaign_id, candidates)
    for plan in plans:
        run_id = run_identifier(plan)
        store.put_run_status(
            tenant_id,
            run_id,
            RunStatus(
                identifier=f"status-{run_id}",
                tenant_id=tenant_id,
                run_id=run_id,
                campaign_id=campaign_id,
                run_plan_id=plan.identifier,
                state=RunState.PLANNED,
                runtime_version=plan.runtime_version,
                input_hash=plan.input_hash,
                created_at=plan.created_at,
                changed_at=plan.created_at,
            ),
        )
    return PreparedCampaign(campaign=campaign, status=status, run_plans=plans)


def start_campaign(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
    changed_at: AwareDatetime,
) -> CampaignStatus:
    """Perform only the COMPILED -> RUNNING lifecycle transition.

    Does not execute simulations and does not fabricate results. A started
    campaign remains RUNNING with its immutable planned runs available.
    """
    current = store.get_campaign_status(tenant_id, campaign_id)
    next_state = transition(current.state, CampaignState.RUNNING)
    updated = CampaignStatus(
        identifier=current.identifier,
        tenant_id=current.tenant_id,
        campaign_id=campaign_id,
        state=next_state,
        changed_at=changed_at,
        message="campaign started",
    )
    store.update_campaign_status(tenant_id, campaign_id, updated)
    return updated
