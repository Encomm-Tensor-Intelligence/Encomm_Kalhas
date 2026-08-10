"""Verified read-only inspection of stored trajectory artifacts (Phase 17).

Phase 17 exposes the immutable artifacts already produced and verified by
Phase 16 - the ``RunTrajectoryExecution`` of a completed trajectory-runtime
run and its ``RunTrajectoryReplayManifest`` after an exact replay - through
a strictly read-only, tenant-scoped application query surface.

Both queries follow the same verified pipeline:

1. ``verify_run_trajectory_inputs`` loads and verifies the recorded run
   inputs (run status, run plan, campaign, compiled world, recorded
   strategy, recorded seed, runtime version, input hash) and resolves the
   exact applicable trajectory-plan tuple and the closed compiled-world
   catalogs, branching only on the recorded runtime version. Unknown or
   foreign runs fail with the store's typed not-found error; tampered
   recorded inputs fail with the typed integrity error; unsupported
   recorded runtime versions fail with the typed unsupported-version
   error - all before any stored artifact is loaded.
2. The stored artifact is loaded through the store's snapshot-isolation
   boundary (a fresh deep copy) and verified with the Phase 16 verifiers
   - never trusted by reference and never rebuilt, repaired, normalized,
   or replaced.
3. Only a completely verified artifact is returned.

The query service performs **no execution, no replay, no evaluation, and
no writes of any kind**: it never calls ``build_run_trajectory_execution``,
``replay_run``, ``evaluate_trajectory``, or the store's ``put_*`` surface,
it records no operational activity, changes no lifecycle state, and
creates no events or replay manifests. A replay-manifest query on a run
that has not been replayed yet returns the typed not-found error instead
of creating the manifest.

The service is pure application logic: no FastAPI, no LEGION/NEXUS calls
or imports, no domain-pack loading or execution, and no wall clock,
randomness, filesystem, database, provider, or network access.
"""

from __future__ import annotations

from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_trajectory_inputs import (
    verify_run_trajectory_inputs,
)
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.application.trajectory_integrity import (
    verify_run_trajectory_execution_record,
    verify_run_trajectory_replay_manifest_record,
)
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)


def get_verified_run_trajectory_execution(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunTrajectoryExecution:
    """Load and fully verify a run's stored trajectory execution artifact.

    Resolves the run's verified recorded inputs and the exact applicable
    trajectory plans and closed compiled-world catalogs, loads the stored
    ``RunTrajectoryExecution`` through the store's deep-copy boundary, and
    returns it only after ``verify_run_trajectory_execution_record``
    accepts every deterministic check. Legacy 1.0.0 runs and not-yet-
    executed 2.0.0 runs have no artifact and raise the typed
    ``RunTrajectoryExecutionNotFoundError`` (404); a corrupted or tampered
    artifact raises ``RunTrajectoryExecutionIntegrityError`` (409
    integrity). The artifact is never rebuilt, evaluated, repaired,
    normalized, replaced, or written - this is retrieval only.
    """
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    execution = store.get_run_trajectory_execution(tenant_id, run_id)
    verify_run_trajectory_execution_record(
        execution,
        inputs=trajectory_inputs.inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )
    return execution


def get_verified_run_trajectory_replay_manifest(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> RunTrajectoryReplayManifest:
    """Load and fully verify a run's stored trajectory replay manifest.

    Resolves the run's verified recorded inputs and trajectory inputs,
    loads and verifies the authoritative ``RunTrajectoryExecution`` first,
    then loads the stored ``RunTrajectoryReplayManifest`` and verifies it
    with ``verify_run_trajectory_replay_manifest_record`` against the
    authoritative execution and the exact ordered trajectory plan-set
    hash. A manifest exists only after a successful replay: before that
    the typed ``RunTrajectoryReplayManifestNotFoundError`` (404) is
    raised and nothing is created. A corrupted or tampered manifest
    preserves the existing typed conflict mapping (409 conflict); a
    corrupted authoritative execution fails through the typed integrity
    mapping (409 integrity). Retrieval never triggers ``replay_run``,
    evaluation, regeneration, or any write.
    """
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    execution = store.get_run_trajectory_execution(tenant_id, run_id)
    verify_run_trajectory_execution_record(
        execution,
        inputs=trajectory_inputs.inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )
    plan_set_hash = trajectory_plan_set_hash(trajectory_inputs.plans)
    manifest = store.get_run_trajectory_replay_manifest(tenant_id, run_id)
    verify_run_trajectory_replay_manifest_record(
        manifest,
        inputs=trajectory_inputs.inputs,
        execution=execution,
        plan_set_hash=plan_set_hash,
    )
    return manifest
