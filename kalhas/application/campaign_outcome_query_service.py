"""Verified read-only campaign outcome-distribution query (KALHAS).

``get_verified_campaign_outcome_distributions`` derives the deterministic
``CampaignOutcomeDistributionMatrix`` of one COMPLETE runtime-3.0.0
campaign strictly from verified stored records, never storing the
derived matrix:

1. Load the tenant-scoped ``CampaignSpec`` and ``CampaignStatus``;
   unknown or foreign campaigns fail with the store's typed not-found
   error, and the campaign must be exactly COMPLETE - any other state
   raises :class:`CampaignNotCompleteError` before any downstream
   derivation begins.
2. Load the campaign's exact compiled world and manifest and fully
   verify them through ``verify_world_snapshot``; extract the
   authoritative world catalog. A missing world or manifest inside an
   existing campaign is corruption of the campaign's inputs, never an
   unrelated public 404 - it raises the safe typed
   :class:`CampaignOutcomeDistributionMatrixIntegrityError`.
3. Obtain the exact evaluation-profile snapshot: the immutable profile
   embedded in the verified compiled world is the single authoritative
   builder input. A verified world with no embedded profile raises the
   established :class:`EvaluationProfileNotFoundError` - nothing is
   ever invented. The stored profile for the same tenant/scenario is
   then loaded, strictly revalidated through the established
   serializer-based store helper, independently identity/hash/ownership
   verified through the established identity path, and required to be
   canonically identical to the embedded snapshot. A profile expected
   by the world but missing, malformed, corrupted, foreign, stale, or
   canonically different is a safe typed
   :class:`CampaignOutcomeDistributionMatrixIntegrityError` - the
   stored copy is never repaired, replaced, normalized, or preferred
   over the embedded snapshot.
4. Obtain the authoritative ``CampaignWorldRealizationMatrix`` by
   calling the existing verified world-realization query exactly once.
5. Obtain the authoritative ``RealizationCampaignMetricObservationMatrix``
   by calling the existing verified observation-matrix query exactly
   once.
6. Derive the result by calling the accepted pure
   ``build_campaign_outcome_distribution_matrix`` exactly once with the
   embedded profile and the two verified source matrices, and return it
   directly without storing it.

The pure builder remains the final independent cross-source verifier
(runtime exactly 3.0.0, tenant/scenario/campaign/world identity, world
and source content hashes, evaluation-profile identity/hash,
uncertainty-model identity/hash or exact absence, realization and
observation matrix identity/hash, exact strategy/seed/objective/metric
ordering, binding provenance and metric units, and every numeric and
statistical invariant); no statistical, identity, or matrix algorithm
is duplicated or weakened here.

The query is deterministic, read-only, all-or-nothing, and
tenant-scoped: it never executes, replays, extracts, evaluates,
regenerates, repairs, writes, or stores anything, records no
operational activity, and changes no lifecycle state. Repeated
successful queries over unchanged storage return byte-identical
matrices and leave the complete store state unchanged. The service is
pure application logic: no FastAPI, no LEGION/NEXUS calls or imports,
no domain-pack loading or execution, and no wall clock, randomness,
filesystem, database, provider, or network access. Public messages
never expose internal reasons, hashes, values, targets, fields, tenant
data, or validator diagnostics.
"""

from __future__ import annotations

from kalhas.application.campaign_outcome_errors import (
    CampaignOutcomeDistributionMatrixIntegrityError,
)
from kalhas.application.campaign_outcome_matrix_runtime import (
    build_campaign_outcome_distribution_matrix,
)
from kalhas.application.domain_errors import CampaignNotCompleteError, WorldNotFoundError
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_evaluation_profile,
)
from kalhas.application.objective_evaluation_errors import (
    EvaluationProfileIntegrityError,
    EvaluationProfileNotFoundError,
)
from kalhas.application.objective_evaluation_identity import (
    verify_evaluation_profile_identity,
)
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix


