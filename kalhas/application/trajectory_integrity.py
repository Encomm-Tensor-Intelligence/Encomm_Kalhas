"""Strict verification of stored trajectory execution and replay records.

Pure, read-only, deterministic verification of a stored
``RunTrajectoryExecution`` or ``RunTrajectoryReplayManifest`` against the
verified authoritative inputs from which it must have been built:

- complete contract revalidation (serializer-based strict revalidation,
  defeating validator bypass);
- deterministic identifiers;
- tenant/run/campaign/run-plan/world/strategy/seed/runtime ownership and
  content hashes;
- the run input hash and the exact ordered plan-set hash;
- exact result count and canonical state-model order;
- per-result plan/model identity and content hash, initial/final state
  hashes, attempt positions and authoritative transition references,
  trace hashes, and the result content hash;
- the aggregate execution content hash;
- ``executed_at``/``replayed_at`` from the recorded RunPlan creation
  time;
- replay expected and recomputed hashes equal to the authoritative
  execution hash.

A record that fails any check is rejected with a safe typed error - it
is never repaired, normalized, replaced, or silently accepted. The
public message stays generic; the internal ``reason`` names only the
violated rule, never state values, guards, targets, policies, or raw
hashes.
"""

from __future__ import annotations

import warnings

from pydantic import ValidationError

from kalhas.application.domain_errors import (
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryReplayManifestConflictError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.input_integrity import VerifiedRunInputs
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_runtime import (
    run_trajectory_execution_content_hash,
    run_trajectory_execution_identifier,
    state_trajectory_result_content_hash,
    trajectory_plan_set_hash,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    strategy_candidate_content_hash,
)
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryAttemptRecord,
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)

_REPLAY_MANIFEST_ID_PREFIX = "trajectory-replay-"


def _execution_reject(run_id: str, reason: str) -> RunTrajectoryExecutionIntegrityError:
    """A generic, safe execution integrity error with an internal reason."""
    return RunTrajectoryExecutionIntegrityError(run_id, reason)


def _manifest_reject(run_id: str, reason: str) -> RunTrajectoryReplayManifestConflictError:
    """A generic, safe manifest conflict error with an internal reason."""
    return RunTrajectoryReplayManifestConflictError("", run_id, reason=reason)


def _trace_hash(attempts: tuple[RunTrajectoryAttemptRecord, ...]) -> str:
    """Recompute the deterministic trace hash over ordered contract attempts.

    Mirrors the Phase 13 engine's canonical attempt-record digest: each
    contract attempt is serialized and its ``transition_identifier``
    (the only field the engine's records do not carry) is removed, so
    the canonical serialization - and therefore the SHA-256 digest - is
    byte-identical to the engine's own ``trace_hash`` computation over
    the same ordered attempts.
    """
    records: list[dict[str, object]] = []
    for attempt in attempts:
        payload = dict(attempt.model_dump(mode="json"))
        del payload["transition_identifier"]
        records.append(payload)
    return sha256_hex(canonical_json(records))


