"""Exact replay of a completed run.

Replay first verifies the run's recorded input integrity, then loads only
recorded in-memory inputs (immutable world, recorded strategy candidate,
recorded seed, run plan, recorded runtime version), regenerates the
deterministic event stream, recomputes the event hash, and compares it with
the stored expected hash. The regenerated stream is the replay result -
cached event output is never used.

Runtime selection derives only from the recorded RunPlan/RunStatus:

- legacy "1.0.0" runs replay exactly as before: the three structural
  events are regenerated, the structural event hash is compared, the
  existing ``ReplayManifest`` is created and stored, and no trajectory
  replay manifest is required or created;
- trajectory "2.0.0" runs additionally verify the stored
  ``RunTrajectoryExecution`` artifact (contract, deterministic
  identifier, ownership, runtime, input hash, plan-set hash, content
  hash), reload and verify the current immutable trajectory-plan
  collection, resolve the same closed compiled-world catalogs,
  regenerate the complete expected execution through the pure builder,
  require exact full-object and content-hash equality with the stored
  authoritative artifact, and only then store both replay manifests.
  The regenerated output is always produced independently - cached
  trajectory results are never read as the replay output;
- any other recorded version is rejected with a typed
  :class:`UnsupportedRuntimeVersionError` before either replay manifest
  is written.

No LEGION, NEXUS, domain pack, provider, network, randomness, or wall
clock is used during replay.
"""

from __future__ import annotations

from typing import Literal, cast

