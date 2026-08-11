"""Verified read-only campaign objective-evaluation query (Phase 23).

Phase 23 exposes the deterministic objective-evaluation matrix of one
completed runtime-2.0.0 campaign - derived exclusively from its
completely verified Phase 21 ``CampaignMetricObservationMatrix`` and
the exact ``ScenarioEvaluationProfile`` embedded in the campaign's
compiled world - through a strictly read-only, tenant-scoped
application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped campaign and its campaign status; unknown or
   foreign campaigns fail with the store's typed not-found error (404).
2. Require the campaign to be exactly COMPLETE - anything else raises
   :class:`CampaignNotCompleteError` (409 invalid_state).
3. Obtain the completely verified Phase 21 ``CampaignMetricObservationMatrix``
   through the existing verified query service - Phase 18/20/21
   verification is never reimplemented or weakened, and its typed
   error mappings pass through unchanged.
4. Load and fully verify the exact compiled world and manifest
   (``verify_world_snapshot`` - which now also verifies the embedded
   evaluation profile's identity, hashes, scenario references,
   coverage, ordering, and copied authoritative values).
5. Extract the world-embedded evaluation profile.
6. A world without an embedded profile returns the typed 404 - the
   honest answer for a campaign whose world predates (or never had) a
   profile; nothing is ever invented.
7. Load the stored profile and strictly verify it (serializer-based
   strict revalidation, independent identifier and content-hash
   re-derivation, ownership).
8. A world-embedded profile with a missing, malformed, or mismatched
   stored record returns the typed 409 integrity_error.
9. Require exact canonical equality between the stored and the
   embedded profile.
10. Build the complete matrix in memory through the pure builder from
    the embedded authoritative snapshot and return it directly
    without storing it. A matrix that violates its own contract at
    construction time is also a typed integrity failure.

The query is deterministic, read-only, all-or-nothing, and tenant-
scoped: it never extracts, executes, replays, evaluates, regenerates,
repairs, writes, or stores anything, records no operational activity,
and changes no lifecycle state. Repeated GET requests return
byte-identical artifacts.

The service is pure application logic: no FastAPI, no LEGION/NEXUS calls
or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access. Public
messages never expose raw observed values, targets, weights,
tolerances, normalization scales, hashes, scenario contents, metadata,
internal reasons, validator diagnostics, or foreign tenant records.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.campaign_metric_observation_query_service import (
    get_verified_campaign_metric_observation_matrix,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_evaluation_profile,
)
from kalhas.application.objective_evaluation_errors import (
    CampaignObjectiveEvaluationMatrixIntegrityError,
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_identity import (
    verify_evaluation_profile_identity,
)
from kalhas.application.objective_evaluation_runtime import (
    build_campaign_objective_evaluation_matrix,
)
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.objective_evaluation import CampaignObjectiveEvaluationMatrix


def get_verified_campaign_objective_evaluations(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignObjectiveEvaluationMatrix:
    """Load and fully verify a completed campaign's objective evaluations.

    Derives the complete strategy x seed x objective evaluation matrix
    of one COMPLETE runtime-2.0.0 campaign from its completely verified
    Phase 21 ``CampaignMetricObservationMatrix`` (obtained through the
    existing verified query service), the fully verified compiled world
    and manifest, and the exact world-embedded evaluation profile -
    strictly verified against the stored profile record - using the
    pure Phase 23 builder, and returns the matrix directly without
    storing it. Unknown or foreign campaigns raise the typed not-found
    error (404); non-COMPLETE campaigns raise
    :class:`CampaignNotCompleteError` (409 invalid_state); a world
    without an embedded profile raises :class:`EvaluationProfileNotFoundError`
    (404); legacy or unsupported runtime raises
    :class:`UnsupportedRuntimeVersionError` (409 conflict); missing,
    inconsistent, or corrupted upstream artifacts - or an internally
    built matrix violating its contract - raise the typed integrity
    error (409 integrity_error). A partial or unverifiable evaluation
    matrix is never returned.
    """
    # The tenant-scoped campaign lookup raises the typed not-found error
    # (404) for unknown or foreign campaigns before the status gate.
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    # The completely verified Phase 21 matrix is the sole authoritative
    # observation source. Its typed error mappings (404, 409 conflict
    # for legacy/unsupported runtime, 409 integrity_error for missing or
    # corrupted earlier-phase artifacts) pass through unchanged.
    observation_matrix = get_verified_campaign_metric_observation_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )

    world = store.get_world(tenant_id, campaign.world_version_id)
    manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    verify_world_snapshot(world, manifest)

    catalog = extract_world_catalog(world)
    embedded_profile = catalog.evaluation_profile
    if embedded_profile is None:
        raise EvaluationProfileNotFoundError(tenant_id, world.source_scenario_id)

    try:
        stored_profile = store.get_evaluation_profile(tenant_id, world.source_scenario_id)
    except EvaluationProfileNotFoundError as exc:
        raise CampaignObjectiveEvaluationMatrixIntegrityError(
            campaign_id, reason="stored evaluation profile missing"
        ) from exc
    revalidate_stored_evaluation_profile(stored_profile, tenant_id, world.source_scenario_id)
    verify_evaluation_profile_identity(
        stored_profile, tenant_id=tenant_id, scenario_id=world.source_scenario_id
    )
    if stored_profile.model_dump(mode="json") != embedded_profile.model_dump(mode="json"):
        raise CampaignObjectiveEvaluationMatrixIntegrityError(
            campaign_id, reason="stored and embedded evaluation profile mismatch"
        )
    if (
        observation_matrix.world_version_id != world.identifier
        or observation_matrix.world_content_hash != world.content_hash
    ):
        raise CampaignObjectiveEvaluationMatrixIntegrityError(
            campaign_id, reason="observation matrix world identity mismatch"
        )

    try:
        return build_campaign_objective_evaluation_matrix(
            profile=embedded_profile,
            observation_matrix=observation_matrix,
        )
    except ValidationError:
        raise CampaignObjectiveEvaluationMatrixIntegrityError(
            campaign_id, reason="internally built evaluation matrix violates its contract"
        ) from None
