"""Verified read-only campaign metric-statistics query (Phase 22).

Phase 22 exposes the deterministic descriptive-statistics matrix of one
completed runtime-2.0.0 campaign - derived exclusively from its
completely verified Phase 21 ``CampaignMetricObservationMatrix`` -
through a strictly read-only, tenant-scoped application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped campaign and its campaign status; unknown or
   foreign campaigns fail with the store's typed not-found error (404).
2. Require the campaign to be exactly COMPLETE - anything else raises
   :class:`CampaignNotCompleteError` (409 invalid_state).
3. Obtain the completely verified Phase 21 ``CampaignMetricObservationMatrix``
   through the existing verified query service
   (``get_verified_campaign_metric_observation_matrix``) - Phase 18,
   20, and 21 verification is never reimplemented or weakened, and its
   typed error mappings (404; 409 conflict for legacy/unsupported
   runtime; 409 integrity_error for missing or corrupted earlier-phase
   artifacts) pass through unchanged.
4. Build the descriptive-statistics matrix in memory through the pure
   Phase 22 builder and return it directly without storing it. A matrix
   that violates its own contract at construction time is a typed
   integrity failure, as is any Phase 22 calculation, consistency,
   overflow, or non-finite failure inside the builder
   (:class:`CampaignMetricStatisticsIntegrityError`, 409
   integrity_error).

The query is deterministic, read-only, all-or-nothing, and tenant-
scoped: it never extracts, executes, replays, evaluates, regenerates,
repairs, writes, or stores anything, creates no missing Phase 20
artifacts, records no operational activity, and changes no lifecycle
state.

The service is pure application logic: no FastAPI, no LEGION/NEXUS calls
or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access. Public
messages never expose raw observed values, calculated statistics,
hashes, state values, field names, strategy policy, internal reasons,
validator diagnostics, or foreign tenant records.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.campaign_metric_observation_query_service import (
    get_verified_campaign_metric_observation_matrix,
)
from kalhas.application.campaign_metric_statistics_runtime import (
    build_campaign_metric_statistics_matrix,
)
from kalhas.application.domain_errors import (
    CampaignMetricStatisticsIntegrityError,
    CampaignNotCompleteError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_metric_statistics import CampaignMetricStatisticsMatrix


def get_verified_campaign_metric_statistics(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignMetricStatisticsMatrix:
    """Load, verify, and summarize a completed campaign's metric observations.

    Derives the complete descriptive-statistics matrix of one COMPLETE
    runtime-2.0.0 campaign from its completely verified Phase 21
    ``CampaignMetricObservationMatrix`` (obtained through the existing
    verified query service) using the pure Phase 22 builder, and
    returns the matrix directly without storing it. Unknown or foreign
    campaigns raise the typed not-found error (404); non-COMPLETE
    campaigns raise :class:`CampaignNotCompleteError` (409
    invalid_state); legacy or unsupported runtime raises
    :class:`UnsupportedRuntimeVersionError` (409 conflict); missing or
    corrupted earlier-phase artifacts preserve the existing safe typed
    409 behavior; and Phase 22 calculation, consistency, overflow,
    non-finite, or internally built contract failures raise
    :class:`CampaignMetricStatisticsIntegrityError` (409
    integrity_error). A partial or unverifiable statistics matrix is
    never returned.
    """
    # The tenant-scoped campaign lookup raises the typed not-found error
    # (404) for unknown or foreign campaigns before the status gate.
    store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    # The completely verified Phase 21 matrix is the sole authoritative
    # source. Its typed error mappings (404, 409 conflict for
    # legacy/unsupported runtime, 409 integrity_error for missing or
    # corrupted earlier-phase artifacts) pass through unchanged.
    observation_matrix = get_verified_campaign_metric_observation_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )

    try:
        return build_campaign_metric_statistics_matrix(observation_matrix=observation_matrix)
    except ValidationError:
        raise CampaignMetricStatisticsIntegrityError(
            campaign_id, reason="internally built statistics matrix violates its contract"
        ) from None
