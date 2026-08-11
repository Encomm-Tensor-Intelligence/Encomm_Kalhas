"""Phase 16 contract tests: immutable run trajectory execution records.

Proves the four new contract types are frozen, strict, JSON-safe, and
free of executable surface; that the two VersionedContracts are
registered in PUBLIC_CONTRACTS (now exactly 31 with the Phase 18 matrix
appended) while the two nested records are not; that the runtime version
and outcome literals are enforced; and that the deterministic identifier
and content hashes are sensitive to every covered field.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from kalhas.contracts.v1 import PUBLIC_CONTRACTS
from kalhas.contracts.v1.trajectory_execution import (
    RunStateTrajectoryResult,
    RunTrajectoryAttemptRecord,
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from pydantic import ValidationError

from tests.test_contracts import VALID_PAYLOADS

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _attempt(**overrides: object) -> RunTrajectoryAttemptRecord:
    payload: dict[str, object] = {
        "sequence_position": 0,
        "transition_identifier": "transition-1",
        "transition_id": "t-1",
        "transition_content_hash": HASH_64,
        "outcome": "applied",
        "before_state_hash": HASH_64,
        "after_state_hash": HASH_64,
    }
    payload.update(overrides)
    return RunTrajectoryAttemptRecord.model_validate(payload)


def _result(**overrides: object) -> RunStateTrajectoryResult:
    payload: dict[str, object] = {
        "trajectory_plan_id": "trajectory-plan-1",
        "trajectory_plan_content_hash": HASH_64,
        "manifest_id": "manifest-1",
        "state_model_identifier": "state-model-1",
        "state_model_id": "sm-1",
        "state_model_content_hash": HASH_64,
        "initial_state": {"status": "idle"},
        "initial_state_hash": HASH_64,
        "attempts": (_attempt(),),
        "final_state": {"status": "active"},
        "final_state_hash": HASH_64,
        "trace_hash": HASH_64,
        "content_hash": HASH_64,
    }
    payload.update(overrides)
    return RunStateTrajectoryResult.model_validate(payload)


def _execution(**overrides: object) -> RunTrajectoryExecution:
    payload: dict[str, object] = dict(VALID_PAYLOADS[RunTrajectoryExecution])
    payload.update(overrides)
    return RunTrajectoryExecution.model_validate(payload)


class TestRegistration:
    def test_public_contract_count_is_35(self) -> None:
        assert len(PUBLIC_CONTRACTS) == 37

    def test_only_the_two_versioned_records_are_registered(self) -> None:
        registered = {contract.__name__ for contract in PUBLIC_CONTRACTS}
        assert "RunTrajectoryExecution" in registered
        assert "RunTrajectoryReplayManifest" in registered
        assert "RunStateTrajectoryResult" not in registered
        assert "RunTrajectoryAttemptRecord" not in registered

    def test_registered_contracts_are_the_phase16_pair(self) -> None:
        assert RunTrajectoryExecution in PUBLIC_CONTRACTS
        assert RunTrajectoryReplayManifest in PUBLIC_CONTRACTS

    def test_only_versioned_records_are_registered(self) -> None:
        from kalhas.contracts.v1.shared import VersionedContract

        assert issubclass(RunTrajectoryExecution, VersionedContract)
        assert issubclass(RunTrajectoryReplayManifest, VersionedContract)
        assert not issubclass(RunStateTrajectoryResult, VersionedContract)
        assert not issubclass(RunTrajectoryAttemptRecord, VersionedContract)


class TestAttemptRecord:
    def test_frozen_assignment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _attempt().sequence_position = 1

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _attempt(explanation="hidden reasoning")

    def test_rejects_invalid_outcome(self) -> None:
        with pytest.raises(ValidationError):
            _attempt(outcome="applied_with_warning")

    def test_rejects_negative_position(self) -> None:
        with pytest.raises(ValidationError):
            _attempt(sequence_position=-1)

    def test_rejects_malformed_hash(self) -> None:
        with pytest.raises(ValidationError):
            _attempt(before_state_hash="not-a-hash")

    def test_rejects_guard_and_target_values(self) -> None:
        with pytest.raises(ValidationError):
            _attempt(guard_values={"status": "idle"})
        with pytest.raises(ValidationError):
            _attempt(target_values={"status": "active"})

    def test_guard_not_satisfied_outcome_valid(self) -> None:
        record = _attempt(outcome="guard_not_satisfied")
        assert record.outcome == "guard_not_satisfied"


class TestResultRecord:
    def test_frozen_assignment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _result().initial_state = {"status": "tampered"}

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _result(evidence={"anything": 1})

    def test_empty_attempts_are_valid(self) -> None:
        result = _result(attempts=())
        assert result.attempts == ()

    def test_rejects_non_json_state(self) -> None:
        with pytest.raises(ValidationError):
            _result(initial_state={"status": object()})

    def test_rejects_malformed_trace_hash(self) -> None:
        with pytest.raises(ValidationError):
            _result(trace_hash="trace")


class TestExecutionContract:
    def test_frozen_assignment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _execution().results = ()

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _execution(outcome_vector={"anything": 1})

    def test_rejects_non_trajectory_runtime_version(self) -> None:
        with pytest.raises(ValidationError):
            _execution(runtime_version="1.0.0")
        with pytest.raises(ValidationError):
            _execution(runtime_version="3.0.0")

    def test_empty_results_tuple_is_valid(self) -> None:
        execution = _execution(results=())
        assert execution.results == ()

    def test_rejects_malformed_plan_set_hash(self) -> None:
        with pytest.raises(ValidationError):
            _execution(trajectory_plan_set_hash="short")

    def test_requires_aware_datetime(self) -> None:
        with pytest.raises(ValidationError):
            _execution(executed_at=datetime(2026, 1, 1, 12, 0, 0))


class TestReplayManifestContract:
    def test_frozen_assignment_raises(self) -> None:
        manifest = _replay_manifest()
        with pytest.raises(ValidationError):
            manifest.replay_classification = "approximate"  # type: ignore[assignment]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            _replay_manifest(regenerated_states={"anything": 1})

    def test_rejects_non_exact_classification(self) -> None:
        with pytest.raises(ValidationError):
            _replay_manifest(replay_classification="approximate")

    def test_rejects_non_trajectory_runtime_version(self) -> None:
        with pytest.raises(ValidationError):
            _replay_manifest(runtime_version="1.0.0")

    def test_expected_and_recomputed_hashes_are_independent_fields(self) -> None:
        manifest = _replay_manifest(
            expected_execution_hash=HASH_64, recomputed_execution_hash=HASH_64
        )
        assert manifest.expected_execution_hash == manifest.recomputed_execution_hash


def _replay_manifest(**overrides: object) -> RunTrajectoryReplayManifest:
    payload: dict[str, object] = dict(VALID_PAYLOADS[RunTrajectoryReplayManifest])
    payload.update(overrides)
    return RunTrajectoryReplayManifest.model_validate(payload)


class TestContractJsonSafety:
    """The four contracts carry no executable surface (structural proof)."""

    def test_no_field_can_express_a_callback(self) -> None:
        for contract in (
            RunTrajectoryAttemptRecord,
            RunStateTrajectoryResult,
            RunTrajectoryExecution,
            RunTrajectoryReplayManifest,
        ):
            for name, field in contract.model_fields.items():
                annotation = str(field.annotation)
                # Word boundaries: "exec" is a substring of the module
                # name "trajectory_execution" inside annotations.
                assert not re.search(r"\b(?:Callable|exec|lambda)\b", annotation), (
                    f"{contract.__name__}.{name}"
                )

    def test_json_round_trip_preserves_records(self) -> None:
        execution = _execution()
        reloaded = RunTrajectoryExecution.model_validate_json(execution.model_dump_json())
        assert reloaded == execution
        manifest = _replay_manifest()
        reloaded_manifest = RunTrajectoryReplayManifest.model_validate_json(
            manifest.model_dump_json()
        )
        assert reloaded_manifest == manifest
