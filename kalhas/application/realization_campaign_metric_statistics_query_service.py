"""Verified read-only runtime-3 realization-aware campaign metric-statistics query.

Phase 25.

``get_verified_realization_campaign_metric_statistics`` exposes the
deterministic descriptive-statistics matrix of one COMPLETE runtime-3.0.0
campaign - derived exclusively from its completely verified Phase 25
``RealizationCampaignMetricObservationMatrix`` - through a strictly
read-only, tenant-scoped application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped ``CampaignSpec`` and ``CampaignStatus``; unknown
   or foreign campaigns fail with the store's typed not-found error (404).
2. Require the campaign to be exactly COMPLETE - anything else raises
   :class:`CampaignNotCompleteError` (409 invalid_state).
3. Obtain the completely verified Phase 25
   ``RealizationCampaignMetricObservationMatrix`` through the existing
   verified observation-matrix query service **exactly once** - its typed
   error mappings (404; 409 conflict for legacy or unsupported runtime;
   409 integrity_error for missing or corrupted observation sets) pass
   through unchanged, and its verification is never reimplemented or
   weakened.
4. Build the descriptive-statistics matrix in memory through the pure
   Phase 25 statistics builder **exactly once** and return it directly
   without storing it. A matrix that violates its own contract at
   construction time is a typed integrity failure, as is any statistics
   calculation, consistency, overflow, or non-finite failure inside the
   builder (:class:`RealizationCampaignMetricStatisticsIntegrityError`,
   409 integrity_error).

The query is deterministic, read-only, all-or-nothing, and tenant-scoped:
it never extracts observations automatically, executes, replays,
evaluates, regenerates, repairs, writes, or stores anything, creates no
missing observation sets, records no operational activity, and changes no
lifecycle state, and it never returns a partial statistics matrix.

The service is pure application logic: no web framework, no LEGION/NEXUS
calls or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access. Public
messages never expose raw observed values, calculated statistics,
hashes, state values, field names, strategy policy, internal reasons,
validator diagnostics, or foreign tenant records.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.domain_errors import CampaignNotCompleteError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_metric_statistics_runtime import (
    build_realization_campaign_metric_statistics_matrix,
)
from kalhas.application.realization_errors import (
    RealizationCampaignMetricStatisticsIntegrityError,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)


def get_verified_realization_campaign_metric_statistics(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> RealizationCampaignMetricStatisticsMatrix:
    """Load, verify, and summarize a completed campaign's metric observations.

    Derives the complete descriptive-statistics matrix of one COMPLETE
    runtime-3.0.0 campaign from its completely verified Phase 25
    ``RealizationCampaignMetricObservationMatrix`` (obtained through the
    existing verified observation-matrix query service) using the pure
    Phase 25 statistics builder, and returns the matrix directly without
    storing it. Unknown or foreign campaigns raise the typed not-found
    error (404); non-COMPLETE campaigns raise
    :class:`CampaignNotCompleteError` (409 invalid_state); legacy or
    unsupported runtime raises :class:`UnsupportedRuntimeVersionError`
    (409 conflict); missing or corrupted observation sets preserve the
    existing safe typed 409 behavior of the observation-matrix query; and
    statistics calculation, consistency, overflow, non-finite, or
    internally built contract failures raise
    :class:`RealizationCampaignMetricStatisticsIntegrityError` (409
    integrity_error). A partial or unverifiable statistics matrix is
    never returned.
    """
    # The tenant-scoped campaign lookup raises the typed not-found error
    # (404) for unknown or foreign campaigns before the status gate.
    store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    # The completely verified Phase 25 observation matrix is the sole
    # authoritative source. Its typed error mappings (404, 409 conflict
    # for legacy/unsupported runtime, 409 integrity_error for missing or
    # corrupted observation sets) pass through unchanged.
    observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )

    try:
        return build_realization_campaign_metric_statistics_matrix(
            observation_matrix=observation_matrix
        )
    except ValidationError:
        raise RealizationCampaignMetricStatisticsIntegrityError(
            campaign_id, reason="internally built statistics matrix violates its contract"
        ) from None
