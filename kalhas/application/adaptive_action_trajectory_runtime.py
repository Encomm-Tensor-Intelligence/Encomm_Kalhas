"""Pure runtime-4 selected-action trajectory application primitive (H28-S06C2A).

Applies the exact bound trajectory plans of one already-made adaptive-policy
decision to the supplied visible pre-action state collection and produces the
canonical, self-covering realized trajectory evidence for that single decision
step. The policy decision has already been made elsewhere: this module derives
no observation, evaluates no policy condition, advances no policy state,
records no activity, changes no run status, persists nothing, and builds no
adaptive-run aggregate. It is the pure per-decision application kernel between
the policy state machine (upstream) and the adaptive-run aggregate (later
slices).

The function accepts only verified immutable authority: the exact bound
:class:`AdaptivePolicy`, the exact :class:`AdaptivePolicyDecisionEvent` whose
``selected_action_id`` resolves the applied plans, the exact bound
:class:`StrategyTrajectoryPlan` tuple, the exact closed
:class:`ModelTrajectoryCatalog` set of the selected action's bound state
models, and the visible pre-action state collection (exactly one complete
state per selected bound state model). Every input is exactly typed, strictly
revalidated from its detached serialization, and cross-checked for identity
and content-hash agreement before any trajectory evaluation begins; any
violated rule raises the safe typed C1 adaptive-trajectory execution error
with a generic public message and an internal ``reason`` that names only the
violated rule class - never identifiers, hashes, state values, guards, or
transition targets. Failure is atomic: no partial result exists and no input
is ever mutated.

Each bound plan is evaluated exactly once, in the exact canonical
selected-action binding order, through the real Phase 13 kernel
(``evaluate_trajectory``) with the supplied pre-action state as the explicit
``initial_state`` - never the model's declared defaults. Transition
references are preserved exactly, including repetitions, and resolved only
against the plan's exact catalog. Every engine attempt is converted into the
exact :class:`RunTrajectoryAttemptRecord` evidence by a verified positional
zip with the authoritative plan transition sequence, and the engine's
deep-frozen snapshots become fresh detached plain JSON states with canonical
hashes, the engine's deterministic trace hash, and a self-covering result
content hash recomputed with the established helper - no competing hash
definition exists.

The module is pure application logic: no store import or write, no activity
event, no wall clock, no RNG, no UUID, no network, no provider, no adapter,
no NEXUS or LEGION dependency, no observation derivation, no policy
evaluation or state advancement, no aggregate construction, no filesystem,
and no domain-specific logic. Byte-equivalent inputs always produce exactly
equal results.
"""

from __future__ import annotations

import copy
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NoReturn

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.domain_errors import (
    InvalidTrajectoryLimitError,
    InvalidTransitionSpecificationError,
    StateValidationError,
    TrajectoryLimitExceededError,
    TransitionModelMismatchError,
)
from kalhas.application.realization_trajectory_runtime import (
    realized_state_trajectory_result_content_hash,
)
from kalhas.application.state_transition_engine import (
    TrajectoryEvaluation,
    evaluate_trajectory,
    state_to_plain_json,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    trajectory_plan_content_hash,
)
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy, BoundAdaptiveAction
from kalhas.contracts.v1.adaptive_policy_state import AdaptivePolicyDecisionEvent
from kalhas.contracts.v1.realization_trajectory_execution import RealizedStateTrajectoryResult
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel, _contains_non_finite
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryAttemptRecord
from kalhas.contracts.v1.transition import DomainStateTransition

#: The exact runtime literal this primitive binds.
RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"

_PLACEHOLDER_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class AdaptiveActionTrajectoryStepResult:
    """The frozen, slotted application-local outcome of one decision application.

    Carries exactly the canonical tuple of realized state-model trajectory
    results for the decision's selected action, in the exact canonical
    selected-action binding order. It is application-local evidence only -
    never a persisted authority, aggregate, query projection, or API surface.
    """

    trajectory_results: tuple[RealizedStateTrajectoryResult, ...]


