"""HTTP routes for the campaign decision surface (KALHAS).

Exactly four operations on three unique paths:

- ``POST /v1/campaigns/{campaign_id}/decision-policy`` -> 201
- ``GET /v1/campaigns/{campaign_id}/decision-policy`` -> 200
- ``GET /v1/campaigns/{campaign_id}/strategy-comparison`` -> 200
- ``GET /v1/campaigns/{campaign_id}/decision-brief`` -> 200

All four operations are ``X-Tenant-ID`` scoped and read the
tenant-scoped recorded ``RunPlan`` tuple **before** invoking any
policy or query service: exactly ``3.0.0`` on every recorded plan is
accepted, and an empty plan tuple - which has no recorded runtime to
dispatch on - or any recorded plan runtime other than ``3.0.0`` raises
the typed :class:`UnsupportedRuntimeVersionError` (409 conflict)
before any downstream service call. The complete recorded tuple is
inspected, never only the first plan: a legacy, unsupported, or mixed
runtime at the first, middle, or last position fails closed. The
runtime switch derives only from stored records: no query parameter,
request body, caller-provided selector, or header other than tenant
ownership is ever read, and recorded run plans are never mutated or
repaired. Unknown or foreign campaigns raise the store's typed
not-found error (404) unchanged.

The declaration operation converts the validated caller-owned request
into the exact service-owned immutable draft (one
``ObjectiveTargetRequirement`` per per-objective request record in
exact request order, copying only caller-owned fields - no caller
identifier, hash, tenant, campaign, scenario, world, profile, weight,
tail, runtime, or algorithm data) and calls
``declare_campaign_decision_policy`` exactly once. The three GET
operations each call their accepted verified query exactly once and
return the artifact directly; the comparison and the brief are pure
derived artifacts that are never stored, and repeated GETs are
byte-identical and store-neutral. The stored policy remains
retrievable even when the campaign state is later non-COMPLETE, and
the query service owns every COMPLETE/policy-first/outcome/builder
ordering rule - no derivation, execution, replay, or write happens in
this module. The established safe typed 404, 409 invalid_state, 409
conflict, and 409 integrity_error mappings and the generic no-leak
error bodies are preserved unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from kalhas.api.requests_campaign_decision import (
    CampaignDecisionPolicyDeclarationRequest,
)
from kalhas.application.campaign_decision_policy_service import (
    CampaignDecisionPolicyDeclarationDraft,
    declare_campaign_decision_policy,
    get_verified_campaign_decision_policy,
)
from kalhas.application.campaign_decision_query_service import (
    get_verified_campaign_decision_brief,
    get_verified_campaign_strategy_comparison,
)
from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.contracts.v1.campaign_decision import (
    CampaignDecisionBrief,
    CampaignDecisionPolicy,
    CampaignStrategyComparison,
    ObjectiveTargetRequirement,
)

router = APIRouter(tags=["campaign-decision"])


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
    raise the typed unsupported-runtime error (409 conflict) before any
    policy or query service is invoked. The complete recorded ``RunPlan``
    tuple is inspected - a legacy, unsupported, or mixed runtime at the
    first, middle, or last position fails closed - and no query parameter
    or caller-provided switch is ever read. Recorded run plans are never
    mutated or repaired.
    """
    plans = store.get_run_plans(tenant_id, campaign_id)
    if not plans:
        # Fail closed: no recorded runtime exists, so no policy
        # declaration or artifact query may run.
        raise UnsupportedRuntimeVersionError("", operation="campaign decision surface")
    for plan in plans:
        if plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="campaign decision surface"
            )


def _declaration_draft(
    declaration: CampaignDecisionPolicyDeclarationRequest,
) -> CampaignDecisionPolicyDeclarationDraft:
    """Convert the validated request into the exact service-owned draft.

    Per-objective request records become immutable
    ``ObjectiveTargetRequirement`` records in exact request order, and
    only caller-owned fields are copied - no caller-supplied
    identifier, hash, tenant, campaign, scenario, world, evaluation
    profile, weight, tail, runtime, or algorithm data is representable
    or forwarded.
    """
    return CampaignDecisionPolicyDeclarationDraft(
        target_requirement_mode=declaration.target_requirement_mode,
        minimum_sample_count=declaration.minimum_sample_count,
        tie_tolerance=declaration.tie_tolerance,
        all_targeted_objectives_are_hard_gates=declaration.all_targeted_objectives_are_hard_gates,
        declared_at=declaration.declared_at,
        minimum_target_achievement_probability=declaration.minimum_target_achievement_probability,
        objective_target_requirements=tuple(
            ObjectiveTargetRequirement(
                objective_id=requirement.objective_id,
                minimum_target_achievement_probability=(
                    requirement.minimum_target_achievement_probability
                ),
            )
            for requirement in declaration.objective_target_requirements
        ),
        metadata=declaration.metadata,
    )


