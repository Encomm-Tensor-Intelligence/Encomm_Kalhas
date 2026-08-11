"""Verified read-only campaign world-realization query (Phase 24).

Exposes the deterministic world-realization matrix of one campaign -
one strategy-independent ``WorldRealization`` per campaign seed -
through a strictly read-only, tenant-scoped application query surface.

The query follows a verified, all-or-nothing pipeline:

1. Load the tenant-scoped campaign; unknown or foreign campaigns fail
   with the store's typed not-found error (404). **No lifecycle-state
   gate applies**: the matrix is a pure function of the immutable
   campaign record, the compiled world, the embedded uncertainty model
   (or its absence), and the seed ensemble - mutable campaign status
   can neither change the realization bytes nor make derivable
   provenance disappear, and failed/cancelled campaigns retain full
   realization provenance for audit and replay.
2. Load and fully verify the exact compiled world and manifest
   (``verify_world_snapshot`` - which also verifies an embedded
   uncertainty model's identity, hashes, scenario and target
   references, canonical binding order, copied authoritative values,
   sampler/quantization provenance, effective parameter rules, and
   discrete allowed-values outcomes).
3. Extract the world catalog; the embedded model may be absent.
4. When the world embeds a model: load the stored model, strictly
   revalidate it (serializer-based), independently re-verify its
   identity and hashes, and require exact canonical equality with the
   embedded snapshot; a missing, malformed, or mismatched stored record
   is a typed integrity failure. When the world embeds no model, a
   stored model is impossible (declaration after compilation is
   blocked) - its presence is treated as corruption.
5. Build the complete matrix in memory through the pure builder from
   the embedded authoritative snapshots and return it directly without
   storing it. A matrix that violates its own contract at construction
   time is also a typed integrity failure; deterministic per-seed
   sampling or state-validation failures are typed conflict errors.

The query is deterministic, read-only, all-or-nothing, and
tenant-scoped: it never executes, replays, extracts, evaluates,
regenerates, repairs, writes, or stores anything, records no
operational activity, and changes no lifecycle state. Repeated GET
requests return byte-identical artifacts.

The service is pure application logic: no FastAPI, no LEGION/NEXUS
calls or imports, no domain-pack loading or execution, and no wall
clock, randomness, filesystem, database, provider, or network access.
Public messages never expose sampled values, distribution parameters,
bounds, hashes, state values, metadata, internal reasons, validator
diagnostics, or foreign tenant records.
"""

from __future__ import annotations

from pydantic import ValidationError

from kalhas.application.domain_errors import WorldNotFoundError
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_world_uncertainty_model,
)
from kalhas.application.world_integrity import extract_world_catalog, verify_world_snapshot
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
)
from kalhas.application.world_uncertainty_errors import (
    CampaignWorldRealizationMatrixIntegrityError,
    WorldRealizationIntegrityError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_identity import (
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.world_realization import CampaignWorldRealizationMatrix


def get_verified_campaign_world_realizations(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
) -> CampaignWorldRealizationMatrix:
    """Load and fully verify one campaign's world-realization matrix.

    Derives exactly one strategy-independent ``WorldRealization`` per
    campaign seed from the fully verified compiled world, the exact
    embedded uncertainty model (strictly verified against the stored
    record), and the campaign's seed ensemble - through the pure
    Phase 24 builder - and returns the matrix directly without storing
    it. No lifecycle-state gate applies; failed/cancelled campaigns
    retain their full realization provenance. Unknown or foreign
    campaigns raise the typed not-found error (404); missing,
    inconsistent, or corrupted upstream artifacts - or an internally
    built matrix violating its contract - raise the typed integrity
    error (409 integrity_error); deterministic per-seed sampling or
    state-validation failures raise the typed sampling error (409
    conflict). A partial or unverifiable matrix is never returned.
    """
    campaign = store.get_campaign(tenant_id, campaign_id)

    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        # A campaign always references an existing compiled world; a
        # missing world/manifest inside an existing campaign is an
        # inconsistency of the campaign's inputs - never an unrelated
        # tenant-scoped 404.
        raise CampaignWorldRealizationMatrixIntegrityError(
            campaign_id, reason="campaign world record missing"
        ) from exc
    verify_world_snapshot(world, manifest)

    catalog = extract_world_catalog(world)
    embedded_model = catalog.uncertainty_model
    scenario_id = world.source_scenario_id

    if embedded_model is not None:
        try:
            stored_model = store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError as exc:
            raise CampaignWorldRealizationMatrixIntegrityError(
                campaign_id, reason="stored uncertainty model missing"
            ) from exc
        revalidate_stored_world_uncertainty_model(stored_model, tenant_id, scenario_id)
        verify_world_uncertainty_model_identity(
            stored_model, tenant_id=tenant_id, scenario_id=scenario_id
        )
        if stored_model.model_dump(mode="json") != embedded_model.model_dump(mode="json"):
            raise CampaignWorldRealizationMatrixIntegrityError(
                campaign_id, reason="stored and embedded uncertainty model mismatch"
            )
    else:
        # Declaration after the first world compilation is blocked, so a
        # stored model alongside a model-free world is corruption.
        try:
            store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError:
            pass
        else:
            raise CampaignWorldRealizationMatrixIntegrityError(
                campaign_id, reason="stored uncertainty model exists without an embedded model"
            )

    try:
        return build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=embedded_model,
        )
    except ValidationError:
        raise CampaignWorldRealizationMatrixIntegrityError(
            campaign_id, reason="internally built realization matrix violates its contract"
        ) from None
    except WorldRealizationIntegrityError as exc:
        # A builder-level integrity failure (campaign/world provenance
        # mismatch, missing or mismatched target state model or field)
        # is a campaign-scoped matrix integrity failure.
        raise CampaignWorldRealizationMatrixIntegrityError(
            campaign_id,
            reason=getattr(exc, "reason", None) or "realization integrity failed",
        ) from exc
    # WorldRealizationSamplingError (typed 409 CONFLICT sampling
    # failure) from the pure builder propagates unchanged: deterministic
    # per-seed sampling failure must never be converted into an
    # integrity error, and a partially built matrix is never returned.