def _reject_validation(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe validation error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionValidationError(tenant_id, run_id, reason)


def _reject_integrity(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe integrity error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionIntegrityError(tenant_id, run_id, reason)


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied artifact from its detached serialization.

    The artifact's Python payload is re-derived with the established Pydantic
    serializer-warnings suppression and the exact model class is re-validated
    with ``strict=True``, so a validator-bypassed same-type instance (wrong-
    typed or non-finite raw values, booleans where strict integers belong,
    tampered nested records) is rejected before any field of it is trusted.
    The revalidation result is discarded; the supplied artifact is never
    replaced, repaired, or mutated. Any structural, type, or validator
    failure raises ``ValueError`` for the caller to convert to the safe
    typed error.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("input failed detached strict revalidation") from None


def _preflight(
    *,
    tenant_id: str,
    run_id: str,
    policy: AdaptivePolicy,
    decision_event: AdaptivePolicyDecisionEvent,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    pre_action_states: Mapping[str, Mapping[str, JsonValue]],
) -> tuple[BoundAdaptiveAction, dict[str, ModelTrajectoryCatalog]]:
    """Verify the complete application input atomically; never repair or coerce.

    Returns the resolved selected bound action and the closed catalogs keyed
    by state-model identifier. The first violated rule raises the safe typed
    error with an internal reason; nothing is evaluated on any failure.
    """
    # Exact caller shape: scalars, exact contract types, tuple shapes, and a
    # genuine mapping collection - subclasses and foreign objects rejected.
    if not isinstance(tenant_id, str) or not isinstance(run_id, str) or not tenant_id or not run_id:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id if isinstance(tenant_id, str) else "",
            run_id if isinstance(run_id, str) else "",
            "tenant_id and run_id must be non-empty strings",
        )
    if type(policy) is not AdaptivePolicy:
        _reject_validation(tenant_id, run_id, "policy must be an exact AdaptivePolicy")
    if type(decision_event) is not AdaptivePolicyDecisionEvent:
        _reject_validation(
            tenant_id, run_id, "decision event must be an exact AdaptivePolicyDecisionEvent"
        )
    if not isinstance(plans, tuple) or not all(
        type(plan) is StrategyTrajectoryPlan for plan in plans
    ):
        _reject_validation(tenant_id, run_id, "plans must be a tuple of exact plans")
    if not isinstance(catalogs, tuple) or not all(
        type(catalog) is ModelTrajectoryCatalog for catalog in catalogs
    ):
        _reject_validation(tenant_id, run_id, "catalogs must be a tuple of exact catalogs")
    if not isinstance(pre_action_states, Mapping):
        _reject_validation(tenant_id, run_id, "pre-action state collection must be a mapping")

    # Detached strict revalidation precedes any trusted field read: a
    # validator-bypassed same-type instance is rejected here before a single
    # value is consumed. The revalidated copies are discarded.
    for artifact, model_type in (
        (policy, AdaptivePolicy),
        (decision_event, AdaptivePolicyDecisionEvent),
    ):
        try:
            _strictly_revalidate_detached(artifact, model_type)
        except ValueError:
            _reject_validation(tenant_id, run_id, "input failed detached strict revalidation")
    for plan in plans:
        try:
            _strictly_revalidate_detached(plan, StrategyTrajectoryPlan)
        except ValueError:
            _reject_validation(
                tenant_id, run_id, "trajectory plan failed detached strict revalidation"
            )
        if plan.content_hash != trajectory_plan_content_hash(plan):
            _reject_integrity(tenant_id, run_id, "trajectory plan content hash mismatch")

    # Runtime and policy/decision identity and content-hash agreement.
    if policy.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "policy must be runtime 4")
    if decision_event.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "decision event must be runtime 4")
    if decision_event.policy_id != policy.policy_id:
        _reject_integrity(tenant_id, run_id, "decision policy identity mismatch")
    if decision_event.policy_content_hash != policy.content_hash:
        _reject_integrity(tenant_id, run_id, "decision policy content hash mismatch")

    # Resolve the selected action against the policy's bound action catalog.
    selected = next(
        (
            action
            for action in policy.actions
            if action.action_id == decision_event.selected_action_id
        ),
        None,
    )
    if selected is None:
        _reject_integrity(tenant_id, run_id, "selected action is not bound by the policy")

    # The supplied plan tuple must match the selected action's trajectory-plan
    # bindings exactly: same cardinality, same canonical order, and exact
    # plan / manifest / state-model / strategy identity and content hashes.
    bindings = selected.trajectory_plan_bindings
    if len(plans) != len(bindings):
        _reject_integrity(tenant_id, run_id, "plan collection cardinality mismatch")
    for binding, plan in zip(bindings, plans, strict=True):
        if plan.identifier != binding.trajectory_plan_id:
            _reject_integrity(
                tenant_id, run_id, "plan collection is not in canonical binding order"
            )
        if plan.content_hash != binding.trajectory_plan_content_hash:
            _reject_integrity(tenant_id, run_id, "plan content hash does not match its binding")
        if plan.campaign_id != policy.campaign_id:
            _reject_integrity(tenant_id, run_id, "plan campaign mismatch")
        if plan.world_version_id != policy.world_version_id:
            _reject_integrity(tenant_id, run_id, "plan world identity mismatch")
        if plan.world_content_hash != policy.world_content_hash:
            _reject_integrity(tenant_id, run_id, "plan world content hash mismatch")
        if plan.strategy_candidate_id != selected.strategy_candidate_id:
            _reject_integrity(tenant_id, run_id, "plan strategy identity mismatch")
        if plan.strategy_content_hash != selected.strategy_content_hash:
            _reject_integrity(tenant_id, run_id, "plan strategy content hash mismatch")
        if plan.manifest_id != binding.manifest_id:
            _reject_integrity(tenant_id, run_id, "plan manifest mismatch")
        if plan.state_model_id != binding.state_model_id:
            _reject_integrity(tenant_id, run_id, "plan state model identity mismatch")
        if plan.state_model_identifier != binding.state_model_identifier:
            _reject_integrity(tenant_id, run_id, "plan state model identifier mismatch")
        if plan.state_model_content_hash != binding.state_model_content_hash:
            _reject_integrity(tenant_id, run_id, "plan state model content hash mismatch")

    # Catalogs must be canonical, unique, and exact for the selected action's
    # bound state-model set: ascending order, one per bound state model, no
    # missing or extra catalog, and exact binding authority agreement.
    expected_identifiers = sorted(binding.state_model_identifier for binding in bindings)
    observed_identifiers = [catalog.state_model.identifier for catalog in catalogs]
    if observed_identifiers != expected_identifiers:
        _reject_integrity(
            tenant_id, run_id, "catalog collection does not match the bound state-model set"
        )
    if len(observed_identifiers) != len(set(observed_identifiers)):
        _reject_integrity(tenant_id, run_id, "duplicate catalog state-model identifiers")
    catalogs_by_identifier = {catalog.state_model.identifier: catalog for catalog in catalogs}
    for binding in bindings:
        catalog = catalogs_by_identifier[binding.state_model_identifier]
        state_model = catalog.state_model
        if (
            state_model.manifest_id != binding.manifest_id
            or state_model.state_model_id != binding.state_model_id
            or state_model.content_hash != binding.state_model_content_hash
        ):
            _reject_integrity(tenant_id, run_id, "catalog state model authority mismatch")
        for transition in catalog.transitions:
            if type(transition) is not DomainStateTransition:
                _reject_validation(
                    tenant_id, run_id, "catalog must hold exact transition snapshots"
                )
            if (
                transition.manifest_id != state_model.manifest_id
                or transition.state_model_id != state_model.state_model_id
                or transition.state_model_content_hash != state_model.content_hash
            ):
                _reject_integrity(
                    tenant_id, run_id, "catalog transition does not belong to its state model"
                )

    # The pre-action collection must hold exactly one complete state per
    # selected bound state model - no missing and no extra keys - and every
    # state must be a finite JSON-compatible mapping.
    supplied_keys = set(pre_action_states.keys())
    if supplied_keys != set(expected_identifiers):
        _reject_validation(
            tenant_id,
            run_id,
            "pre-action state collection must hold exactly one state per bound state model",
        )
    for state in pre_action_states.values():
        if not isinstance(state, Mapping):
            _reject_validation(tenant_id, run_id, "pre-action state must be a mapping")
        if _contains_non_finite(dict(state)):
            _reject_validation(
                tenant_id, run_id, "pre-action state must contain only finite JSON values"
            )
    return selected, catalogs_by_identifier


