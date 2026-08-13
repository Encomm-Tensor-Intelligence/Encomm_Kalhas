"""Observation-aware exact runtime-3 realization replay (Phase 25, Amendment 2).

``replay_realization_run`` regenerates the complete deterministic runtime-3
evidence of one COMPLETE realization-trajectory run **from recorded
immutable inputs only** and attests it through the manifest-pair protocol:
the existing generic ``ReplayManifest`` (structural event-stream attestation)
plus the focused ``RealizationRunTrajectoryReplayManifest`` (execution and
observation-set attestation).

The pipeline is strictly ordered:

1. The recorded RunStatus must be COMPLETE (typed invalid-state error
   otherwise) and ``verify_run_trajectory_inputs`` runs exactly once; the
   separate run-scoped verifier is never called, the recorded runtime must
   be exactly ``\"3.0.0\"`` (1.0.0, 2.0.0, and unknown versions raise the
   typed unsupported-version error), and the verified realization must be
   present - it is never reconstructed or resampled here.
2. The stored ``RealizationRunTrajectoryExecution`` is loaded only through
   the store boundary and fully verified; then the complete execution is
   **independently regenerated** from the immutable verified inputs and
   required to match the stored artifact by exact canonical JSON equality
   **and** content-hash equality (any mismatch raises
   ``TrajectoryReplayMismatchError``). The stored execution is only a
   verified comparison target - its results are never used as replay
   output.
3. Runtime-3 replay is observation-aware: the stored
   ``RealizationRunMetricObservationSet`` must already exist (a missing set
   propagates the typed not-found error, writes nothing, and is never
   auto-extracted). The stored set is fully verified through the existing
   verifier with the already-verified trajectory inputs, and the expected
   set is independently rebuilt **from the regenerated execution** and
   required to match by exact canonical JSON equality **and** content-hash
   equality (any mismatch raises the typed observation integrity error).
   Replay never calls the extraction service and never writes
   observations.
4. The three structural events are regenerated from the verified immutable
   inputs and their recomputed hash must equal the recorded COMPLETE
   ``RunStatus.event_hash`` (mismatch raises ``ReplayHashMismatchError``);
   cached stored events are never loaded as replay output.
5. Both manifests are built completely in memory: the generic manifest
   (identifier ``replay-<run_id>``, runtime 3.0.0, recomputed structural
   event hash, ``replay_classification=\"exact\"``) and the focused runtime-3
   manifest (deterministic identifier, execution and observation-set
   references, expected/recomputed execution and observation hashes from
   the stored/regenerated artifacts, realization identity from the
   verified realization, plan-set hash, ``replay_classification=\"exact\"``,
   ``replayed_at`` = the recorded RunPlan creation time - never the wall
   clock - and a self-covering content hash).
6. The generic store seam overwrites by design, so both collections are
   **probed before the first write**: an existing generic manifest must be
   a strictly revalidated ``ReplayManifest`` byte-identical to the expected
   one (else ``RealizationReplayManifestConflictError``), and an existing
   runtime-3 manifest must pass the focused manifest verifier and be
   byte-identical to the expected one (else
   ``RealizationRunTrajectoryReplayManifestConflictError``). Absence
   continues. A differing or corrupt record is never overwritten or
   repaired.
7. Only then are the two manifests written in order (generic first, then
   runtime-3). Replay writes **only** these two manifests. The writes are
   sequential; no transactional rollback is claimed - a failure after the
   first write may leave partial state, and recovery is a later identical
   replay, which completes the pair idempotently.

Nothing here evaluates or re-executes transitions, rebuilds executions or
observations from cached artifacts, triggers the extraction service or any
lifecycle service, invokes LEGION or NEXUS, performs network, provider,
filesystem, or database operations, uses randomness or wall-clock time, or
produces probabilities, risk statistics, rankings, or recommendations.
"""

from __future__ import annotations

