"""Focused Phase 23 objective-evaluation routes.

Declares and fetches the immutable per-scenario evaluation profile and
derives the read-only campaign objective-evaluation matrix. The router
is intentionally separate from the large general router module: Phase
23 adds exactly three endpoints, all tenant-scoped through the required
``X-Tenant-ID`` header, returning the public contracts directly through
the single typed error boundary.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from kalhas.api.requests_objective_evaluation import (
    ObjectiveEvaluationProfileDeclarationRequest,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.objective_evaluation_query_service import (
    get_verified_campaign_objective_evaluations,
)
from kalhas.application.objective_evaluation_service import (
    ObjectiveMetricBindingDraft,
    declare_scenario_evaluation_profile,
    get_scenario_evaluation_profile,
)
from kalhas.contracts.v1.objective_evaluation import (
    CampaignObjectiveEvaluationMatrix,
    ScenarioEvaluationProfile,
)

router = APIRouter(tags=["objective-evaluation"])


def _store(request: Request) -> InMemoryScenarioStore:
    store = getattr(request.app.state, "store", None)
    if not isinstance(store, InMemoryScenarioStore):
        raise HTTPException(status_code=500, detail="Application store unavailable")
    return store


@router.post(
    "/v1/scenarios/{scenario_id}/evaluation-profile",
    response_model=ScenarioEvaluationProfile,
    status_code=201,
    summary="Declare a scenario's immutable objective-to-metric evaluation profile",
)
def declare_evaluation_profile_route(
    scenario_id: str,
    request_body: ObjectiveEvaluationProfileDeclarationRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> ScenarioEvaluationProfile:
    """Declare the immutable evaluation profile of one scenario.

    Accepts only caller-owned binding values (``objective_id``,
    ``metric_id``, ``reach_tolerance``, ``normalization_scale``) plus
    ``declared_at`` and optional ``metadata``; every authoritative
    field - direction, target, weight, metric unit, identifiers, and
    hashes - is copied or computed from stored immutable records, so
    forged authoritative values are structurally impossible. The
    profile covers every scenario objective exactly once, is
    canonicalized into the exact ``ScenarioSpec`` objective order, and
    must be declared before any world has been compiled for the
    scenario. Unknown or foreign scenarios return the typed 404;
    invalid references, coverage, tolerance, or scale rules the typed
    422; a duplicate declaration or a declaration after world
    compilation the typed 409 conflict; stored-record inconsistencies
    the typed 409 integrity_error - without leaking targets, weights,
    tolerances, scales, hashes, scenario contents, metadata, internal
    reasons, or validation details. No operational-activity event is
    recorded.
    """
    bindings = tuple(
        ObjectiveMetricBindingDraft(
            objective_id=binding.objective_id,
            metric_id=binding.metric_id,
            reach_tolerance=binding.reach_tolerance,
            normalization_scale=binding.normalization_scale,
        )
        for binding in request_body.bindings
    )
    return declare_scenario_evaluation_profile(
        store=_store(request),
        tenant_id=x_tenant_id,
        scenario_id=scenario_id,
        bindings=bindings,
        declared_at=request_body.declared_at,
        metadata=request_body.metadata,
    )


@router.get(
    "/v1/scenarios/{scenario_id}/evaluation-profile",
    response_model=ScenarioEvaluationProfile,
    summary="Fetch a scenario's immutable evaluation profile",
)
def get_evaluation_profile_route(
    scenario_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> ScenarioEvaluationProfile:
    """Fetch the stored evaluation profile of one scenario (tenant-scoped).

    Strictly read-only: unknown and foreign profiles are
    indistinguishable and both return the typed 404; the profile is
    returned through the store's deep-copy boundary and is never
    repaired, replaced, or re-derived.
    """
    return get_scenario_evaluation_profile(
        store=_store(request), tenant_id=x_tenant_id, scenario_id=scenario_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/objective-evaluations",
    response_model=CampaignObjectiveEvaluationMatrix,
    tags=["objective-evaluation"],
    summary="Fetch a completed campaign's deterministic objective evaluations",
)
def get_campaign_objective_evaluations_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignObjectiveEvaluationMatrix:
    """Fetch the deterministic objective-evaluation matrix of a COMPLETE 2.0.0 campaign.

    The exact strategy x seed x objective evaluation of one completed
    trajectory-runtime campaign, derived exclusively from its
    completely verified Phase 21 metric-observation matrix and the
    exact evaluation profile embedded in the campaign's compiled world:
    exact raw values and direction-aware value-level statements
    (target achievement, signed target delta, normalized target
    violation) only - never probability, confidence, distributions,
    risk, ranking, dominance, regret, preference, winners, evidence,
    recommendations, or decision briefs. Read-only retrieval: the
    campaign must be COMPLETE, the Phase 21 matrix is obtained through
    the existing verified query service, the compiled world is fully
    verified, the world-embedded profile must exist and match the
    stored profile record exactly, and the matrix is built in memory
    and returned directly - it is never stored, executed, replayed,
    evaluated, repaired, or partially returned. Unknown or foreign
    campaigns return the typed 404; a world without an embedded
    profile the typed 404; non-COMPLETE campaigns the typed 409
    invalid_state; legacy or unsupported runtime the typed 409
    conflict; and missing, inconsistent, or corrupted artifacts (or an
    internally malformed matrix) the typed 409 integrity_error -
    without leaking raw observation values, targets, weights,
    tolerances, scales, hashes, scenario contents, metadata, internal
    reasons, or validation details. The GET performs no write and
    creates no operational-activity event.
    """
    return get_verified_campaign_objective_evaluations(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
