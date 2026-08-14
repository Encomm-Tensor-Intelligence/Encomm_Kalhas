"""Verified read-only runtime-3 realization-aware campaign metric-observation matrix query.

Phase 25.

``get_verified_realization_campaign_metric_observation_matrix`` assembles
the complete strategy x shared-seed metric-observation matrix of one
COMPLETE runtime-3.0.0 campaign **strictly from verified stored records**,
never storing the derived matrix:

1. Load the tenant-scoped ``CampaignSpec`` and ``CampaignStatus``; the
   campaign must be COMPLETE (typed invalid-state error otherwise).
2. Call the existing verified trajectory-matrix query
   (``get_verified_realization_campaign_trajectory_matrix``) **exactly
   once** - its typed error mappings (404, 409 conflict for legacy or
   unsupported runtime, 409 integrity error for missing or corrupted
   trajectory records) pass through unchanged, and its complete strategy x
   shared-seed cell order is the authoritative layout.
3. Iterate the trajectory cells in their exact authoritative order and,
   for every cell, call the existing verified observation-set query
   (``get_verified_realization_run_metric_observation_set``) **exactly
   once**. Every set must already exist - nothing is ever extracted
   automatically.
4. A missing, foreign, partial, inconsistent, or corrupted set inside an
   otherwise completed campaign rejects the entire query through
   :class:`RealizationCampaignMetricObservationMatrixIntegrityError`.
5. Only after every set is verified, call the pure matrix builder
   **exactly once** and return the derived matrix without storing it. A
   matrix that violates its own contract at construction time is also a
   typed integrity failure.

The query is deterministic, read-only, all-or-nothing, and tenant-scoped:
it never extracts observations, writes or repairs any artifact, records no
operational activity, changes no lifecycle state, and never returns a
partial matrix. Nothing here evaluates or re-executes transitions, runs
replay, calls LEGION or NEXUS, loads or executes domain packs, or uses
wall-clock time, randomness, filesystem, database, provider, or network
access.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    RunInputIntegrityError,
    RunNotCompleteError,
    RunNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_runtime import (
    build_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_trajectory_query_service import (
    get_verified_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_errors import (
    RealizationCampaignMetricObservationMatrixIntegrityError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_run_metric_observation_service import (
    get_verified_realization_run_metric_observation_set,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)


def get_verified_realization_campaign_metric_observation_matrix(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> RealizationCampaignMetricObservationMatrix:
    """Load and fully verify a completed campaign's metric-observation matrix.

    Assembles the complete strategy x shared-seed metric-observation
    matrix of one COMPLETE runtime-3.0.0 campaign from its verified stored
    records: the campaign, status, the verified trajectory matrix (through
    the existing verified query service), and the verified observation set
    of every run (through the existing verified query path). Every set
    must already exist; the complete collection is verified before
    anything is returned, and the matrix is built in memory through the
    pure builder and returned without being stored. Unknown or foreign
    campaigns raise the typed not-found error; non-COMPLETE campaigns
    raise :class:`CampaignNotCompleteError`; legacy or unsupported
    runtime raises :class:`UnsupportedRuntimeVersionError`; and missing,
    inconsistent, or corrupted observation sets - or an internally built
    matrix violating its contract - raise the typed matrix integrity
    error. A partial matrix is never returned.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    # The completely verified trajectory matrix is the authoritative
    # strategy x shared-seed layout and cell order. Its typed error
    # mappings (404, 409 conflict for legacy/unsupported runtime, 409
    # integrity error for missing or corrupted matrix inputs) pass
    # through unchanged.
    trajectory_matrix = get_verified_realization_campaign_trajectory_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )

    observation_sets: list[RealizationRunMetricObservationSet] = []
    for cell in trajectory_matrix.cells:
        try:
            observation_sets.append(
                get_verified_realization_run_metric_observation_set(
                    store=store, tenant_id=tenant_id, run_id=cell.run_id
                )
            )
        except (
            RealizationRunMetricObservationNotFoundError,
            RealizationRunMetricObservationIntegrityError,
            RealizationRunTrajectoryExecutionIntegrityError,
            RunInputIntegrityError,
            RunNotFoundError,
            RunNotCompleteError,
        ) as exc:
            raise RealizationCampaignMetricObservationMatrixIntegrityError(
                campaign_id, reason="run metric observation set missing or corrupted"
            ) from exc

    try:
        return build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=tuple(observation_sets),
        )
    except ValidationError:
        raise RealizationCampaignMetricObservationMatrixIntegrityError(
            campaign_id, reason="internally built matrix violates its contract"
        ) from None