from kalhas.application.domain_errors import (
    ReplayHashMismatchError,
    RunNotCompleteError,
    TrajectoryReplayMismatchError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import VerifiedRunInputs, verify_run_inputs
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.run_trajectory_runtime import build_run_trajectory_execution
from kalhas.application.structural_runtime import event_hash, structural_events
from kalhas.application.trajectory_integrity import (
    trajectory_replay_manifest_identifier,
    verify_run_trajectory_execution_record,
)
from kalhas.contracts.v1.execution import ReplayManifest, RunState
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryReplayManifest


def replay_run(*, store: InMemoryScenarioStore, tenant_id: str, run_id: str) -> ReplayManifest:
    """Verify input integrity, then regenerate a COMPLETE run's event stream.

    Raises RunNotCompleteError unless the run is COMPLETE, the typed input
    integrity error when the recorded inputs are inconsistent or tampered
    (raised before any replay hash comparison), and ReplayHashMismatchError
    when the regenerated hash differs from the recorded expected event hash.
    For trajectory-runtime runs the stored execution artifact is verified
    and independently regenerated first, and a
    :class:`TrajectoryReplayMismatchError` (or the typed execution
    integrity error) is raised before either replay manifest is written on
    any mismatch. Returns the existing ``ReplayManifest`` in every case.
    """
    status = store.get_run_status(tenant_id, run_id)
    if status.state is not RunState.COMPLETE:
        raise RunNotCompleteError(run_id, status.state.value)

    # Integrity gate: tampered or inconsistent inputs fail before regeneration.
    verified = verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
    recorded_version = verified.run_plan.runtime_version
    if recorded_version == LEGACY_STRUCTURAL_RUNTIME_VERSION:
        return _replay_legacy(store, tenant_id, run_id, verified)
    if recorded_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(recorded_version, operation="run replay")
    return _replay_trajectory(store, tenant_id, run_id, verified)


def _replay_legacy(
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
    verified: VerifiedRunInputs,
) -> ReplayManifest:
    """The exact legacy structural replay (runtime version 1.0.0).

    Byte-identical to the pre-Phase 16 behavior: the integrity manifest
    is recorded, the three structural events are regenerated, the event
    hash is compared, and the existing ``ReplayManifest`` is created and
    stored. No trajectory replay manifest is required or created.
    """
    store.put_input_integrity_manifest(tenant_id, run_id, verified.manifest)

    run_plan = verified.run_plan
    events = structural_events(
        run_plan=run_plan,
        world=verified.world,
        strategy=verified.strategy,
        seed=verified.seed,
        run_id=run_id,
    )
    recomputed_hash = event_hash(events)
    if recomputed_hash != verified.status.event_hash:
        raise ReplayHashMismatchError(run_id)

    manifest = ReplayManifest(
        identifier=f"replay-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=verified.status.campaign_id,
        world_version_id=run_plan.world_version_id,
        strategy_candidate_id=run_plan.strategy_candidate_id,
        scenario_seed_id=run_plan.scenario_seed_id,
        runtime_version=verified.status.runtime_version,
        input_hash=verified.status.input_hash,
        expected_event_hash=recomputed_hash,
        created_at=run_plan.created_at,
    )
    store.put_replay_manifest(tenant_id, run_id, manifest)
    return manifest


def _replay_trajectory(
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
    verified: VerifiedRunInputs,
) -> ReplayManifest:
    """The exact trajectory replay (runtime version 2.0.0).

    Every structural and trajectory check completes before either replay
    manifest is written: the trajectory inputs are resolved (reloading
    and verifying the current immutable plan collection and the closed
    compiled-world catalogs), the stored ``RunTrajectoryExecution`` is
    verified (contract revalidation, deterministic identifier, ownership,
    runtime, input hash, plan-set hash, content hash), the complete
    expected execution is independently regenerated through the pure
    builder, and exact full-object and content-hash equality with the
    stored authoritative artifact is required. The three structural
    events are regenerated and compared as today. On any mismatch a
    typed safe error is raised and neither replay manifest is created;
    no state values or hashes are exposed publicly.
    """
    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    inputs = trajectory_inputs.inputs

    # The stored authoritative artifact is verified, never trusted by
    # reference: contract revalidation first, then deterministic
    # identifier, ownership, runtime, input hash, plan-set hash, and
    # self-consistent content hash.
    stored_execution = store.get_run_trajectory_execution(tenant_id, run_id)
    verify_run_trajectory_execution_record(
        stored_execution,
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )

    # Independently regenerate the complete expected execution from
    # recorded inputs only - never from the cached stored artifact.
    regenerated = build_run_trajectory_execution(
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
    )
    if regenerated != stored_execution:
        raise TrajectoryReplayMismatchError(run_id)
    if regenerated.content_hash != stored_execution.content_hash:
        raise TrajectoryReplayMismatchError(run_id)

    run_plan = inputs.run_plan
    recorded_runtime: Literal["2.0.0"] = cast(Literal["2.0.0"], inputs.status.runtime_version)
    events = structural_events(
        run_plan=run_plan,
        world=inputs.world,
        strategy=inputs.strategy,
        seed=inputs.seed,
        run_id=run_id,
    )
    recomputed_hash = event_hash(events)
    if recomputed_hash != inputs.status.event_hash:
        raise ReplayHashMismatchError(run_id)

    manifest = ReplayManifest(
        identifier=f"replay-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=inputs.status.campaign_id,
        world_version_id=run_plan.world_version_id,
        strategy_candidate_id=run_plan.strategy_candidate_id,
        scenario_seed_id=run_plan.scenario_seed_id,
        runtime_version=recorded_runtime,
        input_hash=inputs.status.input_hash,
        expected_event_hash=recomputed_hash,
        created_at=run_plan.created_at,
    )
    trajectory_manifest = RunTrajectoryReplayManifest(
        identifier=trajectory_replay_manifest_identifier(run_id),
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=inputs.status.campaign_id,
        run_trajectory_execution_id=stored_execution.identifier,
        world_version_id=run_plan.world_version_id,
        strategy_candidate_id=run_plan.strategy_candidate_id,
        scenario_seed_id=run_plan.scenario_seed_id,
        runtime_version=recorded_runtime,
        input_hash=inputs.status.input_hash,
        trajectory_plan_set_hash=stored_execution.trajectory_plan_set_hash,
        expected_execution_hash=stored_execution.content_hash,
        recomputed_execution_hash=regenerated.content_hash,
        replay_classification="exact",
        replayed_at=run_plan.created_at,
    )
    store.put_replay_manifest(tenant_id, run_id, manifest)
    store.put_run_trajectory_replay_manifest(tenant_id, run_id, trajectory_manifest)
    return manifest