@router.post(
    "/v1/campaigns/{campaign_id}/decision-policy",
    response_model=CampaignDecisionPolicy,
    status_code=201,
    summary="Declare a completed campaign's immutable decision policy",
)
def declare_campaign_decision_policy_route(
    campaign_id: str,
    declaration: CampaignDecisionPolicyDeclarationRequest,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignDecisionPolicy:
    """Declare the immutable decision policy of one COMPLETE 3.0.0 campaign.

    The tenant-scoped recorded run plans are read first (every recorded
    runtime must be exactly 3.0.0; an empty plan tuple or any other
    value returns the typed 409 conflict before the declaration service
    is invoked), then the validated caller-owned request is converted
    into the exact service-owned immutable draft and the accepted
    declaration service is called exactly once. The service owns every
    validation and construction rule: a successful declaration returns
    201 with the verified stored policy; a duplicate declaration the
    typed 409 conflict; a non-COMPLETE campaign the typed 409
    invalid_state; an invalid request or service-level policy the typed
    422; a stored-record integrity failure the typed 409 integrity_error;
    and an unknown or foreign campaign the typed 404 - without leaking
    hashes, identities, thresholds, metadata, internal reasons, or
    validator diagnostics. Any failed declaration performs zero writes.
    """
    _require_runtime_three_campaign(_store(request), x_tenant_id, campaign_id)
    return declare_campaign_decision_policy(
        store=_store(request),
        tenant_id=x_tenant_id,
        campaign_id=campaign_id,
        draft=_declaration_draft(declaration),
    )


@router.get(
    "/v1/campaigns/{campaign_id}/decision-policy",
    response_model=CampaignDecisionPolicy,
    summary="Fetch a campaign's stored decision policy",
)
def get_campaign_decision_policy_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignDecisionPolicy:
    """Fetch and independently verify the stored decision policy of a campaign.

    The tenant-scoped recorded run plans are read first (every recorded
    runtime must be exactly 3.0.0; an empty plan tuple or any other
    value returns the typed 409 conflict before the query is invoked),
    then the stored policy is retrieved and independently verified
    through the accepted verified query. A missing or foreign policy
    returns the typed 404; a corrupted, forged, or validator-bypassed
    stored policy the typed 409 integrity_error - without leaking
    hashes, identities, thresholds, metadata, or internal reasons. A
    stored policy remains retrievable even if the campaign state is
    later non-COMPLETE. The GET performs no derivation, execution,
    write, or operational-activity event.
    """
    _require_runtime_three_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_campaign_decision_policy(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/strategy-comparison",
    response_model=CampaignStrategyComparison,
    summary="Fetch a completed campaign's verified strategy comparison",
)
def get_campaign_strategy_comparison_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignStrategyComparison:
    """Fetch the derived strategy comparison of a COMPLETE 3.0.0 campaign.

    The tenant-scoped recorded run plans are read first (every recorded
    runtime must be exactly 3.0.0; an empty plan tuple or any other
    value returns the typed 409 conflict before the query is invoked),
    then the accepted verified query is called exactly once; the query
    service owns the COMPLETE/policy-first/outcome/builder ordering and
    the derived comparison is returned directly and never stored.
    Unknown or foreign campaigns return the typed 404; a missing policy
    the typed 404; non-COMPLETE campaigns the typed 409 invalid_state;
    and policy, outcome, or comparison integrity failures the typed 409
    integrity_error - without leaking hashes, identities, values,
    thresholds, or internal reasons. Repeated GETs are byte-identical
    and store-neutral. The GET performs no execution, replay,
    extraction, evaluation, write, or operational-activity event.
    """
    _require_runtime_three_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_campaign_strategy_comparison(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )


@router.get(
    "/v1/campaigns/{campaign_id}/decision-brief",
    response_model=CampaignDecisionBrief,
    summary="Fetch a completed campaign's verified decision brief",
)
def get_campaign_decision_brief_route(
    campaign_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> CampaignDecisionBrief:
    """Fetch the derived decision brief of a COMPLETE 3.0.0 campaign.

    The tenant-scoped recorded run plans are read first (every recorded
    runtime must be exactly 3.0.0; an empty plan tuple or any other
    value returns the typed 409 conflict before the query is invoked),
    then the accepted verified query is called exactly once; the query
    service owns the COMPLETE/policy-first/outcome/comparison/builder
    ordering - no duplicate outcome or comparison work happens in this
    route - and the derived brief is returned directly and never
    stored. Unknown or foreign campaigns return the typed 404; a
    missing policy the typed 404; non-COMPLETE campaigns the typed 409
    invalid_state; and policy, outcome, comparison, or brief integrity
    failures the typed 409 integrity_error - without leaking hashes,
    identities, values, thresholds, or internal reasons. Repeated GETs
    are byte-identical and store-neutral. The GET performs no
    execution, replay, extraction, evaluation, write, or
    operational-activity event.
    """
    _require_runtime_three_campaign(_store(request), x_tenant_id, campaign_id)
    return get_verified_campaign_decision_brief(
        store=_store(request), tenant_id=x_tenant_id, campaign_id=campaign_id
    )
