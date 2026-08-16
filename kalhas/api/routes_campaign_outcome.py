"""HTTP route for the campaign outcome-distribution surface (KALHAS).

Exactly one unique path and one OpenAPI operation:

- ``GET /v1/campaigns/{campaign_id}/outcome-distributions``

The operation is ``X-Tenant-ID`` scoped and reads the tenant-scoped
recorded ``RunPlan`` tuple **before** invoking any outcome query:
exactly ``3.0.0`` on every recorded plan is accepted, and an empty
plan tuple - which has no recorded runtime to dispatch on - or any
recorded plan runtime other than ``3.0.0`` raises the typed
:class:`UnsupportedRuntimeVersionError` (409 conflict) before the
outcome query service is invoked. The complete recorded tuple is
inspected, never only the first plan. The runtime switch derives only
from stored records: no query parameter, request body, caller-provided
selector, or header other than tenant ownership is ever read.

The GET is strictly read-only: no execution, replay, extraction,
evaluation, repair, regeneration, backfill, storage, activity event,
or lifecycle mutation; no NEXUS/LEGION/domain-pack invocation; no wall
clock, randomness, provider, network, filesystem, or database access;
and no ranking, winner, preferred-strategy, recommendation,
confidence-interval, forecast-certainty, or narrative surface. The
established safe typed 404, 409 invalid_state, 409 conflict, and 409
integrity_error mappings and the generic no-leak error bodies are
preserved unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from kalhas.application.campaign_outcome_query_service import (
    get_verified_campaign_outcome_distributions,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign_outcome import CampaignOutcomeDistributionMatrix

router = APIRouter()


def _store(request: Request) -> InMemoryScenarioStore:
    """Resolve the process-local in-memory store from app state."""
    store: InMemoryScenarioStore = request.app.state.store
    return store


def _require_runtime_three_campaign(
    store: InMemoryScenarioStore, tenant_id: str, campaign_id: str
) -> None:
    """Read the tenant-scoped recorded run plans and require every runtime 3.0.0.

    Unknown or foreign campaigns raise the store's typed not-found error
    (404); an empty recorded plan tuple - which has no recorded runtime
    to dispatch on - and any recorded plan runtime other than ``3.0.0``
    raise the typed unsupported-runtime error (409 conflict) before the
    outcome query service is invoked. The complete recorded ``RunPlan``
    tuple is inspected; no query parameter or caller-provided switch is
    ever read.
    """
    plans = store.get_run_plans(tenant_id, campaign_id)
    if not plans:
        # Fail closed: no recorded runtime exists, so no outcome query
        # or artifact access may run.
        raise UnsupportedRuntimeVersionError("", operation="campaign outcome distribution artifact")
    for plan in plans:
        if plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="campaign outcome distribution artifact"
            )


@router.get(
    "/v1/campaigns/{campaign_id}/outcome-distributions",
    response_model=CampaignOutcomeDistributionMatrix,
    tags=["campaign-outcome"],
    summary="Fetch a completed campaign's verified empirical outcome distributions",
)
def get_campaign_outcome_distributions_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignOutcomeDistributionMatrix:
    """Fetch the deterministic outcome-distribution matrix of a COMPLETE 3.0.0 campaign.

    Read-only retrieval: the tenant-scoped recorded run plans are read
    first (every recorded runtime must be exactly 3.0.0; an empty plan
    tuple or any other value returns the typed 409 conflict before the
    outcome query is invoked), then the complete strategy-major/
    objective-minor empirical outcome matrix is derived through the
    existing verified query service - the campaign must be COMPLETE, the
    compiled world and the world-embedded evaluation profile are fully
    verified, and the pure outcome matrix builder aggregates the
    verified realization and observation sources - and returned without
    being stored. Unknown or foreign campaigns return the typed 404; a
    world without an embedded evaluation profile the typed 404;
    non-COMPLETE campaigns the typed 409 invalid_state; missing,
    inconsistent, or corrupted world/profile/realization/observation/
    outcome sources the typed 409 integrity_error - without leaking raw
    observed values, samples, targets, hashes, state values, field
    names, internal reasons, validator diagnostics, or another tenant's
    existence. The GET performs no write and creates no
    operational-activity event.
    """
    _require_runtime_three_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_campaign_outcome_distributions(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
