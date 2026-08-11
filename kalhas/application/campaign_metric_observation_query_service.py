"""Verified read-only campaign metric-observation matrix query (Phase 21).

Phase 21 exposes the deterministic campaign metric-observation matrix
of one completed runtime-2.0.0 campaign - the exact authoritative
strategy x shared-seed observation layout assembled from every
completely verified Phase 20 ``RunMetricObservationSet`` of that
campaign, in the exact order of the verified Phase 18
``CampaignTrajectoryMatrix`` - through a strictly read-only,
tenant-scoped application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped campaign and its campaign status; unknown or
   foreign campaigns fail with the store's typed not-found error (404).
2. Require the campaign to be exactly COMPLETE - anything else raises
   :class:`CampaignNotCompleteError` (409 invalid_state).
3. Obtain the completely verified Phase 18 ``CampaignTrajectoryMatrix``
   through the existing verified query service
   (``get_verified_campaign_trajectory_matrix``) - Phase 18 verification
   is never reimplemented or weakened, and its typed error mappings
   (404, 409 conflict for legacy/unsupported runtime, 409
   integrity_error for missing or corrupted matrix inputs) pass through
   unchanged.
4. Iterate the trajectory-matrix cells in their exact authoritative
   order and, for every run, obtain its Phase 20
   ``RunMetricObservationSet`` through the existing verified Phase 20
   query path (``get_verified_run_metric_observation_set``). Every
   Phase 20 artifact must already exist - nothing is ever extracted
   automatically.
5. A missing, foreign, partial, inconsistent, or corrupted run
   observation artifact inside an otherwise completed campaign rejects
   the entire matrix with :class:`CampaignMetricObservationMatrixIntegrityError`
   (409 integrity_error).
6. Build the complete matrix in memory through the pure builder and
   return it directly without storing it. A matrix that violates its
   own contract at construction time is also a typed integrity failure.

The query is deterministic, read-only, all-or-nothing, and tenant-
scoped: it never extracts, executes, replays, evaluates, regenerates,
repairs, or writes anything, records no operational activity, and
changes no lifecycle state. A missing or corrupt Phase 20 artifact
inside a COMPLETE 2.0.0 campaign means no matrix response - a partial
matrix is never returned.

The service is pure application logic: no FastAPI, no LEGION/NEXUS calls
or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.campaign_metric_observation_runtime import (
    build_campaign_metric_observation_matrix,
)
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.domain_errors import (
    CampaignMetricObservationMatrixIntegrityError,
    CampaignNotCompleteError,
    RunInputIntegrityError,
    RunMetricObservationIntegrityError,
    RunMetricObservationNotFoundError,
    RunNotCompleteError,
    RunNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_metric_observation_service import (
    get_verified_run_metric_observation_set,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.run_metric_observation import RunMetricObservationSet


def get_verified_campaign_metric_observation_matrix(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignMetricObservationMatrix:
    """Load and fully verify a completed campaign's metric-observation matrix.

    Assembles the complete strategy x shared-seed observation matrix of
    one COMPLETE runtime-2.0.0 campaign from its verified stored
    records: the campaign, status, the verified Phase 18
    ``CampaignTrajectoryMatrix`` (through the existing verified query
    service), and the verified Phase 20 ``RunMetricObservationSet`` of
    every run (through the existing verified query path). Every Phase
    20 artifact must already exist; the complete collection is verified
    before anything is returned, and the matrix is built in memory
    through the pure builder and returned without being stored.
    Unknown or foreign campaigns raise the typed not-found error (404);
    non-COMPLETE campaigns raise :class:`CampaignNotCompleteError` (409
    invalid_state); legacy or unsupported runtime raises
    :class:`UnsupportedRuntimeVersionError` (409 conflict); and
    missing, inconsistent, or corrupted Phase 20 artifacts - or an
    internally built matrix violating its contract - raise the typed
    matrix integrity error (409 integrity_error). A partial matrix is
    never returned.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    # The completely verified Phase 18 trajectory matrix is the
    # authoritative strategy x shared-seed layout and cell order. Its
    # typed error mappings (404, 409 conflict for legacy/unsupported
    # runtime, 409 integrity_error for missing or corrupted matrix
    # inputs) pass through unchanged.
    trajectory_matrix = get_verified_campaign_trajectory_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )

    observation_sets: list[RunMetricObservationSet] = []
    for cell in trajectory_matrix.cells:
        try:
            observation_sets.append(
                get_verified_run_metric_observation_set(
                    store=store, tenant_id=tenant_id, run_id=cell.run_id
                )
            )
        except (
            RunMetricObservationNotFoundError,
            RunMetricObservationIntegrityError,
            RunInputIntegrityError,
            RunNotFoundError,
            RunNotCompleteError,
        ) as exc:
            raise CampaignMetricObservationMatrixIntegrityError(
                campaign_id, reason="run metric observation set missing or corrupted"
            ) from exc

    try:
        return build_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=tuple(observation_sets),
        )
    except ValidationError:
        raise CampaignMetricObservationMatrixIntegrityError(
            campaign_id, reason="internally built matrix violates its contract"
        ) from None
