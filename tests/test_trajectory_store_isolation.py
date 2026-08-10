"""Phase 16 store isolation tests for trajectory execution records.

Proves the two new store collections are deep-copy isolated (mutating
the original after put or a retrieved copy after get never affects
storage, including nested state dicts and lists), validator-bypassed
records are rejected on write, tenant isolation makes foreign access
indistinguishable from missing, and immutable records can never be
overwritten by a differing write (identical rewrites are idempotent).
"""

from __future__ import annotations

from typing import cast

import pytest
from kalhas.application.domain_errors import (
    RunTrajectoryExecutionAlreadyExistsError,
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryExecutionNotFoundError,
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.structural_runtime import execute_run
from kalhas.contracts.v1.state_model import StateValueKind
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)
from pydantic import ValidationError

from tests.phase4_helpers import TENANT
from tests.phase16_helpers import (
    build_model,
    build_trajectory_store,
    build_transition,
)

OTHER_TENANT = "tenant-other"


def _execution_pair() -> tuple[InMemoryScenarioStore, RunTrajectoryExecution, str]:
    """A store with one executed v2 run; returns (store, artifact, run_id)."""
    model = build_model()
    transition = build_transition(model)
    store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
    run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
    execute_run(store=store, tenant_id=TENANT, run_id=run_id)
    return store, store.get_run_trajectory_execution(TENANT, run_id), run_id


class TestExecutionIsolation:
    def test_original_mutation_after_put(self) -> None:
        store, execution, run_id = _execution_pair()
        store.put_run_trajectory_execution(TENANT, "run-other", execution)
        # Mutate the caller's object AFTER the write: storage is isolated.
        result = execution.results[0]
        result.initial_state["status"] = "tampered"
        stored = store.get_run_trajectory_execution(TENANT, "run-other")
        assert stored.results[0].initial_state == {"status": "idle"}

    def test_retrieved_mutation(self) -> None:
        store, execution, run_id = _execution_pair()
        retrieved = store.get_run_trajectory_execution(TENANT, run_id)
        result = retrieved.results[0]
        result.final_state["status"] = "tampered"
        stored = store.get_run_trajectory_execution(TENANT, run_id)
        assert stored.results[0].final_state == {"status": "active"}

    def test_nested_state_dict_and_list_mutation(self) -> None:
        model = build_model(
            state_model_id="sm-1",
            field="payload",
            value_kind=StateValueKind.JSON,
            initial_value={"items": [1, 2], "flag": True},
        )
        transition = build_transition(
            model,
            target_values={
                "payload": {"items": [1, 2, 3], "flag": True, "extra": {"deep": [9, 8]}}
            },
        )
        store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        retrieved = store.get_run_trajectory_execution(TENANT, run_id)
        payload = retrieved.results[0].final_state["payload"]
        assert isinstance(payload, dict)
        items = payload["items"]
        assert isinstance(items, list)
        items.append(999)
        extra = payload["extra"]
        assert isinstance(extra, dict)
        deep = extra["deep"]
        assert isinstance(deep, list)
        deep.append(777)
        stored = store.get_run_trajectory_execution(TENANT, run_id)
        stored_payload = stored.results[0].final_state["payload"]
        assert isinstance(stored_payload, dict)
        assert stored_payload["items"] == [1, 2, 3]
        extra = stored_payload["extra"]
        assert isinstance(extra, dict)
        assert extra["deep"] == [9, 8]

    def test_foreign_get_indistinguishable_from_missing(self) -> None:
        store, execution, run_id = _execution_pair()
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            store.get_run_trajectory_execution(OTHER_TENANT, run_id)

    def test_foreign_put_is_isolated(self) -> None:
        store, execution, run_id = _execution_pair()
        store.put_run_trajectory_execution(OTHER_TENANT, run_id, execution)
        assert store.get_run_trajectory_execution(OTHER_TENANT, run_id) == execution
        assert store.get_run_trajectory_execution(TENANT, run_id) == execution

    def test_identical_rewrite_idempotent(self) -> None:
        store, execution, run_id = _execution_pair()
        store.put_run_trajectory_execution(TENANT, run_id, execution)
        assert store.get_run_trajectory_execution(TENANT, run_id) == execution

    def test_conflicting_write_rejected_without_overwrite(self) -> None:
        store, execution, run_id = _execution_pair()
        tampered = execution.model_copy(deep=True)
        result = tampered.results[0]
        result.initial_state["status"] = "tampered"
        with pytest.raises(RunTrajectoryExecutionAlreadyExistsError):
            store.put_run_trajectory_execution(TENANT, run_id, tampered)
        assert store.get_run_trajectory_execution(TENANT, run_id) == execution

    def test_validator_bypassed_execution_rejected(self) -> None:
        store, execution, run_id = _execution_pair()
        bypassed = RunTrajectoryExecution.model_construct(
            **{
                **execution.model_dump(mode="python"),
                "runtime_version": "1.0.0",
            }
        )
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            store.put_run_trajectory_execution(TENANT, "run-bypassed", bypassed)
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            store.get_run_trajectory_execution(TENANT, "run-bypassed")

    def test_foreign_object_rejected(self) -> None:
        store, execution, run_id = _execution_pair()
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            store.put_run_trajectory_execution(
                TENANT, "run-foreign", cast(RunTrajectoryExecution, {"not": "an execution"})
            )


class TestReplayManifestIsolation:
    def _manifest_pair(self) -> tuple[InMemoryScenarioStore, RunTrajectoryReplayManifest, str]:
        from kalhas.application.replay_service import replay_run

        store, execution, run_id = _execution_pair()
        replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        return store, store.get_run_trajectory_replay_manifest(TENANT, run_id), run_id

    def test_original_mutation_after_put(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        store.put_run_trajectory_replay_manifest(TENANT, "run-other", manifest)
        stored = store.get_run_trajectory_replay_manifest(TENANT, "run-other")
        assert stored == manifest
        # The stored record is a detached copy, never the caller's object.
        assert stored is not manifest

    def test_retrieved_mutation(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        retrieved = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        with pytest.raises(ValidationError):
            retrieved.replay_classification = "approximate"  # type: ignore[assignment]
        stored = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        assert stored == manifest

    def test_foreign_get_indistinguishable_from_missing(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(OTHER_TENANT, run_id)

    def test_conflicting_write_rejected_without_overwrite(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        different = manifest.model_copy(update={"input_hash": "1" * 64})
        with pytest.raises(RunTrajectoryReplayManifestConflictError):
            store.put_run_trajectory_replay_manifest(TENANT, run_id, different)
        assert store.get_run_trajectory_replay_manifest(TENANT, run_id) == manifest

    def test_identical_rewrite_idempotent(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        store.put_run_trajectory_replay_manifest(TENANT, run_id, manifest)
        assert store.get_run_trajectory_replay_manifest(TENANT, run_id) == manifest

    def test_validator_bypassed_manifest_rejected(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        bypassed = RunTrajectoryReplayManifest.model_construct(
            **{
                **manifest.model_dump(mode="python"),
                "replay_classification": "approximate",
            }
        )
        with pytest.raises(RunTrajectoryReplayManifestConflictError):
            store.put_run_trajectory_replay_manifest(TENANT, "run-bypassed", bypassed)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, "run-bypassed")

    def test_foreign_object_rejected(self) -> None:
        store, manifest, run_id = self._manifest_pair()
        with pytest.raises(RunTrajectoryReplayManifestConflictError):
            store.put_run_trajectory_replay_manifest(
                TENANT, "run-foreign", cast(RunTrajectoryReplayManifest, {"not": "a manifest"})
            )