import warnings

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    ReplayHashMismatchError,
    RunNotCompleteError,
    RunNotFoundError,
    TrajectoryReplayMismatchError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_errors import (
    RealizationReplayManifestConflictError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_replay_manifest_content_hash,
    realization_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_execution_record,
    verify_realization_run_trajectory_replay_manifest_record,
)
from kalhas.application.realization_run_metric_observation_service import (
    build_realization_run_metric_observation_set,
    verify_realization_run_metric_observation_set_record,
)
from kalhas.application.realization_trajectory_runtime import (
    build_realization_run_trajectory_execution,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_inputs import (
    verify_run_trajectory_inputs,
)
from kalhas.application.structural_runtime import event_hash, structural_events
from kalhas.contracts.v1.execution import ReplayManifest, RunState
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryReplayManifest,
)

_PLACEHOLDER_HASH = "0" * 64


def _generic_conflict(run_id: str, reason: str) -> RealizationReplayManifestConflictError:
    """A safe generic replay-manifest conflict error with an internal reason."""
    return RealizationReplayManifestConflictError(run_id, reason)


def _realization_conflict(
    run_id: str, reason: str
) -> RealizationRunTrajectoryReplayManifestConflictError:
    """A safe runtime-3 replay-manifest conflict error with an internal reason."""
    return RealizationRunTrajectoryReplayManifestConflictError(run_id, reason)


def _strictly_revalidate_generic_manifest(manifest: object, run_id: str) -> None:
    """Serializer-based strict revalidation of a stored generic manifest."""
    if not isinstance(manifest, ReplayManifest):
        raise _generic_conflict(run_id, "stored replay manifest violates its contract")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = manifest.model_dump(mode="python")
        ReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _generic_conflict(run_id, "stored replay manifest violates its contract") from None


