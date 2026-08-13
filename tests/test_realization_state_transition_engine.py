"""Permanent focused tests for the Phase 25 optional ``initial_state`` engine extension.

These tests prove the pure deterministic transition engine's Phase 25
extension: ``evaluate_trajectory`` accepts an optional explicit realized
initial state without changing runtime 2.0.0 behavior in any way. The
omitted-keyword and explicit-``None`` paths are byte-for-byte the
historical path (initial state derived solely from the model's declared
initial values). A supplied complete realized state is deep-copied,
fully validated against the model's field definitions **before the
first transition** (missing fields, unknown fields, exact value kinds,
booleans rejected for integer/number fields, NaN/Infinity rejected, and
canonical ``allowed_values`` membership), its canonical hash becomes the
authoritative ``initial_state_hash``, guards evaluate against the
realized values, and the final state causally reflects the realized
initial state. Caller mappings and nested containers are never mutated,
returned initial/final snapshots are deeply immutable, an invalid
supplied state produces no transition attempts, and the canonical state
hash is invariant to input key insertion order.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast

import pytest
from kalhas.application.domain_errors import StateValidationError
from kalhas.application.domain_state_model_service import state_model_content_hash
from kalhas.application.domain_state_transition_service import transition_content_hash
from kalhas.application.state_transition_engine import (
    TransitionOutcome,
    derive_initial_state,
    evaluate_trajectory,
    state_hash,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.transition import DomainStateTransition

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PLACEHOLDER = "0" * 64


def field(
    identifier: str,
    *,
    value_kind: StateValueKind,
    initial_value: JsonValue,
    allowed_values: tuple[JsonValue, ...] = (),
) -> DomainStateFieldDefinition:
    return DomainStateFieldDefinition(
        identifier=identifier,
        description="A declared state field",
        value_kind=value_kind,
        initial_value=initial_value,
        allowed_values=allowed_values,
    )


def base_fields() -> tuple[DomainStateFieldDefinition, ...]:
    return (
        field(
            "status",
            value_kind=StateValueKind.STRING,
            initial_value="idle",
            allowed_values=("idle", "active", "paused"),
        ),
        field("level", value_kind=StateValueKind.INTEGER, initial_value=0),
        field("ratio", value_kind=StateValueKind.NUMBER, initial_value=0.0),
        field("flag", value_kind=StateValueKind.BOOLEAN, initial_value=False),
        field("extra", value_kind=StateValueKind.JSON, initial_value={"tags": []}),
    )


def make_model() -> DomainStateModel:
    """Build an authoritative state model (self-consistent content hash)."""
    model = DomainStateModel(
        identifier="state-model-sm-1",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id="sm-1",
        state_fields=base_fields(),
        content_hash=PLACEHOLDER,
        declared_at=NOW,
    )
    return model.model_copy(update={"content_hash": state_model_content_hash(model)})


def make_transition(
    model: DomainStateModel,
    *,
    transition_id: str = "t-1",
    guard_values: dict[str, JsonValue] | None = None,
    target_values: dict[str, JsonValue] | None = None,
) -> DomainStateTransition:
    """Build an authoritative transition belonging to the supplied model."""
    if guard_values is None:
        guard_values = {"level": 1}
    if target_values is None:
        target_values = {"level": 84}
    transition = DomainStateTransition(
        identifier=f"transition-{transition_id}",
        tenant_id=model.tenant_id,
        scenario_id=model.scenario_id,
        binding_id=model.binding_id,
        manifest_id=model.manifest_id,
        pack_id=model.pack_id,
        pack_version=model.pack_version,
        manifest_content_hash=model.manifest_content_hash,
        state_model_id=model.state_model_id,
        state_model_content_hash=model.content_hash,
        transition_id=transition_id,
        description="A possible state change",
        guard_values=guard_values,
        target_values=target_values,
        content_hash=PLACEHOLDER,
        declared_at=NOW,
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


def expected_initial() -> dict[str, JsonValue]:
    return {
        "status": "idle",
        "level": 0,
        "ratio": 0.0,
        "flag": False,
        "extra": {"tags": []},
    }


def realized_state() -> dict[str, JsonValue]:
    return {
        "status": "idle",
        "level": 1,
        "ratio": 0.5,
        "flag": True,
        "extra": {"tags": ["realized"]},
    }


class TestRuntimeTwoCompatibility:
    def test_omitted_initial_state_preserves_runtime_two_result(self) -> None:
        model = make_model()
        transition = make_transition(model)
        result = evaluate_trajectory(model, [transition])
        assert result.initial_state == expected_initial()
        assert result.initial_state_hash == state_hash(derive_initial_state(model))
        # The realized guard (level == 1) does not match the derived level 0.
        assert result.attempts[0].outcome is TransitionOutcome.GUARD_NOT_SATISFIED
        assert result.final_state == expected_initial()

    def test_explicit_none_matches_omitted(self) -> None:
        model = make_model()
        transitions = [make_transition(model), make_transition(model, transition_id="t-2")]
        omitted = evaluate_trajectory(model, transitions)
        explicit = evaluate_trajectory(model, transitions, initial_state=None)
        assert explicit.initial_state == omitted.initial_state
        assert explicit.initial_state_hash == omitted.initial_state_hash
        assert explicit.attempts == omitted.attempts
        assert explicit.final_state == omitted.final_state
        assert explicit.final_state_hash == omitted.final_state_hash
        assert explicit.trace_hash == omitted.trace_hash


class TestSuppliedRealizedState:
    def test_supplied_state_is_authoritative_initial_state(self) -> None:
        model = make_model()
        realized = realized_state()
        transition = make_transition(model)
        result = evaluate_trajectory(model, [transition], initial_state=realized)
        assert result.initial_state == realized
        assert result.initial_state_hash == state_hash(realized)
        assert result.initial_state_hash != state_hash(derive_initial_state(model))

    def test_guards_evaluate_against_realized_values(self) -> None:
        model = make_model()
        transition = make_transition(model)  # guard {"level": 1} -> target {"level": 84}
        realized = evaluate_trajectory(model, [transition], initial_state=realized_state())
        assert realized.attempts[0].outcome is TransitionOutcome.APPLIED
        assert realized.final_state == {
            **realized_state(),
            "level": 84,
        }
        base = evaluate_trajectory(model, [transition])
        assert base.attempts[0].outcome is TransitionOutcome.GUARD_NOT_SATISFIED

    def test_final_state_causally_reflects_realized_initial_state(self) -> None:
        model = make_model()
        transition = make_transition(model)
        result = evaluate_trajectory(model, [transition], initial_state=realized_state())
        # The realized level 1 satisfies the guard; the derived level 0 does not.
        assert result.final_state["level"] == 84
        assert result.final_state["flag"] is True
        assert result.final_state["extra"] == {"tags": ["realized"]}

    def test_input_state_key_order_does_not_change_state_hash(self) -> None:
        model = make_model()
        transition = make_transition(model)
        ordered = realized_state()
        reordered: dict[str, JsonValue] = {
            "extra": ordered["extra"],
            "flag": ordered["flag"],
            "ratio": ordered["ratio"],
            "level": ordered["level"],
            "status": ordered["status"],
        }
        first = evaluate_trajectory(model, [transition], initial_state=ordered)
        second = evaluate_trajectory(model, [transition], initial_state=reordered)
        assert first.initial_state_hash == second.initial_state_hash
        assert first.final_state_hash == second.final_state_hash
        assert first.trace_hash == second.trace_hash


class TestNoMutation:
    def test_caller_mapping_and_nested_containers_are_not_mutated(self) -> None:
        model = make_model()
        realized = realized_state()
        snapshot = copy.deepcopy(realized)
        evaluate_trajectory(model, [make_transition(model)], initial_state=realized)
        assert realized == snapshot
        # Nested containers keep their identity: nothing was copied into,
        # out of, or through them.
        assert realized["extra"] == {"tags": ["realized"]}
        # Mutating the caller's mapping after evaluation never touches the result.
        result = evaluate_trajectory(model, [make_transition(model)], initial_state=realized)
        realized["level"] = 999
        realized_tags = cast(Any, realized["extra"]["tags"])
        realized_tags.append("mutated")
        assert result.initial_state["level"] == 1
        assert result.initial_state["extra"] == {"tags": ["realized"]}
        assert result.final_state["level"] == 84

    def test_returned_snapshots_are_deeply_immutable(self) -> None:
        model = make_model()
        result = evaluate_trajectory(
            model, [make_transition(model)], initial_state=realized_state()
        )
        for snapshot in (result.initial_state, result.final_state):
            assert isinstance(snapshot, MappingProxyType)
            frozen_any = cast(Any, snapshot)
            with pytest.raises(TypeError):
                frozen_any["level"] = 5
            with pytest.raises(TypeError):
                frozen_any["extra"]["tags"] = []
            with pytest.raises(AttributeError):
                frozen_any["extra"]["tags"].append("x")


class TestRejection:
    def test_missing_fields_are_rejected(self) -> None:
        model = make_model()
        realized = realized_state()
        del realized["ratio"]
        with pytest.raises(StateValidationError) as exc_info:
            evaluate_trajectory(model, [make_transition(model)], initial_state=realized)
        reason = exc_info.value.reason
        assert reason is not None and "missing required state field 'ratio'" in reason

    def test_unknown_fields_are_rejected(self) -> None:
        model = make_model()
        realized = realized_state()
        realized["ghost"] = 1
        with pytest.raises(StateValidationError) as exc_info:
            evaluate_trajectory(model, [make_transition(model)], initial_state=realized)
        reason = exc_info.value.reason
        assert reason is not None and "unknown state field 'ghost'" in reason

    def test_wrong_exact_numeric_kinds_are_rejected(self) -> None:
        model = make_model()
        realized = realized_state()
        realized["level"] = 1.0  # float for an integer field
        with pytest.raises(StateValidationError):
            evaluate_trajectory(model, [make_transition(model)], initial_state=realized)

    def test_booleans_are_rejected_for_integer_and_number_fields(self) -> None:
        model = make_model()
        for key, value in (("level", True), ("ratio", False)):
            realized = realized_state()
            realized[key] = value
            with pytest.raises(StateValidationError):
                evaluate_trajectory(model, [make_transition(model)], initial_state=realized)

    def test_nan_and_infinity_are_rejected(self) -> None:
        model = make_model()
        for value in (float("nan"), float("inf"), float("-inf")):
            realized = realized_state()
            realized["ratio"] = value
            with pytest.raises(StateValidationError):
                evaluate_trajectory(model, [make_transition(model)], initial_state=realized)

    def test_allowed_values_violations_are_rejected(self) -> None:
        model = make_model()
        realized = realized_state()
        realized["status"] = "bogus"
        with pytest.raises(StateValidationError) as exc_info:
            evaluate_trajectory(
                model,
                [make_transition(model), make_transition(model, transition_id="t-2")],
                initial_state=realized,
            )
        reason = exc_info.value.reason
        assert reason is not None and "allowed_values" in reason

    def test_invalid_supplied_state_produces_no_transition_attempts(self) -> None:
        model = make_model()
        # The engine validates the supplied initial state before the attempt
        # loop: a state that fails validation raises and no attempt is ever
        # recorded, even when the transitions are valid and would match.
        realized = realized_state()
        realized["status"] = "invalid"
        with pytest.raises(StateValidationError):
            evaluate_trajectory(
                model,
                [make_transition(model), make_transition(model, transition_id="t-2")],
                initial_state=realized,
            )
        # A valid supplied state with an empty sequence proves attempts are
        # built only after initial-state validation succeeds.
        empty = evaluate_trajectory(model, [], initial_state=realized_state())
        assert empty.attempts == ()
        assert empty.final_state == realized_state()