def verify_run_trajectory_execution_record(
    execution: RunTrajectoryExecution,
    *,
    inputs: VerifiedRunInputs,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
) -> None:
    """Verify a stored trajectory execution exactly represents authoritative output.

    Every check below is deterministic; the first violated rule raises
    :class:`RunTrajectoryExecutionIntegrityError` with a generic public
    message and an internal reason. The record is never repaired or
    replaced.
    """
    run_id = inputs.status.run_id

    # Strict contract revalidation first: a validator-bypassed record is
    # rejected before any field of it is trusted.
    if not isinstance(execution, RunTrajectoryExecution):
        raise _execution_reject(run_id, "stored trajectory execution violates its contract")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = execution.model_dump(mode="python")
        RunTrajectoryExecution.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _execution_reject(
            run_id, "stored trajectory execution violates its contract"
        ) from None

    if execution.identifier != run_trajectory_execution_identifier(
        run_id=run_id, runtime_version=inputs.run_plan.runtime_version
    ):
        raise _execution_reject(run_id, "trajectory execution identifier mismatch")
    if execution.tenant_id != inputs.run_plan.tenant_id:
        raise _execution_reject(run_id, "trajectory execution tenant mismatch")
    if execution.run_id != run_id:
        raise _execution_reject(run_id, "trajectory execution run identity mismatch")
    if execution.campaign_id != inputs.run_plan.campaign_id:
        raise _execution_reject(run_id, "trajectory execution campaign mismatch")
    if execution.run_plan_id != inputs.run_plan.identifier:
        raise _execution_reject(run_id, "trajectory execution run plan mismatch")
    if execution.world_version_id != inputs.world.identifier:
        raise _execution_reject(run_id, "trajectory execution world version mismatch")
    if execution.world_content_hash != inputs.world.content_hash:
        raise _execution_reject(run_id, "trajectory execution world content hash mismatch")
    if execution.strategy_candidate_id != inputs.strategy.identifier:
        raise _execution_reject(run_id, "trajectory execution strategy mismatch")
    if execution.strategy_content_hash != strategy_candidate_content_hash(inputs.strategy):
        raise _execution_reject(run_id, "trajectory execution strategy content hash mismatch")
    if execution.scenario_seed_id != inputs.seed.identifier:
        raise _execution_reject(run_id, "trajectory execution scenario seed mismatch")
    if execution.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise _execution_reject(run_id, "trajectory execution runtime version mismatch")
    if execution.input_hash != inputs.run_plan.input_hash:
        raise _execution_reject(run_id, "trajectory execution input hash mismatch")
    if execution.trajectory_plan_set_hash != trajectory_plan_set_hash(plans):
        raise _execution_reject(run_id, "trajectory execution plan set hash mismatch")
    if len(execution.results) != len(plans):
        raise _execution_reject(run_id, "trajectory execution result count mismatch")
    if execution.executed_at != inputs.run_plan.created_at:
        raise _execution_reject(run_id, "trajectory execution executed_at mismatch")

    models_by_identifier = {
        catalog.state_model.identifier: catalog.state_model for catalog in catalogs
    }
    transitions_by_identifier = {
        transition.identifier: transition
        for catalog in catalogs
        for transition in catalog.transitions
    }

    for result, plan in zip(execution.results, plans, strict=True):
        if result.trajectory_plan_id != plan.identifier:
            raise _execution_reject(run_id, "trajectory result plan identity mismatch")
        if result.trajectory_plan_content_hash != plan.content_hash:
            raise _execution_reject(run_id, "trajectory result plan content hash mismatch")
        state_model = models_by_identifier.get(plan.state_model_identifier)
        if state_model is None:
            raise _execution_reject(run_id, "trajectory result state model missing from the world")
        if result.manifest_id != state_model.manifest_id:
            raise _execution_reject(run_id, "trajectory result manifest mismatch")
        if result.state_model_identifier != state_model.identifier:
            raise _execution_reject(run_id, "trajectory result state model identifier mismatch")
        if result.state_model_id != state_model.state_model_id:
            raise _execution_reject(run_id, "trajectory result state model identity mismatch")
        if result.state_model_content_hash != state_model.content_hash:
            raise _execution_reject(run_id, "trajectory result state model content hash mismatch")
        if result.initial_state_hash != state_hash(result.initial_state):
            raise _execution_reject(run_id, "trajectory result initial state hash mismatch")
        if result.final_state_hash != state_hash(result.final_state):
            raise _execution_reject(run_id, "trajectory result final state hash mismatch")
        if result.trace_hash != _trace_hash(result.attempts):
            raise _execution_reject(run_id, "trajectory result trace hash mismatch")
        if result.content_hash != state_trajectory_result_content_hash(result):
            raise _execution_reject(run_id, "trajectory result content hash mismatch")
        for position, attempt in enumerate(result.attempts):
            if attempt.sequence_position != position:
                raise _execution_reject(run_id, "trajectory attempt positions are not contiguous")
            transition = transitions_by_identifier.get(attempt.transition_identifier)
            if transition is None:
                raise _execution_reject(
                    run_id, "trajectory attempt references an unknown transition"
                )
            if (
                transition.manifest_id != state_model.manifest_id
                or transition.state_model_id != state_model.state_model_id
                or transition.state_model_content_hash != state_model.content_hash
            ):
                raise _execution_reject(run_id, "trajectory attempt transition model mismatch")
            if transition.transition_id != attempt.transition_id:
                raise _execution_reject(run_id, "trajectory attempt transition id mismatch")
            if transition.content_hash != attempt.transition_content_hash:
                raise _execution_reject(
                    run_id, "trajectory attempt transition content hash mismatch"
                )

    if execution.content_hash != run_trajectory_execution_content_hash(execution):
        raise _execution_reject(run_id, "trajectory execution content hash mismatch")


