"""Strict verification of stored runtime-3 realization execution records (Phase 25).

Pure, read-only, deterministic verification of a stored
``RealizationRunTrajectoryExecution`` against the verified authoritative
inputs from which it must have been built:

- complete contract revalidation (serializer-based strict revalidation,
  defeating validator bypass, including non-finite state content);
- deterministic identifiers;
- tenant/run/campaign/run-plan/world/strategy/seed/runtime ownership and
  content hashes;
- the run input hash and the exact ordered plan-set hash;
- the explicitly supplied realization agreeing with ``inputs.realization``
  and with every execution realization field;
- exact result count and canonical state-model order;
- per-result plan/model identity and content hash, the realized initial
  state being exactly model defaults plus the matching realization
  overrides, initial/final state hashes, the attempt state chain
  (first before hash == initial hash, every before hash == the previous
  after hash, last after hash == final hash), attempt positions and
  authoritative transition references, trace hashes, and the result
  content hash;
- the aggregate execution content hash;
- ``executed_at`` from the recorded RunPlan creation time.

This is structural/integrity verification, **not replay**: the engine is
never called, nothing is regenerated, the store is never accessed, and
nothing is written or repaired. A record that fails any check is rejected
with a safe typed error; the public message stays generic and the
internal ``reason`` names only the violated rule, never state values,
guards, targets, policies, uncertainty values, or raw hashes.

The replay-manifest verifier (``verify_realization_run_trajectory_replay_manifest_record``)
verifies a stored runtime-3 replay manifest against the verified inputs,
the stored execution, and the stored observation set: strict contract
revalidation, deterministic identifier, ownership, execution and
observation-set references, world/strategy/seed identities, runtime
literal, input hash, plan-set hash, realization identity equal to the
execution, expected/recomputed execution and observation hashes both
equal to the respective authoritative content hashes,
``replay_classification``, ``replayed_at`` from the recorded RunPlan
creation time, and the self-covering content hash. It never writes or
repairs anything.
"""

from __future__ import annotations

import warnings

from pydantic import ValidationError

from kalhas.application.input_integrity import VerifiedRunInputs
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryReplayManifestConflictError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_execution_content_hash,
    realization_run_trajectory_execution_identifier,
    realization_run_trajectory_replay_manifest_content_hash,
    realization_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.realization_trajectory_runtime import (
    realized_initial_state,
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    strategy_candidate_content_hash,
)
from kalhas.application.trajectory_integrity import _trace_hash
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizationRunTrajectoryReplayManifest,
)
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.world_realization import WorldRealization


def _execution_reject(run_id: str, reason: str) -> RealizationRunTrajectoryExecutionIntegrityError:
    """A generic, safe execution integrity error with an internal reason."""
    return RealizationRunTrajectoryExecutionIntegrityError(run_id, reason)