def _evaluate(
    *,
    tenant_id: str,
    run_id: str,
    state_model: DomainStateModel,
    transitions: list[DomainStateTransition],
    initial_state: dict[str, JsonValue],
) -> TrajectoryEvaluation:
    """Evaluate one plan through the real kernel; convert engine failures safely.

    The engine validates the supplied initial state fully before transition
    zero and verifies every transition's ownership and specification before
    any attempt; no partial trajectory can exist on any failure.
    """
    try:
        return evaluate_trajectory(state_model, transitions, initial_state=initial_state)
    except StateValidationError:
        _reject_validation(tenant_id, run_id, "pre-action state failed model validation")
    except (
        TransitionModelMismatchError,
        InvalidTransitionSpecificationError,
        TrajectoryLimitExceededError,
        InvalidTrajectoryLimitError,
    ):
        _reject_integrity(tenant_id, run_id, "trajectory evaluation failed integrity verification")


def _build_result(
    *,
    tenant_id: str,
    run_id: str,
    plan: StrategyTrajectoryPlan,
    state_model: DomainStateModel,
    evaluation: TrajectoryEvaluation,
) -> RealizedStateTrajectoryResult:
    """Convert one engine evaluation into canonical self-covering evidence.

    The engine's deep-frozen snapshots become fresh detached plain JSON
    trees; every attempt is zipped positionally with the authoritative plan
    transition reference and verified; the result content hash is recomputed
    with the established helper. Any unexpected record-construction failure
    is converted to the safe typed error with no partial result.
    """
    initial_state = state_to_plain_json(evaluation.initial_state)
    final_state = state_to_plain_json(evaluation.final_state)
    attempt_records: list[RunTrajectoryAttemptRecord] = []
    for attempt, reference in zip(evaluation.attempts, plan.transition_references, strict=True):
        if attempt.sequence_position != reference.sequence_position:
            _reject_integrity(tenant_id, run_id, "trajectory attempt position mismatch")
        if (
            attempt.transition_id != reference.transition_id
            or attempt.transition_content_hash != reference.transition_content_hash
        ):
            _reject_integrity(tenant_id, run_id, "trajectory attempt reference mismatch")
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
    try:
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
    except (ValidationError, TypeError, AttributeError):
        _reject_integrity(tenant_id, run_id, "trajectory result failed strict integrity")
    return result.model_copy(
        update={"content_hash": realized_state_trajectory_result_content_hash(result)}
    )


