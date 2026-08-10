"""Tests for the Phase 13 pure deterministic state-transition evaluation kernel.

These tests prove the engine is a focused, deterministic,
domain-neutral application-layer kernel: initial state derived solely
from the model's declared initial values (deep-copied); guards evaluated
as exact canonical equality; targets applied as copy-on-write patches of
only their declared keys; strict caller-order evaluation (never
selection, reordering, or looping); never-mutate inputs; Phase 11
value-kind, allowed-values, and nested finite-JSON rules enforced before
and after application; foreign/mismatched transitions and corrupted
identities - including tampered ownership fields with recomputed
content hashes - rejected up front with safe typed errors; every
transition specification validated up front (non-empty targets, existing
guard/target keys, exact value kinds, allowed values, no nested
non-finite values) so an invalid specification can never be silently
recorded as `guard_not_satisfied`; trajectory
maximums enforced; result states returned as deep-frozen immutable
snapshots that work with hashing, validation, guards, and canonical
serialization exactly like plain states; and canonical hashing making
insertion order irrelevant.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, cast

import pytest
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
from kalhas.application.state_transition_engine import (
    TrajectoryEvaluation,
    TransitionAttempt,
    TransitionOutcome,
    derive_initial_state,
    evaluate_trajectory,
    state_hash,
    validate_state,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from pydantic import ValidationError

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
PLACEHOLDER = "0" * 64


def field(
    identifier: str = "status",
    *,
    value_kind: StateValueKind = StateValueKind.STRING,
    initial_value: JsonValue = "idle",
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


def make_model(
    *,
    state_model_id: str = "sm-1",
    manifest_id: str = "manifest-1",
    state_fields: tuple[DomainStateFieldDefinition, ...] | None = None,
) -> DomainStateModel:
    """Build an authoritative state model (self-consistent content hash)."""
    model = DomainStateModel(
        identifier=f"state-model-{state_model_id}",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id=manifest_id,
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id=state_model_id,
        state_fields=state_fields if state_fields is not None else base_fields(),
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
    description: str = "A possible state change",
) -> DomainStateTransition:
    """Build an authoritative transition belonging to the supplied model."""
    if guard_values is None:
        guard_values = {"level": 0}
    if target_values is None:
        target_values = {"status": "active"}
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
        description=description,
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


class TestInitialState:
    def test_derived_solely_from_declared_initial_values(self) -> None:
        model = make_model()
        initial = derive_initial_state(model)
        assert initial == expected_initial()
        # Canonical (identifier) insertion order in the fresh mapping.
        assert list(initial) == ["extra", "flag", "level", "ratio", "status"]

    def test_initial_state_hash_is_canonical_and_order_invariant(self) -> None:
        model = make_model()
        initial = derive_initial_state(model)
        assert state_hash(initial) == sha256_hex(canonical_json(initial))
        # Equivalent mapping with a different insertion order hashes identically.
        reordered: dict[str, JsonValue] = {
            "status": "idle",
            "extra": {"tags": []},
            "flag": False,
            "level": 0,
            "ratio": 0.0,
        }
        assert state_hash(reordered) == state_hash(initial)

    def test_initial_state_contains_all_declared_fields(self) -> None:
        model = make_model()
        assert set(derive_initial_state(model)) == {
            definition.identifier for definition in model.state_fields
        }


class TestValidateState:
    def test_accepts_exact_state(self) -> None:
        model = make_model()
        validate_state(expected_initial(), model)  # must not raise

    def test_rejects_unknown_state_field(self) -> None:
        model = make_model()
        with pytest.raises(StateValidationError) as exc_info:
            validate_state({**expected_initial(), "ghost": 1}, model)
        assert exc_info.value.reason == "unknown state field 'ghost'"
        # The public message stays generic (no field ids).
        assert "ghost" not in str(exc_info.value)

    def test_rejects_missing_required_field(self) -> None:
        model = make_model()
        missing = dict(expected_initial())
        del missing["level"]
        with pytest.raises(StateValidationError) as exc_info:
            validate_state(missing, model)
        assert exc_info.value.reason == "missing required state field 'level'"

    @pytest.mark.parametrize(
        ("key", "bad_value"),
        [
            ("level", True),  # bool as integer
            ("level", 1.5),  # float as integer
            ("level", "1"),  # string as integer
            ("ratio", True),  # bool as number
            ("ratio", float("nan")),  # non-finite number
            ("ratio", float("inf")),
            ("status", 5),  # integer as string
            ("flag", 1),  # integer as boolean
            ("flag", "true"),  # string as boolean
            ("status", {"nested": "x"}),  # dict as string
        ],
    )
    def test_rejects_values_not_matching_declared_kind(
        self, key: str, bad_value: JsonValue
    ) -> None:
        model = make_model()
        with pytest.raises(StateValidationError):
            validate_state({**expected_initial(), key: bad_value}, model)

    def test_rejects_nested_non_finite_json_values(self) -> None:
        model = make_model()
        with pytest.raises(StateValidationError):
            validate_state({**expected_initial(), "extra": {"tags": [float("nan")]}}, model)
        with pytest.raises(StateValidationError):
            validate_state({**expected_initial(), "extra": {"deep": {"x": float("-inf")}}}, model)

    def test_rejects_values_outside_declared_allowed_values(self) -> None:
        model = make_model()
        with pytest.raises(StateValidationError) as exc_info:
            validate_state({**expected_initial(), "status": "reserved"}, model)
        assert exc_info.value.reason == (
            "state value for field 'status' is not among its declared allowed_values"
        )
        # Canonical equality: an allowed value passes.
        validate_state({**expected_initial(), "status": "paused"}, model)

    def test_never_mutates_the_supplied_mapping(self) -> None:
        model = make_model()
        state = expected_initial()
        snapshot = copy.deepcopy(state)
        validate_state(state, model)
        assert state == snapshot


class TestGuardEvaluation:
    def test_guard_match_applies_only_declared_target_keys(self) -> None:
        model = make_model()
        transition = make_transition(
            model, guard_values={"level": 0}, target_values={"status": "active"}
        )
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.APPLIED
        # Only the declared target key changed; everything else is untouched.
        assert result.final_state["status"] == "active"
        assert result.final_state["level"] == 0
        assert result.final_state["ratio"] == 0.0
        assert result.final_state["flag"] is False
        assert result.final_state["extra"] == {"tags": []}
        assert result.initial_state == expected_initial()

    def test_guard_mismatch_leaves_state_byte_identical(self) -> None:
        model = make_model()
        transition = make_transition(
            model, guard_values={"status": "paused"}, target_values={"level": 7}
        )
        result = evaluate_trajectory(model, [transition])
        attempt = result.attempts[0]
        assert attempt.outcome is TransitionOutcome.GUARD_NOT_SATISFIED
        assert attempt.before_state_hash == attempt.after_state_hash
        assert result.final_state == result.initial_state == expected_initial()
        assert result.final_state_hash == result.initial_state_hash
        # The unchanged state mapping is returned untouched (same content).
        assert result.final_state == expected_initial()

    def test_guard_matches_on_exact_canonical_equality_only(self) -> None:
        # The engine derives state from the model, so the model's initial
        # json value is what guards compare against.
        model = make_model(
            state_fields=(
                field(
                    "status",
                    value_kind=StateValueKind.STRING,
                    initial_value="idle",
                    allowed_values=("idle", "active", "paused"),
                ),
                field("level", value_kind=StateValueKind.INTEGER, initial_value=0),
                field(
                    "extra",
                    value_kind=StateValueKind.JSON,
                    initial_value={"tags": [1, 2], "meta": {"a": 1, "b": 2}},
                ),
            )
        )
        ordered = make_transition(
            model,
            transition_id="t-nested",
            guard_values={"extra": {"tags": [1, 2], "meta": {"a": 1, "b": 2}}},
            target_values={"level": 3},
        )
        reordered = make_transition(
            model,
            transition_id="t-nested-2",
            guard_values={"extra": {"meta": {"b": 2, "a": 1}, "tags": [1, 2]}},
            target_values={"level": 3},
        )
        # Both guards match the same model-derived state (canonical JSON
        # equality sorts nested keys).
        for transition in (ordered, reordered):
            result = evaluate_trajectory(model, [transition])
            assert result.attempts[0].outcome is TransitionOutcome.APPLIED

    def test_guard_canonical_equality_distinguishes_one_from_one_point_zero(
        self,
    ) -> None:
        # 1 and 1.0 are canonically distinct. Both are valid NUMBER-kind
        # values, so the specification pre-validation passes and only the
        # canonical comparison can tell them apart: the guard with 1.0
        # must not match a state whose number field holds 1.
        model = make_model(
            state_fields=(
                field(
                    "status",
                    value_kind=StateValueKind.STRING,
                    initial_value="idle",
                    allowed_values=("idle", "active"),
                ),
                field("ratio", value_kind=StateValueKind.NUMBER, initial_value=1),
            )
        )
        transition = make_transition(
            model,
            guard_values={"ratio": 1.0},
            target_values={"status": "active"},
        )
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.GUARD_NOT_SATISFIED
        assert result.final_state == {"status": "idle", "ratio": 1}


class TestOrderAndImmutability:
    def test_multiple_transitions_evaluate_strictly_in_supplied_order(self) -> None:
        model = make_model()
        first = make_transition(
            model,
            transition_id="t-1",
            guard_values={"level": 0},
            target_values={"status": "active", "level": 1},
        )
        second = make_transition(
            model,
            transition_id="t-2",
            guard_values={"status": "active"},
            target_values={"status": "paused", "flag": True},
        )
        result = evaluate_trajectory(model, [first, second])
        assert [(a.transition_id, a.outcome) for a in result.attempts] == [
            ("t-1", TransitionOutcome.APPLIED),
            ("t-2", TransitionOutcome.APPLIED),
        ]
        # The second attempt's before-state is the first attempt's after-state.
        assert result.attempts[0].after_state_hash == result.attempts[1].before_state_hash
        assert result.final_state["status"] == "paused"
        assert result.final_state["level"] == 1
        assert result.final_state["flag"] is True

    def test_different_orderings_produce_different_valid_trajectories(self) -> None:
        model = make_model()
        to_active = make_transition(
            model,
            transition_id="t-active",
            guard_values={"level": 0},
            target_values={"status": "active"},
        )
        to_level_five = make_transition(
            model,
            transition_id="t-five",
            guard_values={"status": "active"},
            target_values={"level": 5},
        )
        forward = evaluate_trajectory(model, [to_active, to_level_five])
        backward = evaluate_trajectory(model, [to_level_five, to_active])
        # Forward: both apply -> status active, level 5.
        assert [a.outcome for a in forward.attempts] == [
            TransitionOutcome.APPLIED,
            TransitionOutcome.APPLIED,
        ]
        assert forward.final_state["level"] == 5
        # Backward: the level guard fails first, then the status transition
        # applies -> status active, level still 0.
        assert [a.outcome for a in backward.attempts] == [
            TransitionOutcome.GUARD_NOT_SATISFIED,
            TransitionOutcome.APPLIED,
        ]
        assert backward.final_state["level"] == 0
        assert backward.final_state["status"] == "active"
        assert forward.final_state != backward.final_state
        # Both trajectories are valid states per the model.
        validate_state(forward.final_state, model)
        validate_state(backward.final_state, model)

    def test_inputs_are_never_mutated(self) -> None:
        model = make_model()
        transition = make_transition(
            model, guard_values={"level": 0}, target_values={"status": "active", "level": 9}
        )
        model_snapshot = model.model_dump(mode="json")
        transition_snapshot = transition.model_dump(mode="json")
        state = expected_initial()
        state_snapshot = copy.deepcopy(state)
        validate_state(state, model)
        result = evaluate_trajectory(model, [transition])
        # Model and transition contracts are byte-identical afterwards.
        assert model.model_dump(mode="json") == model_snapshot
        assert transition.model_dump(mode="json") == transition_snapshot
        # The supplied state mapping is untouched.
        assert state == state_snapshot
        # The engine's initial-state mapping is a fresh dict, and the final
        # state is a fresh dict, never the same object as the initial one
        # when a transition applied.
        assert result.initial_state == expected_initial()
        assert result.final_state is not result.initial_state

    def test_insertion_order_never_changes_state_or_trace_hashes(self) -> None:
        model = make_model()
        transition = make_transition(
            model,
            guard_values={"extra": {"meta": {"x": 1}, "tags": []}},
            target_values={"status": "active"},
        )
        first = evaluate_trajectory(model, [transition])
        second = evaluate_trajectory(model, [transition])
        assert first == second
        assert first.final_state_hash == second.final_state_hash
        assert first.trace_hash == second.trace_hash
        # A state mapping with reversed insertion order hashes identically.
        reordered: dict[str, JsonValue] = {
            "extra": {"tags": []},
            "ratio": 0.0,
            "flag": False,
            "status": "idle",
            "level": 0,
        }
        assert state_hash(reordered) == state_hash(expected_initial())

    def test_empty_sequence_returns_initial_state_unchanged(self) -> None:
        model = make_model()
        result = evaluate_trajectory(model, [])
        assert result.attempts == ()
        assert result.final_state == result.initial_state == expected_initial()
        assert result.final_state_hash == result.initial_state_hash
        assert result.trace_hash == sha256_hex(canonical_json([]))


class TestDeepImmutableResultSnapshots:
    def test_result_state_mappings_are_immutable_at_top_level(self) -> None:
        model = make_model()
        result = evaluate_trajectory(model, [])
        # cast: the snapshots are deliberately read-only at runtime; the
        # cast gives mypy a writable target so the raised-mutation
        # assertions below are statically legal.
        for snapshot in (
            cast(dict[str, Any], result.initial_state),
            cast(dict[str, Any], result.final_state),
        ):
            with pytest.raises(TypeError):
                snapshot["status"] = "active"
            with pytest.raises(TypeError):
                snapshot["level"] = 1

    def test_nested_result_mappings_and_arrays_are_immutable(self) -> None:
        model = make_model()
        transition = make_transition(
            model, target_values={"extra": {"tags": ["x"], "deep": {"k": 1}}}
        )
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.APPLIED
        # cast: same rationale as above - the runtime objects are the
        # read-only frozen snapshot containers.
        initial_extra = cast(dict[str, Any], result.initial_state["extra"])
        final_extra = cast(dict[str, Any], result.final_state["extra"])
        # Nested mapping mutation raises (both the initial and final
        # snapshots are recursively frozen).
        with pytest.raises(TypeError):
            initial_extra["tags"] = ["y"]
        with pytest.raises(TypeError):
            final_extra["deep"]["k"] = 2
        # Nested arrays reject list-style mutators and index assignment.
        with pytest.raises(AttributeError):
            initial_extra["tags"].append("y")
        with pytest.raises(TypeError):
            final_extra["tags"][0] = "y"

    def test_mutating_model_initial_value_after_evaluation_does_not_alter_result(
        self,
    ) -> None:
        model = make_model(
            state_fields=(
                field(
                    "extra",
                    value_kind=StateValueKind.JSON,
                    initial_value={"tags": ["keep"]},
                ),
                field("level", value_kind=StateValueKind.INTEGER, initial_value=0),
            )
        )
        result = evaluate_trajectory(model, [])
        # The model's own stored nested initial dict is a plain mutable
        # object; mutating it after evaluation must not leak into the
        # result snapshots (they were deep-frozen, never aliased).
        # cast: ``initial_value`` is typed ``JsonValue``, a union that
        # mypy cannot index.
        model_extra = cast(dict[str, Any], model.state_fields[0].initial_value)
        model_extra["tags"].append("tampered")
        # Whole-snapshot comparison (no union indexing): the frozen
        # snapshots are still value-equal to the pre-mutation state.
        assert result.initial_state == {"extra": {"tags": ["keep"]}, "level": 0}
        assert result.final_state == {"extra": {"tags": ["keep"]}, "level": 0}
        assert result.initial_state_hash == state_hash({"extra": {"tags": ["keep"]}, "level": 0})

    def test_mutating_transition_target_source_after_evaluation_does_not_alter_result(
        self,
    ) -> None:
        model = make_model()
        transition = make_transition(model, target_values={"extra": {"tags": ["target"]}})
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.APPLIED
        # The transition's own stored target dict is a plain mutable
        # object; mutating it after evaluation must not leak into the
        # stored final snapshot.
        # cast: ``target_values[key]`` is typed ``JsonValue``, a union
        # that mypy cannot index.
        target_extra = cast(dict[str, Any], transition.target_values["extra"])
        target_extra["tags"].append("tampered")
        # Whole-snapshot comparison (no union indexing): the stored
        # final snapshot is unchanged by the post-evaluation mutation.
        assert result.final_state == {
            "status": "idle",
            "level": 0,
            "ratio": 0.0,
            "flag": False,
            "extra": {"tags": ["target"]},
        }
        assert result.final_state_hash == state_hash(
            {
                "status": "idle",
                "level": 0,
                "ratio": 0.0,
                "flag": False,
                "extra": {"tags": ["target"]},
            }
        )

    def test_frozen_snapshots_hash_validate_and_match_plain_states(self) -> None:
        model = make_model()
        transition = make_transition(
            model, target_values={"extra": {"tags": ["x"], "deep": {"k": 1}}}
        )
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.APPLIED
        # Recorded hashes are reproducible from the frozen snapshots.
        assert state_hash(result.initial_state) == result.initial_state_hash
        assert state_hash(result.final_state) == result.final_state_hash
        # Frozen snapshots validate exactly like plain states.
        validate_state(result.initial_state, model)
        validate_state(result.final_state, model)
        # Validation still rejects bad values mixed with frozen ones.
        bad = dict(result.initial_state)
        bad["status"] = 5
        with pytest.raises(StateValidationError):
            validate_state(bad, model)
        bad_allowed = dict(result.initial_state)
        bad_allowed["status"] = "reserved"
        with pytest.raises(StateValidationError) as exc_info:
            validate_state(bad_allowed, model)
        assert "allowed_values" in (exc_info.value.reason or "")
        # Frozen snapshots compare equal to their plain JSON equivalents.
        assert result.initial_state == expected_initial()
        assert result.final_state == {
            "status": "idle",
            "level": 0,
            "ratio": 0.0,
            "flag": False,
            "extra": {"tags": ["x"], "deep": {"k": 1}},
        }
        # Re-evaluating reproduces the exact same records.
        assert evaluate_trajectory(model, [transition]) == result
        assert evaluate_trajectory(model, [transition]).trace_hash == result.trace_hash

    def test_guard_matching_accepts_frozen_state_values(self) -> None:
        from kalhas.application.state_transition_engine import _guard_matches

        model = make_model()
        transition = make_transition(
            model,
            guard_values={"extra": {"tags": []}},
            target_values={"status": "active"},
        )
        result = evaluate_trajectory(model, [transition])
        assert result.attempts[0].outcome is TransitionOutcome.APPLIED
        # The frozen snapshot matches the guard exactly like the plain state.
        assert _guard_matches(result.initial_state, transition)


class TestPostApplicationEnforcement:
    def test_target_violating_allowed_values_rejected(self) -> None:
        model = make_model()
        # A hand-built transition whose target violates the model's allowed
        # values is rejected by the up-front specification validation
        # (Phase 12 declaration would reject it too); the engine's
        # post-application revalidation remains defense in depth.
        transition = make_transition(
            model, transition_id="t-bad-target", target_values={"status": "reserved"}
        )
        with pytest.raises(InvalidTransitionSpecificationError) as exc_info:
            evaluate_trajectory(model, [transition])
        assert "allowed_values" in (exc_info.value.reason or "")

    def test_target_violating_value_kind_rejected(self) -> None:
        model = make_model()
        transition = make_transition(
            model, transition_id="t-bad-kind", target_values={"level": "high"}
        )
        with pytest.raises(InvalidTransitionSpecificationError):
            evaluate_trajectory(model, [transition])

    def test_target_with_nested_non_finite_json_cannot_reach_the_engine(self) -> None:
        # The DomainStateTransition contract rejects nested non-finite
        # target values at construction time (Phase 12 rule), so a NaN or
        # Infinity target can never be supplied to the engine; the
        # engine's post-application validation remains defense in depth.
        with pytest.raises(ValidationError):
            make_transition(
                make_model(),
                transition_id="t-bad-json",
                target_values={"extra": {"x": float("inf")}},
            )
        with pytest.raises(ValidationError):
            make_transition(
                make_model(),
                transition_id="t-bad-json-2",
                target_values={"extra": {"nested": [float("nan")]}},
            )

    def test_valid_guarded_transition_chain_passes(self) -> None:
        model = make_model()
        transitions = (
            make_transition(
                model, transition_id="t-a", target_values={"status": "active", "level": 2}
            ),
            make_transition(
                model,
                transition_id="t-b",
                guard_values={"level": 2},
                target_values={"status": "paused"},
            ),
        )
        result = evaluate_trajectory(model, transitions)
        assert [a.outcome for a in result.attempts] == [
            TransitionOutcome.APPLIED,
            TransitionOutcome.APPLIED,
        ]
        assert result.final_state["status"] == "paused"
        assert result.final_state["level"] == 2


class TestIdentityAndHashIntegrity:
    def test_transition_from_another_state_model_rejected(self) -> None:
        model = make_model()
        other_model = make_model(state_model_id="sm-other")
        foreign = make_transition(other_model, transition_id="t-foreign")
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [foreign])
        assert exc_info.value.reason == "state model identity mismatch"
        # Public message is generic but names the caller-supplied ids.
        message = str(exc_info.value)
        assert "t-foreign" in message
        assert "sm-1" in message

    def test_transition_from_another_manifest_rejected(self) -> None:
        model = make_model()
        other_model = make_model(manifest_id="manifest-other")
        foreign = make_transition(other_model, transition_id="t-foreign-manifest")
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [foreign])
        assert exc_info.value.reason == "manifest identity mismatch"

    def test_transition_with_wrong_manifest_content_hash_rejected(self) -> None:
        model = make_model()
        transition = make_transition(model).model_copy(update={"manifest_content_hash": "f" * 64})
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [transition])
        assert exc_info.value.reason == "manifest content hash mismatch"

    def test_transition_with_wrong_state_model_content_hash_rejected(self) -> None:
        model = make_model()
        transition = make_transition(model).model_copy(
            update={"state_model_content_hash": "f" * 64}
        )
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [transition])
        assert exc_info.value.reason == "state model content hash mismatch"

    def test_transition_with_corrupted_own_content_hash_rejected(self) -> None:
        model = make_model()
        transition = make_transition(model).model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [transition])
        assert exc_info.value.reason == "transition content hash mismatch"
        # Raw hashes never leak into the public message.
        assert "f" * 64 not in str(exc_info.value)

    def test_state_model_with_corrupted_content_hash_rejected(self) -> None:
        model = make_model()
        corrupted = model.model_copy(update={"content_hash": "f" * 64})
        transition = make_transition(model)
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(corrupted, [transition])
        assert exc_info.value.reason == "state model content hash mismatch"
        assert "f" * 64 not in str(exc_info.value)

    def test_sequence_with_conflicting_model_identities_rejected_upfront(self) -> None:
        model = make_model()
        other_model = make_model(state_model_id="sm-other")
        good = make_transition(model, transition_id="t-good")
        foreign = make_transition(other_model, transition_id="t-foreign")
        # The mismatch is detected before any evaluation happens: even a
        # sequence whose first member is valid is rejected as a whole.
        with pytest.raises(TransitionModelMismatchError):
            evaluate_trajectory(model, [good, foreign])

    @pytest.mark.parametrize(
        ("field_name", "tampered_value", "expected_reason"),
        [
            ("tenant_id", "tenant-other", "tenant identity mismatch"),
            ("scenario_id", "scenario-other", "scenario identity mismatch"),
            ("binding_id", "binding-other", "binding identity mismatch"),
            ("pack_id", "pack-other", "pack identity mismatch"),
            ("pack_version", "9.9.9", "pack version mismatch"),
        ],
    )
    def test_transition_with_tampered_ownership_field_rejected(
        self, field_name: str, tampered_value: str, expected_reason: str
    ) -> None:
        model = make_model()
        tampered = make_transition(model).model_copy(update={field_name: tampered_value})
        # The tamper is self-consistent: the transition's own content
        # hash is recomputed over the tampered content, so only the
        # ownership comparison can catch it.
        rehashed = tampered.model_copy(update={"content_hash": transition_content_hash(tampered)})
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [rehashed])
        assert exc_info.value.reason == expected_reason
        # The tampered value never leaks into the public message.
        assert tampered_value not in str(exc_info.value)

    def test_tampered_ownership_transition_rejected_before_any_evaluation(self) -> None:
        model = make_model()
        good = make_transition(model, transition_id="t-good", target_values={"status": "active"})
        tampered = make_transition(model, transition_id="t-bad").model_copy(
            update={"binding_id": "binding-other"}
        )
        rehashed = tampered.model_copy(update={"content_hash": transition_content_hash(tampered)})
        # Upfront rejection: even with a valid first member the whole
        # sequence raises and no partial trajectory is ever produced.
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            evaluate_trajectory(model, [good, rehashed])
        assert exc_info.value.reason == "binding identity mismatch"


class TestTransitionSpecificationPreValidation:
    @pytest.mark.parametrize(
        ("tamper", "reason_fragment"),
        [
            ({"guard_values": {"ghost": 1}}, "guard field 'ghost' does not exist"),
            ({"target_values": {"ghost": 1}}, "target field 'ghost' does not exist"),
            ({"guard_values": {"level": "high"}}, "guard value for field 'level'"),
            ({"target_values": {"level": "high"}}, "target value for field 'level'"),
            ({"guard_values": {"status": "reserved"}}, "guard value for field 'status'"),
            ({"target_values": {"status": "reserved"}}, "target value for field 'status'"),
            ({"guard_values": {"extra": {"x": float("nan")}}}, "guard value for field 'extra'"),
            ({"target_values": {"extra": {"x": float("inf")}}}, "target value for field 'extra'"),
            ({"target_values": {}}, "target_values must be non-empty"),
        ],
    )
    def test_invalid_specification_rejected_before_evaluation(
        self, tamper: dict[str, object], reason_fragment: str
    ) -> None:
        model = make_model()
        # Every tamper is self-consistent: the transition's own content
        # hash is recomputed over the tampered content, so only the
        # specification validation can catch it (model_copy bypasses the
        # contract validators - including the non-empty-targets rule).
        tampered = make_transition(model).model_copy(update=tamper)
        rehashed = tampered.model_copy(update={"content_hash": transition_content_hash(tampered)})
        with pytest.raises(InvalidTransitionSpecificationError) as exc_info:
            evaluate_trajectory(model, [rehashed])
        assert exc_info.value.transition_id == "t-1"
        assert exc_info.value.reason is not None
        assert reason_fragment in exc_info.value.reason
        # The public message stays generic: no reason, state value, or
        # hash leaks into it.
        assert exc_info.value.reason not in str(exc_info.value)
        assert "t-1" in str(exc_info.value)

    def test_invalid_target_behind_non_matching_guard_rejected(self) -> None:
        model = make_model()
        # The guard ("status": "paused") deliberately does not match the
        # initial state ("idle"), but the invalid target value must still
        # fail pre-validation - it cannot evade validation merely because
        # its guard does not match.
        transition = make_transition(
            model,
            transition_id="t-bad-behind-guard",
            guard_values={"status": "paused"},
            target_values={"level": "high"},
        )
        rehashed = transition.model_copy(
            update={"content_hash": transition_content_hash(transition)}
        )
        with pytest.raises(InvalidTransitionSpecificationError) as exc_info:
            evaluate_trajectory(model, [rehashed])
        assert "target" in (exc_info.value.reason or "")
        assert "high" not in str(exc_info.value)

    def test_invalid_member_rejects_whole_sequence_before_any_attempt(self) -> None:
        model = make_model()
        good = make_transition(model, transition_id="t-good", target_values={"status": "active"})
        tampered = make_transition(model, transition_id="t-bad").model_copy(
            update={"target_values": {"ghost": 1}}
        )
        rehashed = tampered.model_copy(update={"content_hash": transition_content_hash(tampered)})
        # The complete sequence is validated up front: the invalid second
        # member fails before the first attempt, so the valid first
        # member never produces a partial trajectory result.
        with pytest.raises(InvalidTransitionSpecificationError) as exc_info:
            evaluate_trajectory(model, [good, rehashed])
        assert "ghost" in (exc_info.value.reason or "")


class TestTrajectoryLimit:
    def test_sequence_longer_than_maximum_rejected_before_evaluation(self) -> None:
        model = make_model()
        transitions = (
            make_transition(model, transition_id="t-1"),
            make_transition(model, transition_id="t-2"),
        )
        with pytest.raises(TrajectoryLimitExceededError) as exc_info:
            evaluate_trajectory(model, transitions, max_attempts=1)
        assert exc_info.value.required == 2
        assert exc_info.value.maximum == 1
        assert "2" in str(exc_info.value)

    def test_sequence_at_exactly_the_maximum_is_accepted(self) -> None:
        model = make_model()
        transitions = (
            make_transition(model, transition_id="t-1"),
            make_transition(model, transition_id="t-2"),
        )
        result = evaluate_trajectory(model, transitions, max_attempts=2)
        assert len(result.attempts) == 2

    def test_non_positive_maximum_rejected(self) -> None:
        model = make_model()
        with pytest.raises(InvalidTrajectoryLimitError):
            evaluate_trajectory(model, [], max_attempts=0)
        with pytest.raises(InvalidTrajectoryLimitError):
            evaluate_trajectory(model, [], max_attempts=-3)

    def test_default_maximum_is_safe_and_fixed(self) -> None:
        from kalhas.application.state_transition_engine import (
            DEFAULT_MAX_TRANSITION_ATTEMPTS,
        )

        assert DEFAULT_MAX_TRANSITION_ATTEMPTS == 1000


class TestTraceRecords:
    def test_attempt_records_carry_structural_facts_only(self) -> None:
        model = make_model()
        transition = make_transition(
            model, transition_id="t-trace", target_values={"status": "active"}
        )
        result = evaluate_trajectory(model, [transition])
        attempt = result.attempts[0]
        assert isinstance(attempt, TransitionAttempt)
        assert attempt.sequence_position == 0
        assert attempt.transition_id == "t-trace"
        assert attempt.transition_content_hash == transition.content_hash
        assert attempt.outcome is TransitionOutcome.APPLIED
        assert len(attempt.before_state_hash) == 64
        assert len(attempt.after_state_hash) == 64
        assert attempt.before_state_hash == result.initial_state_hash
        assert attempt.after_state_hash == result.final_state_hash
        # No human-language explanations or hidden reasoning.
        serialized = repr(attempt)
        assert "because" not in serialized
        assert "reasoning" not in serialized

    def test_trace_hash_is_deterministic_and_canonical(self) -> None:
        model = make_model()
        transitions = (
            make_transition(model, transition_id="t-1", target_values={"status": "active"}),
            make_transition(
                model,
                transition_id="t-2",
                guard_values={"status": "active"},
                target_values={"level": 4},
            ),
            make_transition(model, transition_id="t-3", guard_values={"level": 9}),
        )
        first = evaluate_trajectory(model, transitions)
        second = evaluate_trajectory(model, transitions)
        assert first == second
        assert first.trace_hash == second.trace_hash
        # The trace hash is the canonical digest of the ordered attempt records.
        records = [
            {
                "sequence_position": attempt.sequence_position,
                "transition_id": attempt.transition_id,
                "transition_content_hash": attempt.transition_content_hash,
                "outcome": attempt.outcome.value,
                "before_state_hash": attempt.before_state_hash,
                "after_state_hash": attempt.after_state_hash,
            }
            for attempt in first.attempts
        ]
        assert first.trace_hash == sha256_hex(canonical_json(records))
        assert [a.outcome for a in first.attempts] == [
            TransitionOutcome.APPLIED,
            TransitionOutcome.APPLIED,
            TransitionOutcome.GUARD_NOT_SATISFIED,
        ]
        assert first.final_state_hash == state_hash(first.final_state)
        assert isinstance(first, TrajectoryEvaluation)
        assert first.state_model_id == "sm-1"

    def test_result_states_cannot_be_mutated_by_callers(self) -> None:
        model = make_model()
        result = evaluate_trajectory(model, [])
        # The returned snapshots are deep-immutable: even a top-level
        # assignment raises, and the recorded hashes stay intact.
        # cast: the runtime snapshot is deliberately read-only; the cast
        # gives mypy a writable target so the raise is statically legal.
        final_state = cast(dict[str, Any], result.final_state)
        with pytest.raises(TypeError):
            final_state["status"] = "tampered"
        assert result.initial_state == expected_initial()
        assert result.final_state_hash == state_hash(expected_initial())


class TestNoExecutableMechanisms:
    def test_engine_imports_only_declarative_and_hashing_modules(self) -> None:
        """The engine never imports adapters, packs, or executable machinery.

        Only code is scanned: docstrings legitimately name the forbidden
        mechanisms ("no callbacks, no evaluators...") as prose.
        """
        from pathlib import Path

        import kalhas.application.state_transition_engine as engine

        source = Path(engine.__file__).read_text(encoding="utf-8")
        parts = source.split('"""')
        code_only = "".join(parts[index] for index in range(0, len(parts), 2))
        for token in (
            "importlib",
            "__import__",
            "import_module",
            "exec(",
            "eval(",
            "lambda",
            "Callable",
            "callback",
            "kalhas.domain_packs",
            "kalhas.adapters",
        ):
            assert token not in code_only

    def test_engine_exposes_no_http_store_or_activity_surface(self) -> None:
        import kalhas.application.state_transition_engine as engine

        for name in dir(engine):
            if name.startswith("_"):
                continue
            assert "route" not in name.lower()
            assert "activity" not in name.lower()
