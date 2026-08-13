"""Pure deterministic runtime-3 realization-aware execution artifact builder (Phase 25).

Builds the immutable ``RealizationRunTrajectoryExecution`` artifact of
one realization-trajectory (3.0.0) run from **already verified
authoritative records only**: the verified run inputs (``VerifiedRunInputs``
from the existing run-input verifier, whose ``realization`` slot carries
the exactly-once reconstructed Phase 24 world realization), the exact
applicable ``StrategyTrajectoryPlan`` tuple, the exact closed
compiled-world catalogs, and the explicitly supplied realization. The
module never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input.

Each plan is evaluated **exactly once** through the Phase 13 kernel with
the model's complete realized initial state: ``derive_initial_state``
defaults plus exactly the realization overrides whose
``state_model_identifier`` matches that model (deep-copied; a model with
no matching override retains its declared defaults; duplicate or unknown
override targets fail closed). The realized initial state is fully
validated by the engine before transition zero, and its canonical hash
becomes the authoritative runtime-3 ``initial_state_hash``. Transition
references are preserved exactly, including repetitions, and resolved
only against the plan's exact closed catalog. The engine's deep-frozen
snapshots are converted to fresh detached plain JSON trees via the
engine's public ``state_to_plain_json`` helper.

Identity and hashing reuse the Phase 25 identity module (``realization_run_
trajectory_execution_identifier`` / ``..._content_hash``) and the
unchanged runtime-2 ``trajectory_plan_set_hash`` - no competing aggregate
rules exist.
"""

from __future__ import annotations

import copy

from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.input_integrity import VerifiedRunInputs
from kalhas.application.realization_errors import (
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_execution_content_hash,
    realization_run_trajectory_execution_identifier,
)
from kalhas.application.run_planner import REALIZATION_TRAJECTORY_RUNTIME_VERSION
from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash
from kalhas.application.state_transition_engine import (
    derive_initial_state,
    evaluate_trajectory,
    state_to_plain_json,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    strategy_candidate_content_hash,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world_realization import WorldRealization

_PLACEHOLDER_HASH = "0" * 64


def _reject(run_id: str, reason: str) -> RealizationRunTrajectoryExecutionIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return RealizationRunTrajectoryExecutionIntegrityError(run_id, reason)


def realized_initial_state(
    *,
    state_model: DomainStateModel,
    realization: WorldRealization,
    run_id: str,
) -> dict[str, JsonValue]:
    """The complete realized initial state of one state model.

    Model-declared default values plus exactly the realization overrides
    whose ``state_model_identifier`` matches this state model, applied by
    ``state_field_id``. Every override value is deep-copied into the
    working state, so neither the model nor the realization is ever
    mutated and no nested reference is shared. A model without a matching
    override retains its declared initial state. Duplicate matching
    overrides for one field and overrides targeting a field the model
    does not declare fail closed with the typed integrity error; the
    resulting state is validated by the engine before transition zero.
    """
    working = derive_initial_state(state_model)
    seen: set[str] = set()
    for override in realization.realized_initial_state_overrides:
        if override.state_model_identifier != state_model.identifier:
            continue
        if override.state_field_id in seen:
            raise _reject(run_id, "duplicate realized override for one state field")
        seen.add(override.state_field_id)
        if override.state_field_id not in working:
            raise _reject(
                run_id, "realized override targets a field the state model does not declare"
            )
        working[override.state_field_id] = copy.deepcopy(override.value)
    return working


def realized_state_trajectory_result_content_hash(result: RealizedStateTrajectoryResult) -> str:
    """Canonical SHA-256 of the complete result content, excluding content_hash."""
    payload = result.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def build_realization_run_trajectory_execution(
    *,
    inputs: VerifiedRunInputs,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    realization: WorldRealization,
) -> RealizationRunTrajectoryExecution:
    """Build and fully hash the deterministic realization-aware execution of one run.

    Requires the realization trajectory runtime version, that the
    explicitly supplied realization is present in the verified inputs and
    exactly equal to them, and that its ownership agrees with the
    verified records (tenant, source scenario, world identity/content
    hash, seed identity). The realization is **never reconstructed or
    resampled here**: it was reconstructed exactly once by
    ``verify_run_trajectory_inputs`` and is only consumed.

    Every plan must be bound to the run's exact recorded strategy and its
    authoritative content hash, and the plan tuple must match the closed
    world catalogs exactly - one plan per transition-capable state model,
    in canonical order. Each plan is then evaluated exactly once through
    the Phase 13 kernel from its complete realized initial state, with
    transition references preserved exactly (including repetitions) and
    resolved only against the plan's exact verified world catalog. The
    engine's deep-frozen snapshots are converted to fresh detached plain
    JSON, every engine attempt is zipped with its authoritative plan
    reference (position, transition id, logical id, and content hash
    verified), and the result and aggregate artifacts are built and
    hashed. ``executed_at`` is the recorded RunPlan creation time - never
    the wall clock. A verified world with no transition-capable catalogs
    produces an empty plans/results artifact deterministically. Nothing
    here mutates the engine results, plans, models, transitions,
    realization, world data, or stored inputs.
    """
    run_id = inputs.status.run_id
    if inputs.run_plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            inputs.run_plan.runtime_version, operation="realization trajectory execution"
        )

    if inputs.realization is None or inputs.realization != realization:
        raise _reject(run_id, "realization does not match the verified run inputs")
    if realization.tenant_id != inputs.run_plan.tenant_id:
        raise _reject(run_id, "realization tenant identity mismatch")
    if realization.scenario_id != inputs.world.source_scenario_id:
        raise _reject(run_id, "realization scenario identity mismatch")
    if realization.world_version_id != inputs.world.identifier:
        raise _reject(run_id, "realization world identity mismatch")
    if realization.world_content_hash != inputs.world.content_hash:
        raise _reject(run_id, "realization world content hash mismatch")
    if realization.scenario_seed_id != inputs.seed.identifier:
        raise _reject(run_id, "realization seed identity mismatch")

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

    results: list[RealizedStateTrajectoryResult] = []
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

        realized_initial = realized_initial_state(
            state_model=state_model,
            realization=realization,
            run_id=run_id,
        )
        evaluation = evaluate_trajectory(state_model, transitions, initial_state=realized_initial)
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

        result = RealizedStateTrajectoryResult(
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
            result.model_copy(
                update={"content_hash": realized_state_trajectory_result_content_hash(result)}
            )
        )

    execution = RealizationRunTrajectoryExecution(
        identifier=realization_run_trajectory_execution_identifier(
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
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        input_hash=inputs.run_plan.input_hash,
        trajectory_plan_set_hash=trajectory_plan_set_hash(plans),
        results=tuple(results),
        content_hash=_PLACEHOLDER_HASH,
        executed_at=inputs.run_plan.created_at,
    )
    return execution.model_copy(
        update={"content_hash": realization_run_trajectory_execution_content_hash(execution)}
    )