def verify_realization_run_trajectory_execution_record(
    execution: RealizationRunTrajectoryExecution,
    *,
    inputs: VerifiedRunInputs,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    realization: WorldRealization,
) -> None:
    """Verify a stored runtime-3 execution exactly represents authoritative output.

    Every check below is deterministic; the first violated rule raises
    :class:`RealizationRunTrajectoryExecutionIntegrityError` with a
    generic public message and an internal reason. The record is never
    repaired, regenerated, or replaced, and no store is accessed.
    """
    run_id = inputs.status.run_id

    # Strict contract revalidation first: a validator-bypassed record is
    # rejected before any field of it is trusted.
    if not isinstance(execution, RealizationRunTrajectoryExecution):
        raise _execution_reject(run_id, "stored realization execution violates its contract")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = execution.model_dump(mode="python")
        RealizationRunTrajectoryExecution.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _execution_reject(
            run_id, "stored realization execution violates its contract"
        ) from None

    if execution.identifier != realization_run_trajectory_execution_identifier(
        run_id=run_id, runtime_version=inputs.run_plan.runtime_version
    ):
        raise _execution_reject(run_id, "realization execution identifier mismatch")
    if execution.tenant_id != inputs.run_plan.tenant_id:
        raise _execution_reject(run_id, "realization execution tenant mismatch")
    if execution.run_id != run_id:
        raise _execution_reject(run_id, "realization execution run identity mismatch")
    if execution.campaign_id != inputs.run_plan.campaign_id:
        raise _execution_reject(run_id, "realization execution campaign mismatch")
    if execution.run_plan_id != inputs.run_plan.identifier:
        raise _execution_reject(run_id, "realization execution run plan mismatch")
    if execution.world_version_id != inputs.world.identifier:
        raise _execution_reject(run_id, "realization execution world version mismatch")
    if execution.world_content_hash != inputs.world.content_hash:
        raise _execution_reject(run_id, "realization execution world content hash mismatch")
    if execution.strategy_candidate_id != inputs.strategy.identifier:
        raise _execution_reject(run_id, "realization execution strategy mismatch")
    if execution.strategy_content_hash != strategy_candidate_content_hash(inputs.strategy):
        raise _execution_reject(run_id, "realization execution strategy content hash mismatch")
    if execution.scenario_seed_id != inputs.seed.identifier:
        raise _execution_reject(run_id, "realization execution scenario seed mismatch")
    if execution.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise _execution_reject(run_id, "realization execution runtime version mismatch")
    if execution.input_hash != inputs.run_plan.input_hash:
        raise _execution_reject(run_id, "realization execution input hash mismatch")
    if execution.trajectory_plan_set_hash != trajectory_plan_set_hash(plans):
        raise _execution_reject(run_id, "realization execution plan set hash mismatch")
    if len(execution.results) != len(plans):
        raise _execution_reject(run_id, "realization execution result count mismatch")
    if execution.executed_at != inputs.run_plan.created_at:
        raise _execution_reject(run_id, "realization execution executed_at mismatch")

    # The explicitly supplied realization must be the verified one and
    # must match every realization field of the execution.
    if inputs.realization is None or inputs.realization != realization:
        raise _execution_reject(run_id, "realization does not match the verified run inputs")
    if execution.world_realization_id != realization.identifier:
        raise _execution_reject(run_id, "realization execution realization identity mismatch")
    if execution.world_realization_content_hash != realization.content_hash:
        raise _execution_reject(run_id, "realization execution realization content hash mismatch")

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
            raise _execution_reject(run_id, "realization result plan identity mismatch")
        if result.trajectory_plan_content_hash != plan.content_hash:
            raise _execution_reject(run_id, "realization result plan content hash mismatch")
        state_model = models_by_identifier.get(plan.state_model_identifier)
        if state_model is None:
            raise _execution_reject(run_id, "realization result state model missing from the world")
        if result.manifest_id != state_model.manifest_id:
            raise _execution_reject(run_id, "realization result manifest mismatch")
        if result.state_model_identifier != state_model.identifier:
            raise _execution_reject(run_id, "realization result state model identifier mismatch")
        if result.state_model_id != state_model.state_model_id:
            raise _execution_reject(run_id, "realization result state model identity mismatch")
        if result.state_model_content_hash != state_model.content_hash:
            raise _execution_reject(run_id, "realization result state model content hash mismatch")
        # The realized initial state must be exactly model defaults plus
        # the matching realization overrides, and must be finite JSON.
        expected_initial = realized_initial_state(
            state_model=state_model, realization=realization, run_id=run_id
        )
        if result.initial_state != expected_initial:
            raise _execution_reject(run_id, "realization result realized initial state mismatch")
        if _contains_non_finite(result.initial_state) or _contains_non_finite(result.final_state):
            raise _execution_reject(run_id, "realization result state contains non-finite values")
        if result.initial_state_hash != state_hash(result.initial_state):
            raise _execution_reject(run_id, "realization result initial state hash mismatch")
        if result.final_state_hash != state_hash(result.final_state):
            raise _execution_reject(run_id, "realization result final state hash mismatch")
        if result.trace_hash != _trace_hash(result.attempts):
            raise _execution_reject(run_id, "realization result trace hash mismatch")
        if result.content_hash != realized_state_trajectory_result_content_hash(result):
            raise _execution_reject(run_id, "realization result content hash mismatch")
        references = plan.transition_references
        if len(result.attempts) != len(references):
            raise _execution_reject(run_id, "realization attempt count mismatch")
        if not result.attempts and (
            references
            or result.initial_state != result.final_state
            or result.initial_state_hash != result.final_state_hash
        ):
            raise _execution_reject(run_id, "realization result without attempts changed the state")
        for position, (attempt, reference) in enumerate(
            zip(result.attempts, references, strict=True)
        ):
            # Exact attempt<->plan binding: catalog membership alone is
            # never sufficient; every attempt must equal the authoritative
            # plan reference at the same position.
            if attempt.sequence_position != position:
                raise _execution_reject(run_id, "realization attempt positions are not contiguous")
            if reference.sequence_position != position:
                raise _execution_reject(
                    run_id, "realization attempt reference positions are not contiguous"
                )
            if attempt.transition_identifier != reference.transition_identifier:
                raise _execution_reject(run_id, "realization attempt transition reference mismatch")
            if attempt.transition_id != reference.transition_id:
                raise _execution_reject(run_id, "realization attempt transition id mismatch")
            if attempt.transition_content_hash != reference.transition_content_hash:
                raise _execution_reject(
                    run_id, "realization attempt transition content hash mismatch"
                )
            if position == 0 and attempt.before_state_hash != result.initial_state_hash:
                raise _execution_reject(run_id, "realization first attempt before hash mismatch")
            if (
                position > 0
                and attempt.before_state_hash != result.attempts[position - 1].after_state_hash
            ):
                raise _execution_reject(run_id, "realization attempt state chain mismatch")
            transition = transitions_by_identifier.get(attempt.transition_identifier)
            if transition is None:
                raise _execution_reject(
                    run_id, "realization attempt references an unknown transition"
                )
            if (
                transition.manifest_id != state_model.manifest_id
                or transition.state_model_id != state_model.state_model_id
                or transition.state_model_content_hash != state_model.content_hash
            ):
                raise _execution_reject(run_id, "realization attempt transition model mismatch")
            if transition.transition_id != attempt.transition_id:
                raise _execution_reject(run_id, "realization attempt transition id mismatch")
            if transition.content_hash != attempt.transition_content_hash:
                raise _execution_reject(
                    run_id, "realization attempt transition content hash mismatch"
                )
        if result.attempts and result.attempts[-1].after_state_hash != result.final_state_hash:
            raise _execution_reject(run_id, "realization last attempt after hash mismatch")

    if execution.content_hash != realization_run_trajectory_execution_content_hash(execution):
        raise _execution_reject(run_id, "realization execution content hash mismatch")


