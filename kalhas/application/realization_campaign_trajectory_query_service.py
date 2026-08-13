"""Verified read-only runtime-3 realization-aware campaign trajectory matrix query (Phase 25).

``get_verified_realization_campaign_trajectory_matrix`` assembles the
complete strategy x shared-seed trajectory matrix of one COMPLETE
runtime-3.0.0 campaign **strictly from verified stored records**, never
storing the derived matrix:

1. Load the tenant-scoped ``CampaignSpec`` and ``CampaignStatus``; the
   campaign must be COMPLETE (typed invalid-state error otherwise).
2. Load the compiled world and its manifest and run
   ``verify_world_snapshot`` before any matrix work.
3. Load the stored strategy candidates and RunPlans.
4. Call the existing read-only ``preflight_realization_run_plan_matrix``
   **exactly once** (complete strategy x seed matrix, recorded runtime
   exactly 3.0.0, stored<->embedded uncertainty-model consistency,
   deterministic realization-matrix reconstruction, exact runtime-3
   input hashes, per-run input integrity).
5. For every RunPlan in stored order: ``verify_run_trajectory_inputs``
   exactly once (non-None realization required), the stored
   ``RealizationRunTrajectoryExecution`` loaded through the store
   boundary and fully verified by
   ``verify_realization_run_trajectory_execution_record`` exactly once,
   the verified execution collected, and exactly one authoritative
   realization collected per seed - every strategy using that seed must
   produce the exact same realization.
6. Only after every run is verified, call the pure matrix builder
   **exactly once** with exactly K realizations in
   ``campaign.seed_ensemble`` order and return the derived matrix.

A missing or corrupt first, middle, or last execution prevents any
matrix response - a partial matrix is never returned. The query is
strictly read-only: no input-integrity manifests, no activity events, no
execution/observation/replay/matrix writes, no lifecycle change, and no
LEGION calls.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    RunNotFoundError,
    WorldNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_service import (
    preflight_realization_run_plan_matrix,
)
from kalhas.application.realization_campaign_trajectory_runtime import (
    build_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_errors import (
    RealizationCampaignTrajectoryMatrixIntegrityError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryExecutionNotFoundError,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_execution_record,
)
from kalhas.application.run_planner import run_identifier
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
)
from kalhas.contracts.v1.world_realization import WorldRealization


def _matrix_reject(
    campaign_id: str, reason: str
) -> RealizationCampaignTrajectoryMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return RealizationCampaignTrajectoryMatrixIntegrityError(campaign_id, reason)


def get_verified_realization_campaign_trajectory_matrix(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> RealizationCampaignTrajectoryMatrix:
    """Load and fully verify a completed campaign's realization trajectory matrix.

    Assembled strictly from verified stored records of one COMPLETE
    runtime-3.0.0 campaign and returned without being stored. Unknown or
    foreign campaigns raise the typed not-found error; non-COMPLETE
    campaigns raise the typed invalid-state error; a missing, corrupted,
    or inconsistent first/middle/last execution - or any other matrix
    inconsistency - raises the typed matrix integrity error and never
    returns a partial matrix. Strictly read-only.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        world_manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError:
        raise _matrix_reject(campaign_id, "compiled world missing") from None
    verify_world_snapshot(world, world_manifest)

    try:
        strategies = store.get_strategy_candidates(tenant_id, campaign_id)
        run_plans = store.get_run_plans(tenant_id, campaign_id)
    except CampaignNotFoundError:
        raise _matrix_reject(campaign_id, "campaign records missing") from None

    # The existing authoritative complete run-plan matrix preflight runs
    # exactly once, before any per-run verification.
    preflight_realization_run_plan_matrix(store, tenant_id, campaign, world)

    realizations_by_seed: dict[str, WorldRealization] = {}
    executions: list[RealizationRunTrajectoryExecution] = []
    for plan in run_plans:
        run_id = run_identifier(plan)
        try:
            trajectory_inputs = verify_run_trajectory_inputs(
                store=store, tenant_id=tenant_id, run_id=run_id
            )
        except RunNotFoundError as exc:
            raise _matrix_reject(
                campaign_id, reason="run trajectory inputs missing or corrupted"
            ) from exc
        if trajectory_inputs.realization is None:
            raise _matrix_reject(
                campaign_id, reason="run realization missing after trajectory verification"
            )
        realization = trajectory_inputs.realization
        try:
            execution = store.get_realization_run_trajectory_execution(tenant_id, run_id)
        except RealizationRunTrajectoryExecutionNotFoundError as exc:
            raise _matrix_reject(
                campaign_id, reason="run realization execution missing or corrupted"
            ) from exc
        try:
            verify_realization_run_trajectory_execution_record(
                execution,
                inputs=trajectory_inputs.inputs,
                plans=trajectory_inputs.plans,
                catalogs=trajectory_inputs.catalogs,
                realization=realization,
            )
        except RealizationRunTrajectoryExecutionIntegrityError as exc:
            raise _matrix_reject(
                campaign_id, reason="run realization execution missing or corrupted"
            ) from exc
        executions.append(execution)

        # Exactly one authoritative realization per seed; every strategy
        # sharing the seed must produce the exact same realization.
        previous = realizations_by_seed.get(realization.scenario_seed_id)
        if previous is None:
            realizations_by_seed[realization.scenario_seed_id] = realization
        elif previous != realization:
            raise _matrix_reject(campaign_id, reason="shared seed realization inconsistency")

    realizations = tuple(realizations_by_seed[seed.identifier] for seed in campaign.seed_ensemble)
    if len(realizations) != len(campaign.seed_ensemble):
        raise _matrix_reject(campaign_id, reason="realization collection incomplete")

    return build_realization_campaign_trajectory_matrix(
        campaign=campaign,
        world=world,
        strategies=strategies,
        seeds=campaign.seed_ensemble,
        run_plans=run_plans,
        executions=tuple(executions),
        realizations=realizations,
    )