def replay_realization_run(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> ReplayManifest:
    """Observation-aware exact replay of one COMPLETE runtime-3 run.

    Regenerates the complete deterministic execution, observation set,
    and structural event stream from recorded immutable inputs, attests
    them through the generic and runtime-3 manifest pair, probes both
    manifest collections before the first write (immutable, idempotent,
    never overwriting a differing or corrupt record), and returns the
    generic manifest. Writes exactly the two manifests and nothing else.
    """
    status = store.get_run_status(tenant_id, run_id)
    if status.state is not RunState.COMPLETE:
        raise RunNotCompleteError(run_id, status.state.value)

    trajectory_inputs = verify_run_trajectory_inputs(
        store=store, tenant_id=tenant_id, run_id=run_id
    )
    inputs = trajectory_inputs.inputs
    if inputs.run_plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            inputs.run_plan.runtime_version, operation="realization run replay"
        )
    if trajectory_inputs.realization is None:
        raise _realization_conflict(
            run_id, "realized initial state missing after trajectory verification"
        )
    realization = trajectory_inputs.realization
    run_plan = inputs.run_plan

    # --- Execution verification and independent regeneration ---
    stored_execution = store.get_realization_run_trajectory_execution(tenant_id, run_id)
    verify_realization_run_trajectory_execution_record(
        stored_execution,
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
        realization=realization,
    )
    regenerated_execution = build_realization_run_trajectory_execution(
        inputs=inputs,
        plans=trajectory_inputs.plans,
        catalogs=trajectory_inputs.catalogs,
        realization=realization,
    )
    if canonical_json(regenerated_execution.model_dump(mode="json")) != canonical_json(
        stored_execution.model_dump(mode="json")
    ):
        raise TrajectoryReplayMismatchError(run_id)
    if regenerated_execution.content_hash != stored_execution.content_hash:
        raise TrajectoryReplayMismatchError(run_id)

    # --- Observation-aware replay: required prior explicit extraction ---
    stored_observations = store.get_realization_run_metric_observation_set(tenant_id, run_id)
    verify_realization_run_metric_observation_set_record(
        stored_observations,
        store=store,
        tenant_id=tenant_id,
        run_id=run_id,
        trajectory_inputs=trajectory_inputs,
    )
    regenerated_observations = build_realization_run_metric_observation_set(
        inputs=trajectory_inputs, execution=regenerated_execution
    )
    if canonical_json(stored_observations.model_dump(mode="json")) != canonical_json(
        regenerated_observations.model_dump(mode="json")
    ):
        raise RealizationRunMetricObservationIntegrityError(
            run_id, "stored observation set does not match the regenerated artifact"
        )
    if stored_observations.content_hash != regenerated_observations.content_hash:
        raise RealizationRunMetricObservationIntegrityError(
            run_id, "stored observation set content hash mismatch"
        )

    # --- Structural replay from verified immutable inputs ---
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

    # --- Manifest construction (complete in memory) ---
    generic_manifest = ReplayManifest(
        identifier=f"replay-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=status.campaign_id,
        world_version_id=run_plan.world_version_id,
        strategy_candidate_id=run_plan.strategy_candidate_id,
        scenario_seed_id=run_plan.scenario_seed_id,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        input_hash=status.input_hash,
        expected_event_hash=recomputed_hash,
        replay_classification="exact",
        created_at=run_plan.created_at,
    )
    realization_manifest = RealizationRunTrajectoryReplayManifest(
        identifier=realization_run_trajectory_replay_manifest_identifier(run_id),
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=status.campaign_id,
        realization_run_trajectory_execution_id=regenerated_execution.identifier,
        realization_run_metric_observation_set_id=stored_observations.identifier,
        world_version_id=run_plan.world_version_id,
        strategy_candidate_id=run_plan.strategy_candidate_id,
        scenario_seed_id=run_plan.scenario_seed_id,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        input_hash=status.input_hash,
        trajectory_plan_set_hash=regenerated_execution.trajectory_plan_set_hash,
        expected_execution_hash=stored_execution.content_hash,
        recomputed_execution_hash=regenerated_execution.content_hash,
        expected_observation_set_hash=stored_observations.content_hash,
        recomputed_observation_set_hash=regenerated_observations.content_hash,
        replay_classification="exact",
        replayed_at=run_plan.created_at,
        content_hash=_PLACEHOLDER_HASH,
    )
    realization_manifest = realization_manifest.model_copy(
        update={
            "content_hash": realization_run_trajectory_replay_manifest_content_hash(
                realization_manifest
            )
        }
    )

    # --- Pre-write probes (both complete before the first write) ---
    try:
        stored_generic = store.get_replay_manifest(tenant_id, run_id)
    except RunNotFoundError:
        stored_generic = None
    if stored_generic is not None:
        _strictly_revalidate_generic_manifest(stored_generic, run_id)
        if canonical_json(stored_generic.model_dump(mode="json")) != canonical_json(
            generic_manifest.model_dump(mode="json")
        ):
            raise _generic_conflict(
                run_id, "stored replay manifest conflicts with the regenerated manifest"
            )

    try:
        stored_realization_manifest = store.get_realization_run_trajectory_replay_manifest(
            tenant_id, run_id
        )
    except RealizationRunTrajectoryReplayManifestNotFoundError:
        stored_realization_manifest = None
    if stored_realization_manifest is not None:
        verify_realization_run_trajectory_replay_manifest_record(
            stored_realization_manifest,
            inputs=inputs,
            execution=stored_execution,
            observation_set=stored_observations,
            plan_set_hash=regenerated_execution.trajectory_plan_set_hash,
        )
        if canonical_json(stored_realization_manifest.model_dump(mode="json")) != canonical_json(
            realization_manifest.model_dump(mode="json")
        ):
            raise _realization_conflict(
                run_id,
                "stored realization replay manifest conflicts with the regenerated manifest",
            )

    # --- Write phase: exactly these two manifests ---
    store.put_replay_manifest(tenant_id, run_id, generic_manifest)
    store.put_realization_run_trajectory_replay_manifest(tenant_id, run_id, realization_manifest)
    return generic_manifest