def _reject(campaign_id: str, reason: str) -> CampaignOutcomeDistributionMatrixIntegrityError:
    """A generic, safe outcome-matrix integrity error with an internal diagnostic reason."""
    return CampaignOutcomeDistributionMatrixIntegrityError(campaign_id, reason)


def get_verified_campaign_outcome_distributions(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignOutcomeDistributionMatrix:
    """Load and fully verify a completed campaign's outcome-distribution matrix.

    Derives the complete strategy-major/objective-minor empirical
    outcome matrix of one COMPLETE runtime-3.0.0 campaign from its
    verified stored records: the campaign and status (exactly COMPLETE),
    the fully verified compiled world and manifest, the exact
    world-embedded evaluation profile (strictly verified against the
    stored profile record), the verified world-realization matrix
    (through the existing verified query service), and the verified
    runtime-3 metric-observation matrix (through the existing verified
    query service), using the accepted pure matrix builder - and
    returns the matrix directly without storing it. Unknown or foreign
    campaigns raise the typed not-found error; non-COMPLETE campaigns
    raise :class:`CampaignNotCompleteError`; a verified world without
    an embedded profile raises :class:`EvaluationProfileNotFoundError`;
    legacy or unsupported recorded runtime raises
    :class:`UnsupportedRuntimeVersionError`; missing, inconsistent, or
    corrupted upstream artifacts - or corruption discovered by this
    query's own world/profile assembly or canonical comparison - raise
    the typed matrix integrity error (or the established upstream
    integrity error unchanged). A partial or unverifiable matrix is
    never returned, and nothing is ever written or repaired.
    """
    # The tenant-scoped campaign lookup raises the typed not-found error
    # (404) for unknown or foreign campaigns before the status gate.
    campaign = store.get_campaign(tenant_id, campaign_id)
    status = store.get_campaign_status(tenant_id, campaign_id)
    if status.state is not CampaignState.COMPLETE:
        raise CampaignNotCompleteError(campaign_id, status.state.value)

    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        # A campaign always references an existing compiled world; a
        # missing world/manifest inside an existing campaign is an
        # inconsistency of the campaign's inputs - never an unrelated
        # tenant-scoped 404.
        raise _reject(campaign_id, "campaign world record missing") from exc
    verify_world_snapshot(world, manifest)

    catalog = extract_world_catalog(world)
    embedded_profile = catalog.evaluation_profile
    if embedded_profile is None:
        raise EvaluationProfileNotFoundError(tenant_id, world.source_scenario_id)

    # The stored record is strictly revalidated and independently
    # identity/hash/ownership verified; only the embedded snapshot is
    # ever used as builder input, and only after exact canonical
    # equality between the stored and embedded profiles.
    try:
        stored_profile = store.get_evaluation_profile(tenant_id, world.source_scenario_id)
        revalidate_stored_evaluation_profile(stored_profile, tenant_id, world.source_scenario_id)
        verify_evaluation_profile_identity(
            stored_profile, tenant_id=tenant_id, scenario_id=world.source_scenario_id
        )
    except EvaluationProfileNotFoundError as exc:
        raise _reject(campaign_id, "stored evaluation profile missing") from exc
    except EvaluationProfileIntegrityError as exc:
        raise _reject(
            campaign_id,
            getattr(exc, "reason", None) or "stored evaluation profile integrity failed",
        ) from exc
    if stored_profile.model_dump(mode="json") != embedded_profile.model_dump(mode="json"):
        raise _reject(campaign_id, "stored and embedded evaluation profile mismatch")

    world_realization_matrix = get_verified_campaign_world_realizations(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
        store=store, tenant_id=tenant_id, campaign_id=campaign_id
    )
    return build_campaign_outcome_distribution_matrix(
        profile=embedded_profile,
        world_realization_matrix=world_realization_matrix,
        observation_matrix=observation_matrix,
    )


__all__ = ["get_verified_campaign_outcome_distributions"]
