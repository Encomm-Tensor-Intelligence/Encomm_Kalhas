"""Pure deterministic run trajectory execution artifact builder (Phase 16).

Builds the immutable ``RunTrajectoryExecution`` artifact of one
trajectory-runtime (2.0.0) run from **already verified authoritative
records only**: the verified run inputs (``VerifiedRunInputs`` from the
existing run-input verifier), the exact applicable ``StrategyTrajectoryPlan``
tuple (the run's strategy subset of the verified campaign collection, in
canonical order), and the exact closed compiled-world catalogs (the same
Phase 15 construction planning and stored-plan verification use). The
module never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input.

Evaluation is delegated **exclusively** to the existing Phase 13 kernel
(``evaluate_trajectory`` - one call per applicable state-model plan, in
the campaign's canonical plan order, with the plan's transition
references preserved exactly, including repetitions). The engine's
deep-frozen result snapshots are converted to fresh, detached plain JSON
trees via the engine's public ``state_to_plain_json`` helper; every
engine attempt is zipped with its authoritative plan reference and its
position, transition id, and content hash are verified before the
attempt record is built. The recorded seed identity is carried into the
artifact's provenance (``scenario_seed_id``) purely as recorded
identity: the declarative transition kernel does not sample or use the
seed, and nothing here pretends otherwise.

Hash rules (repository-wide canonical JSON + SHA-256 conventions only):

- ``trajectory_plan_set_hash(plans)``: SHA-256 over the canonical
  serialization of the complete ordered plan collection (tuple ordering
  significant - it is the *plan-set* digest of exactly the applicable
  plans in canonical order).
- ``state_trajectory_result_content_hash(result)``: SHA-256 over the
  complete canonical result serialization excluding ``content_hash``.
- ``run_trajectory_execution_identifier(...)``: deterministic from the
  run identity and runtime version.
- ``run_trajectory_execution_content_hash(execution)``: SHA-256 over the
  complete canonical execution serialization excluding ``content_hash``.

All errors are safe typed domain errors; public messages never expose
state values, hashes, guards, targets, or validation details.
"""

from __future__ import annotations

from typing import Literal

