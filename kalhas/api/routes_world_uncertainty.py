"""Focused Phase 24 world-uncertainty routes.

Declares and fetches the immutable per-scenario uncertainty model and
derives the read-only campaign world-realization matrix. The router is
intentionally separate from the large general router module: Phase 24
adds exactly three endpoints, all tenant-scoped through the required
``X-Tenant-ID`` header, returning the public contracts directly through
the single typed error boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from kalhas.api.requests_world_uncertainty import (
    WorldUncertaintyModelDeclarationRequest,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.world_realization_query_service import (
    get_verified_campaign_world_realizations,
)
from kalhas.application.world_uncertainty_service import (
    UncertaintyBindingDraft,
    declare_world_uncertainty_model,
    get_world_uncertainty_model,
)
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix,
    WorldUncertaintyModel,
)

router = APIRouter(tags=["world-uncertainty"])


def _store(request: Request) -> InMemoryScenarioStore:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, InMemoryScenarioStore):
        raise HTTPException(status_code=500, detail="Application store unavailable")
    return store


@router.post(
    "/v1/scenarios/{scenario_id}/uncertainty-model",
    response_model=WorldUncertaintyModel,
    status_code=201,
    summary="Declare a scenario's immutable world uncertainty model",
)
def declare_uncertainty_model_route(
    scenario_id: str,
    request_body: WorldUncertaintyModelDeclarationRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> WorldUncertaintyModel:
    """Declare the immutable uncertainty model of one scenario.

    Accepts only caller-owned binding values (``manifest_id``,
    ``state_model_id``, ``state_field_id``, the closed distribution
    specification, ``rounding_policy``, and the independently optional
    clipping bounds) plus ``declared_at`` and optional ``metadata``;
    every authoritative field - scenario, source pack binding,
    manifest, pack identity, manifest content hash, deterministic
    state-model identity, state-model content hash, field kind,
    identifiers, sampler/quantization provenance, and hashes - is
    copied or computed from stored immutable records, so forged
    authoritative values are structurally impossible. Bindings are
    canonicalized into the exact ``(manifest_id, state_model_id,
    state_field_id)`` target-tuple order and must be declared before
    any world has been compiled for the scenario. Unknown or foreign
    scenarios return the typed 404; invalid references, field kinds,
    rounding, bound, distribution-parameter, or allowed-values rules
    the typed 422; a duplicate declaration or a declaration after world
    compilation the typed 409 conflict; stored-record inconsistencies
    the typed 409 integrity_error - without leaking parameters, bounds,
    hashes, scenario contents, metadata, internal reasons, or
    validation details. No operational-activity event is recorded.
    """
    bindings = tuple(
        UncertaintyBindingDraft(
            manifest_id=binding.manifest_id,
            state_model_id=binding.state_model_id,
            state_field_id=binding.state_field_id,
            distribution=binding.distribution,
            rounding_policy=binding.rounding_policy,
            lower_bound=binding.lower_bound,
            upper_bound=binding.upper_bound,
        )
        for binding in request_body.bindings
    )
    return declare_world_uncertainty_model(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        bindings=bindings,
        declared_at=request_body.declared_at,
        metadata=request_body.metadata,
    )


@router.get(
    "/v1/scenarios/{scenario_id}/uncertainty-model",
    response_model=WorldUncertaintyModel,
    summary="Fetch a scenario's immutable uncertainty model",
)
def get_uncertainty_model_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> WorldUncertaintyModel:
    """Fetch the stored uncertainty model of one scenario (tenant-scoped).

    Strictly read-only: unknown and foreign models are indistinguishable
    and both return the typed 404; the model is returned through the
    store's deep-copy boundary with strict revalidation and independent
    identity/hash verification, and is never repaired, replaced, or
    re-derived.
    """
    return get_world_uncertainty_model(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/world-realizations",
    response_model=CampaignWorldRealizationMatrix,
    summary="Fetch a campaign's deterministic world realizations",
)
def get_campaign_world_realizations_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignWorldRealizationMatrix:
    """Fetch the deterministic world-realization matrix of one campaign.

    Exactly one strategy-independent ``WorldRealization`` per campaign
    seed, derived exclusively from the fully verified compiled world,
    the exact embedded uncertainty model (strictly verified against the
    stored record), and the campaign's seed ensemble: sampled values,
    complete realized initial-state overrides, deterministic
    identifiers and content hashes - and **no strategy identifiers
    anywhere**. Sampling and provenance only: nothing is executed,
    replayed, transitioned, measured, evaluated, ranked, or
    recommended. **No lifecycle-state gate applies** - the derivation
    depends on immutable campaign and world inputs, never on execution
    status, and failed/cancelled campaigns retain full realization
    provenance for audit and replay. Read-only retrieval: the matrix is
    built in memory and returned directly - it is never stored,
    repaired, or partially returned. Unknown or foreign campaigns
    return the typed 404; missing, inconsistent, or corrupted artifacts
    (or an internally malformed matrix) the typed 409 integrity_error;
    deterministic per-seed sampling or state-validation failures the
    typed 409 conflict - without leaking sampled values, parameters,
    bounds, hashes, scenario contents, metadata, internal reasons, or
    validation details. The GET performs no write and creates no
    operational-activity event.
    """
    return get_verified_campaign_world_realizations(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