def apply_selected_adaptive_action(
    *,
    tenant_id: str,
    run_id: str,
    policy: AdaptivePolicy,
    decision_event: AdaptivePolicyDecisionEvent,
    plans: tuple[StrategyTrajectoryPlan, ...],
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    pre_action_states: Mapping[str, Mapping[str, JsonValue]],
) -> AdaptiveActionTrajectoryStepResult:
    """Apply the selected action's exact bound trajectory plans once, purely.

    Resolves ``decision_event.selected_action_id`` against ``policy.actions``,
    requires the supplied ``plans`` and ``catalogs`` to match the selected
    action's bindings and the bound state-model set exactly, requires
    ``pre_action_states`` to hold exactly one complete state per bound state
    model, and evaluates every bound plan exactly once through the real
    ``evaluate_trajectory`` kernel with the supplied pre-action state as the
    explicit ``initial_state``. Returns the frozen application-local result
    in the exact canonical selected-action binding order.

    The complete preflight runs before any trajectory evaluation; any
    violated rule raises the safe typed C1 adaptive-trajectory execution
    error with a generic public message, no partial result, and no input
    mutation. Byte-equivalent inputs always produce exactly equal results.
    """
    try:
        selected, catalogs_by_identifier = _preflight(
            tenant_id=tenant_id,
            run_id=run_id,
            policy=policy,
            decision_event=decision_event,
            plans=plans,
            catalogs=catalogs,
            pre_action_states=pre_action_states,
        )
        results: list[RealizedStateTrajectoryResult] = []
        for binding, plan in zip(selected.trajectory_plan_bindings, plans, strict=True):
            catalog = catalogs_by_identifier[binding.state_model_identifier]
            state_model = catalog.state_model
            available = {transition.identifier: transition for transition in catalog.transitions}
            transitions: list[DomainStateTransition] = []
            for reference in plan.transition_references:
                transition = available.get(reference.transition_identifier)
                if transition is None:
                    _reject_integrity(
                        tenant_id, run_id, "trajectory plan references an unknown transition"
                    )
                if (
                    transition.transition_id != reference.transition_id
                    or transition.content_hash != reference.transition_content_hash
                ):
                    _reject_integrity(
                        tenant_id, run_id, "trajectory plan transition reference mismatch"
                    )
                transitions.append(transition)
            initial_state = copy.deepcopy(dict(pre_action_states[binding.state_model_identifier]))
            evaluation = _evaluate(
                tenant_id=tenant_id,
                run_id=run_id,
                state_model=state_model,
                transitions=transitions,
                initial_state=initial_state,
            )
            results.append(
                _build_result(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    plan=plan,
                    state_model=state_model,
                    evaluation=evaluation,
                )
            )
    except (AttributeError, TypeError, KeyError, IndexError, ValueError):
        # A validator-bypassed same-type instance can carry raw dumped
        # dictionaries where nested contracts belong; touching its fields
        # raises bare AttributeError/TypeError/KeyError. Exactly like the
        # established store boundary, those raw failures are converted to
        # the safe typed validation error and never escape this module -
        # typed domain errors are not in this tuple and propagate unchanged.
        _reject_validation(tenant_id, run_id, "input violates its contract")
    return AdaptiveActionTrajectoryStepResult(trajectory_results=tuple(results))


__all__ = [
    "RUNTIME_VERSION",
    "AdaptiveActionTrajectoryStepResult",
    "apply_selected_adaptive_action",
]