from kalhas.application.domain_errors import (
    RunTrajectoryExecutionIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.input_integrity import VerifiedRunInputs
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION
from kalhas.application.state_transition_engine import (
    evaluate_trajectory,
    state_to_plain_json,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    strategy_candidate_content_hash,
)
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import (
    RunStateTrajectoryResult,
    RunTrajectoryAttemptRecord,
    RunTrajectoryExecution,
)
from kalhas.contracts.v1.transition import DomainStateTransition

_EXECUTION_ID_PREFIX = "trajectory-execution-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64

_Outcome = Literal["applied", "guard_not_satisfied"]


def trajectory_plan_set_hash(plans: tuple[StrategyTrajectoryPlan, ...]) -> str:
    """SHA-256 over the canonical serialization of the ordered plan collection.

    The digest covers the complete canonical dump of every plan in the
    supplied tuple order, so ordering, membership, and plan content are
    all significant: any missing, additional, reordered, or tampered
    plan changes the digest.
    """
    return sha256_hex(canonical_json([plan.model_dump(mode="json") for plan in plans]))


def state_trajectory_result_content_hash(result: RunStateTrajectoryResult) -> str:
    """Canonical SHA-256 of the complete result content, excluding content_hash."""
    payload = result.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def run_trajectory_execution_identifier(*, run_id: str, runtime_version: str) -> str:
    """Deterministic execution identifier from the run identity and runtime version.

    Hash-derived from the canonical ``(run_id, runtime_version)``
    identity with a readable, distinct prefix; identical inputs always
    yield the identical identifier.
    """
    canonical = canonical_json({"run_id": run_id, "runtime_version": runtime_version})
    return f"{_EXECUTION_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def run_trajectory_execution_content_hash(execution: RunTrajectoryExecution) -> str:
    """Canonical SHA-256 of the complete execution content, excluding content_hash."""
    payload = execution.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(run_id: str, reason: str) -> RunTrajectoryExecutionIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return RunTrajectoryExecutionIntegrityError(run_id, reason)


def build_run_trajectory_execution(
    *,
    inputs: VerifiedRunInputs,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
) -> RunTrajectoryExecution:
    """Build and fully hash the deterministic trajectory execution of one run.

    Requires the trajectory runtime version, that every plan is bound to
    the run's exact recorded strategy, and that the plan tuple matches
    the closed world catalogs exactly - one plan per transition-capable
    state model, in canonical order (this is the builder's own defense;
    the run-trajectory verifier already enforces the same selection).
    Each plan is then evaluated exactly once through the Phase 13
    kernel, with its transition references preserved exactly (including
    repetitions) and resolved only against the plan's exact verified
    world catalog. The engine's deep-frozen snapshots are converted to
    fresh detached plain JSON, every engine attempt is zipped with its
    authoritative plan reference (position, transition id, and content
    hash verified), and the result and aggregate artifacts are built and
    hashed. ``executed_at`` is the recorded RunPlan creation time - never
    the wall clock - and the seed identity is carried as recorded
    provenance only. Nothing here mutates the engine results, plans,
    models, transitions, world data, or stored inputs.
    """
    run_id = inputs.status.run_id
    if inputs.run_plan.runtime_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            inputs.run_plan.runtime_version, operation="trajectory execution"
        )

    for plan in plans:
        if plan.strategy_candidate_id != inputs.strategy.identifier:
            raise _reject(run_id, "trajectory plan strategy identity mismatch")
        if plan.strategy_content_hash != strategy_candidate_content_hash(inputs.strategy):
            raise _reject(run_id, "trajectory plan strategy content hash mismatch")

    expected_pairs = [
        (inputs.strategy.identifier, catalog.state_model.identifier) for catalog in catalogs
    ]
    actual_pairs = [(plan.strategy_candidate_id, plan.state_model_identifier) for plan in plans]
    if actual_pairs != expected_pairs:
        raise _reject(
            run_id,
            "trajectory plan collection does not match the closed world catalogs",
        )

    models_by_identifier = {
        catalog.state_model.identifier: catalog.state_model for catalog in catalogs
    }
    transitions_by_identifier = {
        transition.identifier: transition
        for catalog in catalogs
        for transition in catalog.transitions
    }

    results: list[RunStateTrajectoryResult] = []
    for plan in plans:
        state_model = models_by_identifier.get(plan.state_model_identifier)
        if state_model is None:
            raise _reject(run_id, "trajectory plan state model missing from the world")
        if (
            plan.manifest_id != state_model.manifest_id
            or plan.state_model_id != state_model.state_model_id
            or plan.state_model_content_hash != state_model.content_hash
        ):
            raise _reject(run_id, "trajectory plan state model identity mismatch")

        transitions: list[DomainStateTransition] = []
        for reference in plan.transition_references:
            transition = transitions_by_identifier.get(reference.transition_identifier)
            if transition is None:
                raise _reject(run_id, "trajectory plan references an unknown transition")
            if (
                transition.manifest_id != state_model.manifest_id
                or transition.state_model_id != state_model.state_model_id
                or transition.state_model_content_hash != state_model.content_hash
            ):
                raise _reject(run_id, "trajectory plan transition model mismatch")
            if (
                transition.transition_id != reference.transition_id
                or transition.content_hash != reference.transition_content_hash
            ):
                raise _reject(run_id, "trajectory plan transition reference mismatch")
            transitions.append(transition)

        evaluation = evaluate_trajectory(state_model, transitions)
        initial_state = state_to_plain_json(evaluation.initial_state)
        final_state = state_to_plain_json(evaluation.final_state)

        attempt_records: list[RunTrajectoryAttemptRecord] = []
        for attempt, reference in zip(evaluation.attempts, plan.transition_references, strict=True):
            if attempt.sequence_position != reference.sequence_position:
                raise _reject(run_id, "trajectory attempt position mismatch")
            if (
                attempt.transition_id != reference.transition_id
                or attempt.transition_content_hash != reference.transition_content_hash
            ):
                raise _reject(run_id, "trajectory attempt reference mismatch")
            attempt_records.append(
                RunTrajectoryAttemptRecord(
                    sequence_position=attempt.sequence_position,
                    transition_identifier=reference.transition_identifier,
                    transition_id=attempt.transition_id,
                    transition_content_hash=attempt.transition_content_hash,
                    outcome=attempt.outcome.value,
                    before_state_hash=attempt.before_state_hash,
                    after_state_hash=attempt.after_state_hash,
                )
            )

        result = RunStateTrajectoryResult(
            trajectory_plan_id=plan.identifier,
            trajectory_plan_content_hash=plan.content_hash,
            manifest_id=state_model.manifest_id,
            state_model_identifier=state_model.identifier,
            state_model_id=state_model.state_model_id,
            state_model_content_hash=state_model.content_hash,
            initial_state=initial_state,
            initial_state_hash=evaluation.initial_state_hash,
            attempts=tuple(attempt_records),
            final_state=final_state,
            final_state_hash=evaluation.final_state_hash,
            trace_hash=evaluation.trace_hash,
            content_hash=_PLACEHOLDER_HASH,
        )
        results.append(
            result.model_copy(update={"content_hash": state_trajectory_result_content_hash(result)})
        )

    execution = RunTrajectoryExecution(
        identifier=run_trajectory_execution_identifier(
            run_id=run_id, runtime_version=inputs.run_plan.runtime_version
        ),
        tenant_id=inputs.run_plan.tenant_id,
        run_id=run_id,
        campaign_id=inputs.run_plan.campaign_id,
        run_plan_id=inputs.run_plan.identifier,
        world_version_id=inputs.world.identifier,
        world_content_hash=inputs.world.content_hash,
        strategy_candidate_id=inputs.strategy.identifier,
        strategy_content_hash=strategy_candidate_content_hash(inputs.strategy),
        scenario_seed_id=inputs.seed.identifier,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        input_hash=inputs.run_plan.input_hash,
        trajectory_plan_set_hash=trajectory_plan_set_hash(plans),
        results=tuple(results),
        content_hash=_PLACEHOLDER_HASH,
        executed_at=inputs.run_plan.created_at,
    )
    return execution.model_copy(
        update={"content_hash": run_trajectory_execution_content_hash(execution)}
    )