def trajectory_replay_manifest_identifier(run_id: str) -> str:
    """Deterministic identifier of a run's trajectory replay manifest."""
    return f"{_REPLAY_MANIFEST_ID_PREFIX}{run_id}"


def verify_run_trajectory_replay_manifest_record(
    manifest: RunTrajectoryReplayManifest,
    *,
    inputs: VerifiedRunInputs,
    execution: RunTrajectoryExecution,
    plan_set_hash: str,
) -> None:
    """Verify a stored trajectory replay manifest exactly represents one exact replay.

    The manifest must bind to the run, campaign, and stored execution
    artifact; carry the verified world/strategy/seed identities, the
    trajectory runtime version, the run input hash, and the exact ordered
    plan-set hash; and record expected and recomputed execution hashes
    equal to the authoritative execution content hash, with a
    deterministic ``replayed_at`` from the recorded RunPlan creation
    time. Any violation raises
    :class:`RunTrajectoryReplayManifestConflictError` with a generic
    public message and an internal reason; the record is never repaired
    or replaced.
    """
    run_id = inputs.status.run_id

    if not isinstance(manifest, RunTrajectoryReplayManifest):
        raise _manifest_reject(run_id, "stored trajectory replay manifest violates its contract")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = manifest.model_dump(mode="python")
        RunTrajectoryReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _manifest_reject(
            run_id, "stored trajectory replay manifest violates its contract"
        ) from None

    if manifest.identifier != trajectory_replay_manifest_identifier(run_id):
        raise _manifest_reject(run_id, "trajectory replay manifest identifier mismatch")
    if manifest.tenant_id != inputs.run_plan.tenant_id:
        raise _manifest_reject(run_id, "trajectory replay manifest tenant mismatch")
    if manifest.run_id != run_id:
        raise _manifest_reject(run_id, "trajectory replay manifest run identity mismatch")
    if manifest.campaign_id != inputs.run_plan.campaign_id:
        raise _manifest_reject(run_id, "trajectory replay manifest campaign mismatch")
    if manifest.run_trajectory_execution_id != execution.identifier:
        raise _manifest_reject(run_id, "trajectory replay manifest execution reference mismatch")
    if manifest.world_version_id != inputs.world.identifier:
        raise _manifest_reject(run_id, "trajectory replay manifest world version mismatch")
    if manifest.strategy_candidate_id != inputs.strategy.identifier:
        raise _manifest_reject(run_id, "trajectory replay manifest strategy mismatch")
    if manifest.scenario_seed_id != inputs.seed.identifier:
        raise _manifest_reject(run_id, "trajectory replay manifest scenario seed mismatch")
    if manifest.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise _manifest_reject(run_id, "trajectory replay manifest runtime version mismatch")
    if manifest.input_hash != inputs.run_plan.input_hash:
        raise _manifest_reject(run_id, "trajectory replay manifest input hash mismatch")
    if manifest.trajectory_plan_set_hash != plan_set_hash:
        raise _manifest_reject(run_id, "trajectory replay manifest plan set hash mismatch")
    if manifest.expected_execution_hash != execution.content_hash:
        raise _manifest_reject(run_id, "trajectory replay manifest expected hash mismatch")
    if manifest.recomputed_execution_hash != execution.content_hash:
        raise _manifest_reject(run_id, "trajectory replay manifest recomputed hash mismatch")
    if manifest.expected_execution_hash != manifest.recomputed_execution_hash:
        raise _manifest_reject(run_id, "trajectory replay manifest hash disagreement")
    if manifest.replayed_at != inputs.run_plan.created_at:
        raise _manifest_reject(run_id, "trajectory replay manifest replayed_at mismatch")
