"""Verified read-only campaign trajectory matrix query (Phase 18).

Phase 18 exposes the deterministic campaign trajectory matrix of one
completed runtime-2.0.0 campaign - the exact authoritative strategy x
shared-seed run matrix assembled from every verified Phase 16
``RunTrajectoryExecution`` of that campaign - through a strictly
read-only, tenant-scoped application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped campaign and its campaign status; unknown or
   foreign campaigns fail with the store's typed not-found error (404).
2. Require the campaign to be exactly COMPLETE - anything else raises
   :class:`CampaignNotCompleteError` (409 invalid_state).
3. Load and verify the compiled world snapshot (``verify_world_snapshot``);
   a missing world inside a completed campaign is a matrix integrity
   failure, a corrupted world fails through the typed integrity mapping.
4. Load the exact authoritative strategy candidates and the ordered
   RunPlan matrix and verify them with the existing authoritative
   run-plan matrix preflight (``preflight_run_plan_matrix``) - the
   stored candidate tuple must equal the campaign strategy order and the
   stored run plans must equal the deterministically recomputed matrix
   exactly, with every expected run passing the existing run-input
   integrity verification. A legacy or unsupported recorded runtime
   raises :class:`UnsupportedRuntimeVersionError` (409 conflict);
   corrupted records raise the typed integrity error.
5. For every run, load and verify its stored trajectory execution
   through the existing Phase 17 verified execution query path. A
   missing or corrupted execution - or missing/corrupted trajectory
   plans - inside a COMPLETE 2.0.0 campaign is a campaign matrix
   integrity failure and raises :class:`CampaignTrajectoryMatrixIntegrityError`
   (409 integrity_error); the complete collection is verified before
   anything is returned.
6. Build the complete matrix in memory through the pure builder and
   return it directly without storing it.

The query is deterministic, read-only, all-or-nothing, and tenant-
scoped: it never executes, replays, evaluates, regenerates, repairs, or
writes anything, records no operational activity, and changes no
lifecycle state. A missing or corrupt execution inside a COMPLETE 2.0.0
campaign means no matrix response - a partial matrix is never returned.

The service is pure application logic: no FastAPI, no LEGION/NEXUS calls
or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access.
"""

from __future__ import annotations

from kalhas.application.campaign_trajectory_runtime import (
    build_campaign_trajectory_matrix,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    CampaignTrajectoryMatrixIntegrityError,
    RunNotFoundError,
    RunTrajectoryExecutionNotFoundError,
    StoredTrajectoryPlanIntegrityError,
    TrajectoryPlansRequiredError,
    WorldNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.strategy_trajectory_service import (
    preflight_run_plan_matrix,
)
from kalhas.application.trajectory_query_service import (
    get_verified_run_trajectory_execution,
)
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryExecution


def get_verified_campaign_trajectory_matrix(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignTrajectoryMatrix:
    """Load and fully verify a completed campaign's trajectory matrix.

    Assembles the complete strategy x shared-seed matrix of one COMPLETE
    runtime-2.0.0 campaign from its verified stored records: the
    campaign, status, compiled world snapshot, stored strategy
    candidates, campaign seed ensemble, ordered RunPlan matrix, and the
    verified ``RunTrajectoryExecution`` of every run (Phase 17 verified
    query path). Every recorded run must use runtime 2.0.0; the complete
    collection is verified before anything is returned, and the matrix
    is built in memory through the pure builder and returned without
    being stored. Unknown or foreign campaigns raise the typed
    not-found error (404); non-COMPLETE campaigns raise
    :class:`CampaignNotCompleteError` (409 invalid_state); legacy or
    unsupported runtime raises :class:`UnsupportedRuntimeVersionError`
    (409 conflict); and missing, inconsistent, or corrupted matrix
    inputs or executions raise the typed matrix integrity error (409
    integrity_error). A partial matrix is never returned.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        world_manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError:
        raise CampaignTrajectoryMatrixIntegrityError(
            campaign_id, reason="compiled world missing"
        ) from None
    verify_world_snapshot(world, world_manifest)

    try:
        strategies = store.get_strategy_candidates(tenant_id, campaign_id)
        run_plans = store.get_run_plans(tenant_id, campaign_id)
    except CampaignNotFoundError:
        raise CampaignTrajectoryMatrixIntegrityError(
            campaign_id, reason="campaign records missing"
        ) from None

    # The existing authoritative run-plan matrix check: the stored
    # strategy candidate tuple must equal the campaign strategy order
    # exactly, and the stored run plans must equal the deterministically
    # recomputed matrix exactly (legacy/unsupported recorded runtime is
    # rejected first, every expected run then passes the existing
    # run-input integrity verification).
    preflight_run_plan_matrix(store=store, tenant_id=tenant_id, campaign=campaign, world=world)

    executions: list[RunTrajectoryExecution] = []
    for plan in run_plans:
        try:
            executions.append(
                get_verified_run_trajectory_execution(
                    store=store, tenant_id=tenant_id, run_id=run_identifier(plan)
                )
            )
        except (
            RunTrajectoryExecutionNotFoundError,
            RunNotFoundError,
            TrajectoryPlansRequiredError,
            StoredTrajectoryPlanIntegrityError,
        ) as exc:
            raise CampaignTrajectoryMatrixIntegrityError(
                campaign_id, reason="run trajectory execution missing or corrupted"
            ) from exc

    return build_campaign_trajectory_matrix(
        campaign=campaign,
        world=world,
        strategies=strategies,
        seeds=campaign.seed_ensemble,
        run_plans=run_plans,
        executions=tuple(executions),
    )
