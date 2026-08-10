"""Phase 15 regression tests for the reusable transition-catalog validator.

``validate_transition_catalog`` is the pure, read-only pre-validation
extracted from the Phase 13 evaluation kernel so planning can validate a
world's transition catalogs without evaluating anything. These tests
prove the extracted validator rejects every corruption class with the
exact Phase 13 errors and reasons, performs no evaluation and no
mutation, and that ``evaluate_trajectory`` still rejects invalid
catalogs up front with its exact validation order (trajectory bounds
first, catalog validation second).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from kalhas.application.domain_errors import (
    InvalidTransitionSpecificationError,
    TrajectoryLimitExceededError,
    TransitionModelMismatchError,
)
from kalhas.application.domain_state_model_service import state_model_content_hash
from kalhas.application.domain_state_transition_service import transition_content_hash
from kalhas.application.state_transition_engine import (
    evaluate_trajectory,
    validate_transition_catalog,
)
from kalhas.contracts.v1.state_model import (
    DomainStateFieldDefinition,
    DomainStateModel,
    StateValueKind,
)
from kalhas.contracts.v1.transition import DomainStateTransition

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _make_model(
    *,
    state_model_id: str = "sm-1",
    tenant_id: str = "tenant-1",
    content_hash: str | None = None,
    allow_initial: tuple[str, ...] = ("idle", "active"),
) -> DomainStateModel:
    model = DomainStateModel(
        identifier="state-model-1",
        tenant_id=tenant_id,
        scenario_id="scenario-1",
        binding_id="binding-1",
        manifest_id="manifest-1",
        pack_id="pack-1",
        pack_version="1.2.3",
        manifest_content_hash=HASH_64,
        state_model_id=state_model_id,
        state_fields=(
            DomainStateFieldDefinition(
                identifier="status",
                description="Declared state field",
                value_kind=StateValueKind.STRING,
                initial_value="idle",
                allowed_values=allow_initial,
            ),
        ),
        content_hash="0" * 64,
        declared_at=NOW,
    )
    if content_hash is None:
        return model.model_copy(update={"content_hash": state_model_content_hash(model)})
    return model.model_copy(update={"content_hash": content_hash})


def _make_transition(
    model: DomainStateModel,
    *,
    transition_id: str = "t-1",
    guard_value: str = "idle",
    target_value: str = "active",
) -> DomainStateTransition:
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
        description="Declared state change",
        guard_values={"status": guard_value},
        target_values={"status": target_value},
        content_hash="0" * 64,
        declared_at=NOW,
    )
    return transition.model_copy(update={"content_hash": transition_content_hash(transition)})


class TestCatalogValidationRejects:
    def test_model_content_hash_mismatch_rejected(self) -> None:
        model = _make_model(content_hash="f" * 64)  # not its deterministic digest
        transition = _make_transition(model)
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            validate_transition_catalog(model, (transition,))
        assert exc_info.value.reason is not None
        assert "state model content hash mismatch" in exc_info.value.reason

    @pytest.mark.parametrize(
        ("field", "bad", "reason_fragment"),
        [
            ("tenant_id", "tenant-other", "tenant identity mismatch"),
            ("scenario_id", "scenario-other", "scenario identity mismatch"),
            ("binding_id", "binding-other", "binding identity mismatch"),
            ("pack_id", "pack-other", "pack identity mismatch"),
            ("pack_version", "9.9.9", "pack version mismatch"),
            ("manifest_id", "manifest-other", "manifest identity mismatch"),
            ("state_model_id", "sm-other", "state model identity mismatch"),
        ],
    )
    def test_transition_ownership_mismatch_rejected(
        self, field: str, bad: str, reason_fragment: str
    ) -> None:
        model = _make_model()
        transition = _make_transition(model).model_copy(update={field: bad})
        transition = transition.model_copy(
            update={"content_hash": transition_content_hash(transition)}
        )
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            validate_transition_catalog(model, (transition,))
        assert exc_info.value.reason is not None
        assert reason_fragment in exc_info.value.reason

    def test_manifest_content_hash_mismatch_rejected(self) -> None:
        model = _make_model()
        transition = _make_transition(model).model_copy(update={"manifest_content_hash": "f" * 64})
        transition = transition.model_copy(
            update={"content_hash": transition_content_hash(transition)}
        )
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            validate_transition_catalog(model, (transition,))
        assert exc_info.value.reason is not None
        assert "manifest content hash mismatch" in exc_info.value.reason

    def test_state_model_content_hash_mismatch_rejected(self) -> None:
        model = _make_model()
        transition = _make_transition(model).model_copy(
            update={"state_model_content_hash": "f" * 64}
        )
        transition = transition.model_copy(
            update={"content_hash": transition_content_hash(transition)}
        )
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            validate_transition_catalog(model, (transition,))
        assert exc_info.value.reason is not None
        assert "state model content hash mismatch" in exc_info.value.reason

    def test_transition_content_hash_mismatch_rejected(self) -> None:
        model = _make_model()
        transition = _make_transition(model).model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(TransitionModelMismatchError) as exc_info:
            validate_transition_catalog(model, (transition,))
        assert exc_info.value.reason is not None
        assert "transition content hash mismatch" in exc_info.value.reason

    @pytest.mark.parametrize(
        ("tamper", "reason_fragment"),
        [
            (
                lambda transition: transition.model_copy(update={"target_values": {}}),
                "target_values must be non-empty",
            ),
            (
                lambda transition: transition.model_copy(
                    update={"guard_values": {"ghost": "idle"}}
                ),
                "guard field 'ghost' does not exist in the state model",
            ),
            (
                lambda transition: transition.model_copy(update={"target_values": {"status": 42}}),
                "target value for field 'status' does not match its declared value kind",
            ),
            (
                lambda transition: transition.model_copy(
                    update={"target_values": {"status": "paused"}}
                ),
                "target value for field 'status' is not among its declared allowed_values",
            ),
        ],
    )
    def test_invalid_transition_specification_rejected(
        self,
        tamper: Callable[[DomainStateTransition], DomainStateTransition],
        reason_fragment: str,
    ) -> None:
        model = _make_model()
        transition = _make_transition(model)
        tampered = tamper(transition)
        tampered = tampered.model_copy(update={"content_hash": transition_content_hash(tampered)})
        with pytest.raises(InvalidTransitionSpecificationError) as exc_info:
            validate_transition_catalog(model, (tampered,))
        assert exc_info.value.reason is not None
        assert reason_fragment in exc_info.value.reason


class TestCatalogValidationIsReadOnly:
    def test_validation_performs_no_evaluation_and_no_mutation(self) -> None:
        model = _make_model()
        transition = _make_transition(model, guard_value="idle", target_value="active")
        model_pristine = copy.deepcopy(model)
        transition_pristine = copy.deepcopy(transition)
        # A matching guard exists, yet validation must never evaluate it;
        # the function returns nothing and leaves its inputs untouched.
        validate_transition_catalog(model, (transition,))
        assert model == model_pristine
        assert transition == transition_pristine
        assert model.model_dump(mode="json") == model_pristine.model_dump(mode="json")
        assert transition.model_dump(mode="json") == transition_pristine.model_dump(mode="json")

    def test_validation_accepts_empty_catalog(self) -> None:
        model = _make_model()
        model_pristine = copy.deepcopy(model)
        validate_transition_catalog(model, ())
        assert model == model_pristine

    def test_validation_accepts_repeated_transitions(self) -> None:
        model = _make_model()
        transition = _make_transition(model)
        transition_pristine = copy.deepcopy(transition)
        validate_transition_catalog(model, (transition, transition))
        assert transition == transition_pristine

    def test_validation_imposes_no_catalog_size_limit(self) -> None:
        model = _make_model()
        transition = _make_transition(model)
        # 2001 members exceed the evaluation kernel's default bound but
        # catalog validation is not an execution limit.
        validate_transition_catalog(model, (transition,) * 2001)


class TestEvaluationOrderPreserved:
    def test_evaluate_trajectory_still_rejects_invalid_catalog_up_front(self) -> None:
        model = _make_model()
        transition = _make_transition(model).model_copy(update={"tenant_id": "tenant-other"})
        transition = transition.model_copy(
            update={"content_hash": transition_content_hash(transition)}
        )
        with pytest.raises(TransitionModelMismatchError):
            evaluate_trajectory(model, (transition,))

    def test_evaluate_trajectory_bounds_fire_before_catalog_validation(self) -> None:
        """The exact Phase 13 validation order is preserved."""
        model = _make_model(content_hash="f" * 64)  # corrupt model
        transition = _make_transition(model)
        # A sequence longer than the bound raises the limit error even
        # though the corrupt model's catalog validation would otherwise
        # reject it: trajectory bounds fire first, then catalog.
        with pytest.raises(TrajectoryLimitExceededError):
            evaluate_trajectory(model, (transition, transition), max_attempts=1)

    def test_evaluate_trajectory_valid_catalog_result_unchanged(self) -> None:
        """A valid catalog still evaluates to the same deterministic result."""
        model = _make_model()
        transition = _make_transition(model)
        result = evaluate_trajectory(model, (transition,))
        assert result.attempts[0].outcome.value == "applied"
        assert result.attempts[0].before_state_hash != result.attempts[0].after_state_hash
        assert result.final_state["status"] == "active"
        assert result.trace_hash == evaluate_trajectory(model, (transition,)).trace_hash
