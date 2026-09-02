"""Verified read-only query projections over one adaptive run execution (H28-S10).

Exposes the immutable per-run evidence already produced and stored by the
runtime-4 adaptive execution service - the ``RuntimeObservationEvent``
sequence, the ``AdaptivePolicyDecisionEvent`` sequence, and the
``AdaptivePolicySwitchEvent`` sequence of exactly one stored
``AdaptiveRunTrajectoryExecution`` - through a strictly read-only,
tenant-scoped application query surface. No new contract, schema, store
collection, persisted projection, cache, error taxonomy, adapter, or API
route is introduced.

Every query follows the same verified pipeline, exactly once and in the
established order:

1. The stored adaptive execution is loaded exclusively through the
   authoritative ``InMemoryScenarioStore.get_adaptive_run_trajectory_execution``
   read path. That path strictly revalidates the stored record against its
   contract and cross-authority verifies it against the store's current
   verified authorities on every read; unknown and foreign executions are
   indistinguishable (the typed not-found error), and corrupted or forged
   records raise the typed integrity error - both propagated unchanged.
2. The requested evidence sequence is returned directly from the verified
   aggregate in its exact canonical stored order - observations by
   ``sequence_position``, decisions and switches by ``decision_step`` - as
   an immutable tuple whose members are the aggregate's own frozen
   contracts. The store's snapshot-isolation boundary supplies a fresh
   deep defensive copy, so caller mutation can never affect store
   authority; the query adds no copying, reordering, filtering, or
   rebuilding of its own.

The query service performs no execution, no replay, no observation
derivation, no policy evaluation, and no writes of any kind: it never
calls the store's ``put_*`` surface, appends no operational activity,
transitions no lifecycle state, and never recomputes, reinterprets,
repairs, patches, or persists any scientific or decision authority. The
module is pure application logic: domain-neutral, with no FastAPI, no
NEXUS/LEGION imports, and no wall clock, randomness, filesystem,
database, provider, or network access.
"""

from __future__ import annotations

from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.runtime_observation import RuntimeObservationEvent

__all__ = [
    "get_verified_adaptive_policy_decision_events",
    "get_verified_adaptive_policy_switch_events",
    "get_verified_runtime_observation_events",
]


def _verified_adaptive_run_execution(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> AdaptiveRunTrajectoryExecution:
    """Load one execution through the single authoritative store read path.

    ``get_adaptive_run_trajectory_execution`` is the only authority: it
    strictly revalidates the stored aggregate on every read and
    cross-authority verifies it against the store's current verified
    authorities, raising the typed not-found error for unknown and
    foreign executions alike and the typed integrity error for corrupt
    or forged records. It returns a fresh deep defensive copy, and no
    activity event or sequence is produced. Every established error of
    that path propagates unchanged.
    """
    return store.get_adaptive_run_trajectory_execution(tenant_id=tenant_id, run_id=run_id)


def get_verified_runtime_observation_events(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> tuple[RuntimeObservationEvent, ...]:
    """Return the verified canonical observation sequence of one adaptive run.

    Loads the execution through the authoritative verified read path and
    returns its exact stored ``observation_events`` tuple - canonical
    ``sequence_position`` order, immutable members - without reordering,
    filtering, rebuilding, or reinterpreting anything. A run without a
    stored execution raises the typed not-found error; a corrupt or
    forged execution raises the typed integrity error; both propagate
    unchanged from the authoritative path. An empty tuple is a valid
    verified answer for a horizon with no scheduled observations.
    """
    execution = _verified_adaptive_run_execution(store, tenant_id=tenant_id, run_id=run_id)
    return execution.observation_events


def get_verified_adaptive_policy_decision_events(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> tuple[AdaptivePolicyDecisionEvent, ...]:
    """Return the verified canonical decision sequence of one adaptive run.

    Loads the execution through the authoritative verified read path and
    returns its exact stored ``decision_events`` tuple - contiguous
    ``decision_step`` order ``0..N-1``, immutable members - without
    reordering, filtering, rebuilding, or reinterpreting anything. The
    aggregate contract guarantees at least one decision event. A run
    without a stored execution raises the typed not-found error; a
    corrupt or forged execution raises the typed integrity error; both
    propagate unchanged from the authoritative path.
    """
    execution = _verified_adaptive_run_execution(store, tenant_id=tenant_id, run_id=run_id)
    return execution.decision_events


def get_verified_adaptive_policy_switch_events(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> tuple[AdaptivePolicySwitchEvent, ...]:
    """Return the verified canonical switch sequence of one adaptive run.

    Loads the execution through the authoritative verified read path and
    returns its exact stored ``switch_events`` tuple - strictly ordered
    by ``decision_step``, exactly the ``action_changed`` decisions,
    immutable members - without reordering, filtering, rebuilding, or
    reinterpreting anything. An empty tuple is a valid verified answer
    for a run whose policy never switched actions. A run without a
    stored execution raises the typed not-found error; a corrupt or
    forged execution raises the typed integrity error; both propagate
    unchanged from the authoritative path.
    """
    execution = _verified_adaptive_run_execution(store, tenant_id=tenant_id, run_id=run_id)
    return execution.switch_events
