"""Pure deterministic state-transition evaluation kernel.

This module is a **focused, domain-neutral application-layer engine**: it
evaluates an explicitly supplied, ordered sequence of already-declared
``DomainStateTransition`` specifications against one immutable
``DomainStateModel`` definition, producing **deep-immutable result
records**: the initial and final state snapshots are recursively frozen
(nested mappings and arrays included) and share no mutable references
with the model, the transitions, or the engine's working state. It is
deliberately **not** a simulation scheduler, runtime, or decision
engine:

- It derives the initial state **only** from
  ``DomainStateModel.state_fields[].initial_value``.
- It evaluates transitions **only in the caller-provided order**; it
  never chooses, reorders, searches for, prioritizes, or loops
  transitions, and it never inspects strategy policies or invokes domain
  packs.
- A guard is evaluated as **exact canonical equality** over its declared
  ``guard_values``; a target is applied as a copy-on-write patch of only
  its declared ``target_values``. Nothing here mutates the input state,
  model, or transitions, and nothing here produces outcomes, evidence,
  recommendations, briefs, probabilities, hidden reasoning, or
  real-world actions.
- Result states are returned as **deep-frozen immutable snapshots**:
  every nested mapping is a read-only ``MappingProxyType`` view and
  every nested array is an immutable ``_FrozenList``; no result snapshot
  shares a mutable nested reference with the model's declared initial
  values, any transition's guard/target values, or the engine's internal
  working state.
- Every transition must belong to the supplied state model (tenant,
  scenario, binding, pack, manifest, and state-model ownership identity
  plus authoritative content hashes), the current
  state is validated against the model's field definitions before every
  evaluation step, and the applied target state is re-validated
  afterwards - enforcing all Phase 11 value-kind, allowed-values, and
  nested finite-JSON rules.
- Every transition's declared guard/target specification is validated
  up front, before any evaluation: non-empty ``target_values``, every
  guard/target key must exist in the state model, every guard/target
  value must exactly match its field's ``StateValueKind`` (including
  nested finite-JSON), and ``allowed_values`` are enforced for guards
  and targets alike - so an invalid specification can never be silently
  recorded as ``guard_not_satisfied`` and an invalid target can never
  evade validation merely because its guard does not match.
- An explicitly requested trajectory is bounded to a safe fixed maximum
  number of transition attempts (default 1000, caller-overridable) with
  a typed error when exceeded.

This module is application-layer only: no HTTP routes, no store methods,
no operational activity events, no Colony behavior, no world compiler
changes, and no campaign/run/replay integration. It contains no
callbacks, scripts, expressions, formulas, evaluators, code references,
providers, imports of executable mechanisms, or dynamic loading.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import cast, overload

from kalhas.application.domain_errors import (
    InvalidTrajectoryLimitError,
    InvalidTransitionSpecificationError,
    StateValidationError,
    TrajectoryLimitExceededError,
    TransitionModelMismatchError,
)
from kalhas.application.domain_state_model_service import state_model_content_hash
from kalhas.application.domain_state_transition_service import transition_content_hash
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    _canonical_value_text,
    _value_matches_kind,
)
from kalhas.contracts.v1.transition import DomainStateTransition

DEFAULT_MAX_TRANSITION_ATTEMPTS = 1000

State = Mapping[str, JsonValue]


class _FrozenList(Sequence[object]):
    """Immutable JSON-array value with list-compatible value equality.

    A deep-frozen snapshot array: read-only (index assignment and every
    mutator raise ``TypeError``/``AttributeError``), but compares equal
    to the plain list (or tuple) with the same elements, so frozen
    result snapshots stay value-equal to their ordinary JSON
    equivalents. ``canonical_json`` cannot serialize it directly - the
    engine normalizes frozen values back to plain lists via
    ``_to_plain_value`` before any serialization.
    """

    __slots__ = ("_items",)

    def __init__(self, items: Iterable[FrozenJsonValue]) -> None:
        self._items: tuple[FrozenJsonValue, ...] = tuple(items)

    @overload
    def __getitem__(self, index: int) -> FrozenJsonValue: ...

    @overload
    def __getitem__(self, index: slice) -> _FrozenList: ...

    def __getitem__(self, index: int | slice) -> FrozenJsonValue | _FrozenList:
        if isinstance(index, slice):
            return _FrozenList(self._items[index])
        return self._items[index]

    def __len__(self) -> int:
        return len(self._items)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence) or isinstance(other, (str, bytes, bytearray)):
            return NotImplemented
        return len(self) == len(other) and all(a == b for a, b in zip(self, other, strict=False))


type FrozenJsonValue = str | int | float | bool | None | _FrozenList | Mapping[str, FrozenJsonValue]
FrozenState = Mapping[str, FrozenJsonValue]
StateLike = Mapping[str, object]


def _freeze_value(value: JsonValue) -> FrozenJsonValue:
    """Deep-freeze one JSON-compatible value into an immutable snapshot value.

    Mappings become read-only ``MappingProxyType`` views and arrays
    become immutable ``_FrozenList`` instances, recursively; scalar
    values (already immutable) pass through untouched. The returned
    structure shares no mutable nested reference with the input.
    """
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_freeze_value(item) for item in value)
    return value


def _freeze_state(state: Mapping[str, JsonValue]) -> FrozenState:
    """Deep-freeze a whole state mapping into an immutable result snapshot."""
    return MappingProxyType({key: _freeze_value(value) for key, value in state.items()})


def _to_plain_value(value: object) -> JsonValue:
    """Normalize one value back to plain JSON-compatible form.

    The single internal conversion helper shared by state hashing, guard
    comparison, state validation, and canonical serialization: it
    accepts both ordinary JSON-compatible values and deep-frozen
    snapshot values (mappings and arrays at any depth) and always
    returns ordinary dicts, lists, and scalars.
    """
    if isinstance(value, Mapping):
        return {key: _to_plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, _FrozenList, tuple)):
        return [_to_plain_value(item) for item in value]
    return cast(JsonValue, value)


def _plain_state(state: StateLike) -> dict[str, JsonValue]:
    """Normalize a whole state mapping (plain or frozen) to plain JSON form."""
    return {key: _to_plain_value(value) for key, value in state.items()}


def state_to_plain_json(state: StateLike) -> dict[str, JsonValue]:
    """Convert a state mapping to a fresh, detached, plain JSON mapping.

    Accepts both ordinary JSON-compatible state mappings and the engine's
    deep-frozen result snapshots (nested read-only mapping views and
    immutable ``_FrozenList`` arrays at any depth) and returns a fresh
    tree of ordinary dicts and lists whose mutable nodes share **no
    reference** with the input: nested containers are rebuilt, and only
    immutable scalars pass through. This is the public conversion helper
    for callers that must persist or embed an evaluated state (for
    example the run trajectory execution builder) without ever mutating
    the engine's snapshots or the model's declared values.
    """
    return _plain_state(state)


def state_hash(state: StateLike) -> str:
    """Canonical SHA-256 of a state mapping.

    Accepts both ordinary JSON-compatible state mappings and deep-frozen
    engine snapshots; frozen values are normalized to their plain JSON
    form before canonical serialization. Deterministic: the canonical
    serialization sorts keys and strips all insignificant whitespace, so
    semantically identical states with different insertion order always
    produce the same lowercase 64-character digest.
    """
    return sha256_hex(canonical_json(_plain_state(state)))


def _field_identifier(field: DomainStateFieldDefinition) -> str:
    """Ordering key for state fields: the field identifier."""
    return field.identifier


def derive_initial_state(state_model: DomainStateModel) -> dict[str, JsonValue]:
    """Derive the initial state solely from the model's declared initial values.

    The returned mapping is a fresh dict keyed by field identifier in
    canonical (identifier) order; nothing else contributes to it. Every
    nested value is deep-copied, so callers can never mutate the model's
    declared initial values through the returned mapping. This is the
    engine's mutable working-state form - the immutable *result*
    snapshots are deep-frozen separately by the engine.
    """
    ordered_fields = sorted(state_model.state_fields, key=_field_identifier)
    return {field.identifier: copy.deepcopy(field.initial_value) for field in ordered_fields}


class TransitionOutcome(StrEnum):
    """The deterministic result of one transition attempt."""

    APPLIED = "applied"
    GUARD_NOT_SATISFIED = "guard_not_satisfied"


@dataclass(frozen=True)
class TransitionAttempt:
    """One deterministic attempt record within an evaluated trajectory.

    ``before_state_hash`` equals ``after_state_hash`` exactly when the
    guard was not satisfied (the state was returned unchanged). The
    record carries no human-language explanation, no hidden reasoning,
    and no guard or target values.
    """

    sequence_position: int
    transition_id: str
    transition_content_hash: str
    outcome: TransitionOutcome
    before_state_hash: str
    after_state_hash: str


@dataclass(frozen=True)
class TrajectoryEvaluation:
    """The immutable result of evaluating an explicitly supplied sequence.

    ``initial_state`` and ``final_state`` are **deep-frozen immutable
    snapshots**, not ordinary dicts: every nested mapping is a read-only
    ``types.MappingProxyType`` view and every nested array is an
    immutable ``_FrozenList``. Assigning to a snapshot mapping or array
    raises ``TypeError`` (list-style mutators such as ``append`` raise
    ``AttributeError``), and no snapshot shares a mutable nested
    reference with the model's declared initial values, any transition's
    guard/target values, or the engine's internal working state - the
    engine never mutates the supplied model or transitions, and callers
    can never mutate the snapshots. The snapshots compare equal to their
    plain JSON equivalents and hash/validate identically. ``trace_hash``
    is the SHA-256 digest of the canonical serialization of the ordered
    attempt records, so the whole evaluation is digestible in one
    deterministic value.
    """

    state_model_id: str
    initial_state: FrozenState
    initial_state_hash: str
    attempts: tuple[TransitionAttempt, ...]
    final_state: FrozenState
    final_state_hash: str
    trace_hash: str


def validate_state(state: StateLike, state_model: DomainStateModel) -> None:
    """Validate a state mapping against the model's field definitions.

    Raises :class:`StateValidationError` when the state carries an
    unknown key, is missing a required field, holds a value that does not
    exactly match the field's declared ``StateValueKind`` (booleans are
    never accepted as integers or numbers, and non-finite floats are
    rejected everywhere - including arbitrarily nested inside ``json``
    values), or holds a value that is not canonically among the field's
    declared ``allowed_values``. The mapping is only read, never
    mutated: both ordinary JSON-compatible mappings and deep-frozen
    engine snapshots are accepted (frozen values are normalized to their
    plain JSON form first).
    """
    plain_state = _plain_state(state)
    fields_by_id = {field.identifier: field for field in state_model.state_fields}
    for field_id in fields_by_id:
        if field_id not in plain_state:
            raise StateValidationError(
                state_model.state_model_id,
                reason=f"missing required state field {field_id!r}",
            )
    for key, value in plain_state.items():
        definition = fields_by_id.get(key)
        if definition is None:
            raise StateValidationError(
                state_model.state_model_id,
                reason=f"unknown state field {key!r}",
            )
        if not _value_matches_kind(value, definition.value_kind):
            raise StateValidationError(
                state_model.state_model_id,
                reason=(
                    f"state value for field {key!r} does not match its declared "
                    f"value kind {definition.value_kind.value!r}"
                ),
            )
        if definition.allowed_values:
            canonical = _canonical_value_text(value)
            allowed = [
                _canonical_value_text(allowed_value) for allowed_value in definition.allowed_values
            ]
            if canonical not in allowed:
                raise StateValidationError(
                    state_model.state_model_id,
                    reason=(
                        f"state value for field {key!r} is not among its declared allowed_values"
                    ),
                )


def _guard_matches(state: StateLike, transition: DomainStateTransition) -> bool:
    """Evaluate a guard as exact canonical equality over its declared values.

    Every declared guard value must canonically equal the current state
    value of the same field (canonical JSON text equality: keys sorted,
    no insignificant whitespace; ``1`` and ``1.0`` are canonically
    distinct). Both plain and deep-frozen state values are accepted -
    values are normalized to their plain JSON form before the canonical
    comparison. The guard is never evaluated for truthiness - only for
    exact declared equality - and nothing is executed or derived.
    """
    for key, value in transition.guard_values.items():
        if _canonical_value_text(_to_plain_value(state.get(key))) != _canonical_value_text(
            _to_plain_value(value)
        ):
            return False
    return True


def _apply_target(state: State, transition: DomainStateTransition) -> dict[str, JsonValue]:
    """Copy-on-write application of only the transition's declared targets.

    Returns a new mapping: the current state copied, then every declared
    target key overwritten with its declared value. Fields not mentioned
    in ``target_values`` keep their current values; the input mapping is
    never mutated.
    """
    new_state = dict(state)
    for key, value in transition.target_values.items():
        new_state[key] = value
    return new_state


def _verify_transition_belongs(
    state_model: DomainStateModel,
    transition: DomainStateTransition,
) -> None:
    """Verify a transition belongs to the supplied model (identity + hashes).

    Checks the copied ownership/identity fields - tenant, scenario,
    binding, pack id, pack version, manifest, and state-model ids must
    exactly equal the model's - and the authoritative content hashes:
    the transition's manifest content hash must equal the model's
    manifest content hash, its state-model content hash must equal the
    model's authoritative content hash, and its own content hash must
    match its recomputed canonical digest. Any mismatch - including
    sequences whose members disagree about which model they belong to -
    raises a safe typed :class:`TransitionModelMismatchError` with a
    generic public message and an internal ``reason``.
    """
    if transition.tenant_id != state_model.tenant_id:
        reason = "tenant identity mismatch"
    elif transition.scenario_id != state_model.scenario_id:
        reason = "scenario identity mismatch"
    elif transition.binding_id != state_model.binding_id:
        reason = "binding identity mismatch"
    elif transition.pack_id != state_model.pack_id:
        reason = "pack identity mismatch"
    elif transition.pack_version != state_model.pack_version:
        reason = "pack version mismatch"
    elif transition.manifest_id != state_model.manifest_id:
        reason = "manifest identity mismatch"
    elif transition.state_model_id != state_model.state_model_id:
        reason = "state model identity mismatch"
    elif transition.manifest_content_hash != state_model.manifest_content_hash:
        reason = "manifest content hash mismatch"
    elif transition.state_model_content_hash != state_model.content_hash:
        reason = "state model content hash mismatch"
    elif transition.content_hash != transition_content_hash(transition):
        reason = "transition content hash mismatch"
    else:
        return
    raise TransitionModelMismatchError(
        state_model.state_model_id, transition.transition_id, reason=reason
    )


def _validate_transition_specification(
    state_model: DomainStateModel,
    transition: DomainStateTransition,
) -> None:
    """Validate one transition's declared guard/target specification.

    Runs after ownership/hash verification and before any trajectory
    evaluation. The transition must declare a non-empty
    ``target_values`` mapping; every guard and target key must identify
    an existing state-model field; every guard and target value must
    exactly match that field's ``StateValueKind`` (booleans are never
    accepted as integers or numbers, and non-finite floats are rejected
    everywhere - including arbitrarily nested inside ``json`` values);
    and - when the field declares ``allowed_values`` - the value must be
    canonically among them. Any violation raises a safe typed
    :class:`InvalidTransitionSpecificationError` whose public message
    stays generic and whose internal ``reason`` names only field
    identifiers and rule names, never state values or hashes. This
    guarantees a malformed specification can never be silently recorded
    as a ``guard_not_satisfied`` outcome, and an invalid target can
    never evade validation merely because its guard does not match.
    """
    if not transition.target_values:
        raise InvalidTransitionSpecificationError(
            transition.transition_id,
            reason="target_values must be non-empty",
        )
    fields_by_id = {field.identifier: field for field in state_model.state_fields}
    for mapping_name, mapping in (
        ("guard", transition.guard_values),
        ("target", transition.target_values),
    ):
        for key, value in mapping.items():
            definition = fields_by_id.get(key)
            if definition is None:
                raise InvalidTransitionSpecificationError(
                    transition.transition_id,
                    reason=f"{mapping_name} field {key!r} does not exist in the state model",
                )
            if not _value_matches_kind(value, definition.value_kind):
                raise InvalidTransitionSpecificationError(
                    transition.transition_id,
                    reason=(
                        f"{mapping_name} value for field {key!r} does not match its "
                        f"declared value kind {definition.value_kind.value!r}"
                    ),
                )
            if definition.allowed_values:
                canonical = _canonical_value_text(value)
                allowed = [
                    _canonical_value_text(allowed_value)
                    for allowed_value in definition.allowed_values
                ]
                if canonical not in allowed:
                    raise InvalidTransitionSpecificationError(
                        transition.transition_id,
                        reason=(
                            f"{mapping_name} value for field {key!r} is not among its "
                            "declared allowed_values"
                        ),
                    )


def _attempt_record(attempt: TransitionAttempt) -> dict[str, object]:
    """Canonical serializable record of one attempt (for the trace hash)."""
    return {
        "sequence_position": attempt.sequence_position,
        "transition_id": attempt.transition_id,
        "transition_content_hash": attempt.transition_content_hash,
        "outcome": attempt.outcome.value,
        "before_state_hash": attempt.before_state_hash,
        "after_state_hash": attempt.after_state_hash,
    }


def validate_transition_catalog(
    state_model: DomainStateModel,
    transitions: Sequence[DomainStateTransition],
) -> None:
    """Validate a transition catalog against its state model, read-only.

    Pure and read-only pre-validation of an *available* transition
    catalog for one state model, reusable by planning and evaluation
    alike: the state model's own content hash must match its
    deterministic digest; every transition must belong to the supplied
    model (ownership/identity fields plus authoritative content hashes);
    and every transition's declared guard/target specification must be
    valid against the model's field definitions (non-empty targets,
    existing field keys, exact value kinds, allowed values, no nested
    non-finite values). It performs **no state derivation, no guard
    evaluation, no target application, and no trajectory result**, and
    it imposes **no catalog-size execution limit** (that stays the
    caller's concern - ``evaluate_trajectory`` bounds its sequences with
    ``max_attempts``).

    The validation order is deterministic: model content hash first,
    then every transition's ownership/hash verification, then every
    transition's specification validation.
    """
    if state_model.content_hash != state_model_content_hash(state_model):
        raise TransitionModelMismatchError(
            state_model.state_model_id, "", reason="state model content hash mismatch"
        )
    for transition in transitions:
        _verify_transition_belongs(state_model, transition)
    for transition in transitions:
        _validate_transition_specification(state_model, transition)


def evaluate_trajectory(
    state_model: DomainStateModel,
    transitions: Sequence[DomainStateTransition],
    *,
    max_attempts: int = DEFAULT_MAX_TRANSITION_ATTEMPTS,
) -> TrajectoryEvaluation:
    """Evaluate the supplied transition sequence strictly in caller order.

    The initial state is derived solely from the model's declared
    initial values and validated against the model. Every transition is
    verified to belong to the supplied model (ownership/identity fields
    - tenant, scenario, binding, pack id, pack version, manifest, and
    state-model - plus the authoritative content hashes) **before any
    evaluation happens**, and every transition's declared guard/target
    specification is then validated up front against the model's field
    definitions (non-empty targets, existing field keys, exact value
    kinds, allowed values, no nested non-finite values) - so a
    malformed or mixed-model sequence, or a semantically invalid
    specification, is rejected with a typed error before any attempt and
    never produces a partial trajectory. An empty sequence is valid and
    returns the initial state unchanged.

    Each attempt validates the current state against the model's field
    definitions, evaluates the guard as exact canonical equality, and -
    when it matches - returns a new state with only the declared target
    values applied, re-validating the applied state. A non-matching
    guard returns the unchanged state. The engine never chooses,
    reorders, searches for, prioritizes, or loops transitions, never
    inspects strategy policies, never invokes domain packs, and never
    mutates any input.

    The returned :class:`TrajectoryEvaluation` carries deep-frozen
    immutable snapshots of the initial and final states (nested mappings
    and arrays included) that share no mutable references with the
    model, the transitions, or the engine's internal working state.

    ``max_attempts`` bounds the explicitly requested trajectory: a
    sequence longer than the bound raises
    :class:`TrajectoryLimitExceededError` before evaluation, and a
    non-positive bound raises :class:`InvalidTrajectoryLimitError`.
    """
    if max_attempts < 1:
        raise InvalidTrajectoryLimitError(max_attempts)
    if len(transitions) > max_attempts:
        raise TrajectoryLimitExceededError(len(transitions), max_attempts)
    validate_transition_catalog(state_model, transitions)

    initial_state = derive_initial_state(state_model)
    validate_state(initial_state, state_model)
    initial_state_hash = state_hash(initial_state)
    state: dict[str, JsonValue] = initial_state

    attempts: list[TransitionAttempt] = []
    for position, transition in enumerate(transitions):
        validate_state(state, state_model)
        before_state_hash = state_hash(state)
        if _guard_matches(state, transition):
            state = _apply_target(state, transition)
            validate_state(state, state_model)
            outcome = TransitionOutcome.APPLIED
        else:
            outcome = TransitionOutcome.GUARD_NOT_SATISFIED
        attempts.append(
            TransitionAttempt(
                sequence_position=position,
                transition_id=transition.transition_id,
                transition_content_hash=transition.content_hash,
                outcome=outcome,
                before_state_hash=before_state_hash,
                after_state_hash=state_hash(state),
            )
        )

    ordered_attempts = tuple(attempts)
    trace_hash = sha256_hex(
        canonical_json([_attempt_record(attempt) for attempt in ordered_attempts])
    )
    return TrajectoryEvaluation(
        state_model_id=state_model.state_model_id,
        initial_state=_freeze_state(initial_state),
        initial_state_hash=initial_state_hash,
        attempts=ordered_attempts,
        final_state=_freeze_state(state),
        final_state_hash=state_hash(state),
        trace_hash=trace_hash,
    )
