"""HTTP routes for the adaptive run execution evidence surface (KALHAS).

Exactly three read-only operations on three unique paths:

- ``GET /v1/runs/{run_id}/adaptive/observations``
- ``GET /v1/runs/{run_id}/adaptive/decisions``
- ``GET /v1/runs/{run_id}/adaptive/switches``

All three operations are ``X-Tenant-ID`` scoped. Each calls the
matching accepted verified query exactly once
(:func:`get_verified_runtime_observation_events`,
:func:`get_verified_adaptive_policy_decision_events`,
:func:`get_verified_adaptive_policy_switch_events`) and returns the
verified tuple directly as the JSON array response: no reordering, no
recomputation, no persistence, no repair, no execution, no replay, and
no operational-activity emission happens in this module. An empty
switch sequence stays a valid empty JSON array. Unknown and foreign
executions are indistinguishable: both raise the store's typed
not-found error, mapped to the established safe 404 envelope, and
corrupted or forged records raise the typed integrity error, mapped to
the established safe 409 integrity envelope - without leaking hashes,
guards, thresholds, hidden state, raw world state, policy internals,
stack traces, validation details, or another tenant's existence. The
module is local and domain-neutral: no wall clock, randomness,
filesystem, database, provider, or network access, and no NEXUS or
LEGION import of any kind.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from kalhas.application.adaptive_run_execution_query_service import (
    get_verified_adaptive_policy_decision_events,
    get_verified_adaptive_policy_switch_events,
    get_verified_runtime_observation_events,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

router = APIRouter(tags=["adaptive-runs"])


def _store(request: Request) -> InMemoryScenarioStore:
    """Resolve the process-local in-memory store from app state."""
    store: InMemoryScenarioStore = request.app.state.store
    return store


@router.get(
    "/v1/runs/{run_id}/adaptive/observations",
    response_model=list[RuntimeObservationEvent],
    summary="Fetch a run's verified canonical adaptive observation events",
)
def get_adaptive_observation_events_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> list[RuntimeObservationEvent]:
    """Fetch the verified canonical observation sequence of one adaptive run.

    The accepted verified query is called exactly once; its verified
    tuple is returned directly in exact canonical ``sequence_position``
    order as the JSON array response. A run without a stored execution,
    and a foreign run alike, raise the typed not-found error (404);
    corrupted or forged records raise the typed integrity error (409)
    - without leaking hashes, thresholds, internals, or another
    tenant's existence. The GET performs no write, no execution, no
    replay, and no operational-activity event.
    """
    return list(
        get_verified_runtime_observation_events(
            store=_store(request), tenant_id=x_tenant_id, run_id=run_id
        )
    )


@router.get(
    "/v1/runs/{run_id}/adaptive/decisions",
    response_model=list[AdaptivePolicyDecisionEvent],
    summary="Fetch a run's verified canonical adaptive policy decision events",
)
def get_adaptive_decision_events_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> list[AdaptivePolicyDecisionEvent]:
    """Fetch the verified canonical decision sequence of one adaptive run.

    The accepted verified query is called exactly once; its verified
    tuple is returned directly in exact contiguous ``decision_step``
    order as the JSON array response. A run without a stored execution,
    and a foreign run alike, raise the typed not-found error (404);
    corrupted or forged records raise the typed integrity error (409)
    - without leaking hashes, thresholds, internals, or another
    tenant's existence. The GET performs no write, no execution, no
    replay, and no operational-activity event.
    """
    return list(
        get_verified_adaptive_policy_decision_events(
            store=_store(request), tenant_id=x_tenant_id, run_id=run_id
        )
    )


@router.get(
    "/v1/runs/{run_id}/adaptive/switches",
    response_model=list[AdaptivePolicySwitchEvent],
    summary="Fetch a run's verified canonical adaptive policy switch events",
)
def get_adaptive_switch_events_route(
    run_id: str,
    request: Request,
    x_tenant_id: str = Header(alias="X-Tenant-ID"),
) -> list[AdaptivePolicySwitchEvent]:
    """Fetch the verified canonical switch sequence of one adaptive run.

    The accepted verified query is called exactly once; its verified
    tuple is returned directly in exact ``decision_step`` order as the
    JSON array response, preserving an empty sequence as a valid empty
    JSON array. A run without a stored execution, and a foreign run
    alike, raise the typed not-found error (404); corrupted or forged
    records raise the typed integrity error (409) - without leaking
    hashes, thresholds, internals, or another tenant's existence. The
    GET performs no write, no execution, no replay, and no
    operational-activity event.
    """
    return list(
        get_verified_adaptive_policy_switch_events(
            store=_store(request), tenant_id=x_tenant_id, run_id=run_id
        )
    )