def _replay_reject(run_id: str, reason: str) -> RealizationRunTrajectoryReplayManifestConflictError:
    """A safe replay-manifest conflict error with an internal reason."""
    return RealizationRunTrajectoryReplayManifestConflictError(run_id, reason)


def verify_realization_run_trajectory_replay_manifest_record(
    manifest: object,
    *,
    inputs: VerifiedRunInputs,
    execution: RealizationRunTrajectoryExecution,
    observation_set: RealizationRunMetricObservationSet,
    plan_set_hash: str,
) -> None:
    """Verify a stored runtime-3 replay manifest against authoritative records.

    Requires an actual ``RealizationRunTrajectoryReplayManifest`` that
    passes serializer-based strict contract revalidation, then verifies
    the deterministic identifier, tenant/run/campaign ownership, the
    execution and observation-set references, the world/strategy/seed
    identities, the runtime literal, the input hash, the plan-set hash,
    the realization identity (equal to the verified execution's), the
    expected and recomputed execution hashes (both equal to the
    execution's content hash), the expected and recomputed observation
    hashes (both equal to the observation set's content hash), the
    ``replay_classification`` literal, ``replayed_at`` from the recorded
    RunPlan creation time, and the self-covering content hash. Every
    failure raises the safe typed conflict error with a generic public
    message; nothing is ever written or repaired.
    """
    run_id = inputs.status.run_id
    if not isinstance(manifest, RealizationRunTrajectoryReplayManifest):
        raise _replay_reject(run_id, "replay manifest violates its contract")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = manifest.model_dump(mode="python")
        RealizationRunTrajectoryReplayManifest.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise _replay_reject(run_id, "replay manifest violates its contract") from None

    if manifest.identifier != realization_run_trajectory_replay_manifest_identifier(run_id):
        raise _replay_reject(run_id, "replay manifest identifier mismatch")
    if manifest.tenant_id != inputs.run_plan.tenant_id:
        raise _replay_reject(run_id, "replay manifest tenant ownership mismatch")
    if manifest.run_id != run_id or manifest.campaign_id != inputs.status.campaign_id:
        raise _replay_reject(run_id, "replay manifest ownership mismatch")
    if manifest.realization_run_trajectory_execution_id != execution.identifier:
        raise _replay_reject(run_id, "replay manifest execution reference mismatch")
    if manifest.realization_run_metric_observation_set_id != observation_set.identifier:
        raise _replay_reject(run_id, "replay manifest observation reference mismatch")
    if manifest.world_version_id != execution.world_version_id:
        raise _replay_reject(run_id, "replay manifest world identity mismatch")
    if manifest.strategy_candidate_id != execution.strategy_candidate_id:
        raise _replay_reject(run_id, "replay manifest strategy identity mismatch")
    if manifest.scenario_seed_id != execution.scenario_seed_id:
        raise _replay_reject(run_id, "replay manifest scenario seed identity mismatch")
    if manifest.world_realization_id != execution.world_realization_id:
        raise _replay_reject(run_id, "replay manifest realization identity mismatch")
    if manifest.world_realization_content_hash != execution.world_realization_content_hash:
        raise _replay_reject(run_id, "replay manifest realization content hash mismatch")
    if manifest.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise _replay_reject(run_id, "replay manifest runtime version mismatch")
    if manifest.input_hash != inputs.run_plan.input_hash:
        raise _replay_reject(run_id, "replay manifest input hash mismatch")
    if manifest.trajectory_plan_set_hash != plan_set_hash:
        raise _replay_reject(run_id, "replay manifest plan set hash mismatch")
    if manifest.trajectory_plan_set_hash != execution.trajectory_plan_set_hash:
        raise _replay_reject(run_id, "replay manifest plan set hash mismatch")
    if manifest.expected_execution_hash != execution.content_hash:
        raise _replay_reject(run_id, "replay manifest expected execution hash mismatch")
    if manifest.recomputed_execution_hash != execution.content_hash:
        raise _replay_reject(run_id, "replay manifest recomputed execution hash mismatch")
    if manifest.expected_observation_set_hash != observation_set.content_hash:
        raise _replay_reject(run_id, "replay manifest expected observation hash mismatch")
    if manifest.recomputed_observation_set_hash != observation_set.content_hash:
        raise _replay_reject(run_id, "replay manifest recomputed observation hash mismatch")
    if manifest.replay_classification != "exact":
        raise _replay_reject(run_id, "replay manifest classification mismatch")
    if manifest.replayed_at != inputs.run_plan.created_at:
        raise _replay_reject(run_id, "replay manifest replayed at mismatch")
    if manifest.content_hash != realization_run_trajectory_replay_manifest_content_hash(manifest):
        raise _replay_reject(run_id, "replay manifest content hash mismatch")
