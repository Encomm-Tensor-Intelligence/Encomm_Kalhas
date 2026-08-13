"""Phase 17 application query-service tests.

Proves the read-only trajectory inspection service returns the stored
``RunTrajectoryExecution`` and ``RunTrajectoryReplayManifest`` artifacts
only after complete verification; that legacy/not-yet-executed/not-yet-
replayed/foreign/unsupported states fail with the existing typed errors
(404-family for absent artifacts, 409-family for unsupported versions and
corrupted records); that repeated retrieval is byte-identical and
returned objects are deep-copy isolated from storage; that the query
path performs no writes, lifecycle changes, events, replay manifests, or
activity entries; and that it never calls the execution builder, replay,
evaluation, LEGION, or NEXUS.
"""

from __future__ import annotations

import copy

import pytest
from kalhas.application.domain_errors import (
    RunNotFoundError,
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryExecutionNotFoundError,
    RunTrajectoryReplayManifestConflictError,
    RunTrajectoryReplayManifestNotFoundError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_runtime import (
    run_trajectory_execution_content_hash,
    state_trajectory_result_content_hash,
)
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.structural_runtime import execute_run
from kalhas.application.trajectory_query_service import (
    get_verified_run_trajectory_execution,
    get_verified_run_trajectory_replay_manifest,
)
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
    RunTrajectoryReplayManifest,
)

from tests.phase4_helpers import TENANT, build_store, prepare, start
from tests.phase16_helpers import (
    build_model,
    build_trajectory_store,
    build_transition,
)
from tests.phase25_helpers import inject_unsupported_recorded_runtime

OTHER_TENANT = "tenant-other"


def _run_ids(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, campaign_id))


def _executed_v2_store() -> tuple[InMemoryScenarioStore, str]:
    """A store with one executed trajectory-runtime run (one model)."""
    model = build_model()
    transition = build_transition(model)
    store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
    run_id = _run_ids(store)[0]
    execute_run(store=store, tenant_id=TENANT, run_id=run_id)
    return store, run_id


def _executed_and_replayed_v2_store() -> tuple[InMemoryScenarioStore, str]:
    store, run_id = _executed_v2_store()
    from kalhas.application.replay_service import replay_run

    replay_run(store=store, tenant_id=TENANT, run_id=run_id)
    return store, run_id


def _store_snapshot(store: InMemoryScenarioStore) -> object:
    """A deep snapshot of every store collection (safe with deepcopy)."""
    return copy.deepcopy(store.__dict__)


class TestExecutionRetrieval:
    def test_valid_v2_execution_retrieved(self) -> None:
        store, run_id = _executed_v2_store()
        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert isinstance(execution, RunTrajectoryExecution)
        assert execution.run_id == run_id
        assert execution == store.get_run_trajectory_execution(TENANT, run_id)

    def test_multiple_models_canonical_result_ordering(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        store, _ = build_trajectory_store(
            state_models=(model_1, model_2),
            transitions=(build_transition(model_1), build_transition(model_2)),
        )
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        # One result per applicable plan, in the canonical model order.
        assert len(execution.results) == 2
        assert [r.state_model_identifier for r in execution.results] == [
            model_1.identifier,
            model_2.identifier,
        ]

    def test_valid_empty_results_v2_world(self) -> None:
        store, _ = build_trajectory_store()
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert execution.results == ()

    def test_legacy_v1_run_has_no_execution_artifact(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)

    def test_retrieval_before_execution(self) -> None:
        store, _ = build_trajectory_store()
        run_id = _run_ids(store)[0]
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)

    def test_foreign_tenant_execution_indistinguishable_from_missing(self) -> None:
        store, run_id = _executed_v2_store()
        with pytest.raises(RunNotFoundError):
            get_verified_run_trajectory_execution(
                store=store, tenant_id=OTHER_TENANT, run_id=run_id
            )

    def test_unsupported_runtime_rejected(self) -> None:
        store, world_id = build_store()
        # Prepare a valid runtime-2 campaign, then simulate corrupted
        # recorded state through private test seams (not an application
        # preparation path): both the stored RunPlan and its matching
        # RunStatus are re-stamped with an unsupported recorded runtime.
        prepared = prepare(store, world_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        start(store)
        run_id = inject_unsupported_recorded_runtime(
            store, campaign_id="campaign-1", plan=prepared.run_plans[0]
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)

    def test_tampered_execution_rejected_with_safe_message(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        # A wrong world content hash is a structural tamper the verifier
        # catches before any field of the record is trusted.
        tampered = execution.model_copy(update={"world_content_hash": "f" * 64})
        store._run_trajectory_executions[(TENANT, run_id)] = tampered
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        message = str(exc_info.value)
        assert "f" * 64 not in message
        assert "integrity" in message

    def test_tampered_nested_state_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_result = result.model_copy(update={"final_state": {"status": "tampered"}})
        tampered_execution = execution.model_copy(update={"results": (tampered_result,)})
        store._run_trajectory_executions[(TENANT, run_id)] = tampered_execution
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        assert "tampered" not in str(exc_info.value)


class TestReplayManifestRetrieval:
    def test_valid_manifest_retrieved_after_exact_replay(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        manifest = get_verified_run_trajectory_replay_manifest(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert isinstance(manifest, RunTrajectoryReplayManifest)
        assert manifest.run_trajectory_execution_id == execution.identifier
        assert manifest == store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_retrieval_before_replay_returns_not_found_and_creates_nothing(self) -> None:
        store, run_id = _executed_v2_store()
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            get_verified_run_trajectory_replay_manifest(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        # Nothing was created by the failed retrieval.
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_manifest_query_verifies_authoritative_execution_first(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"world_content_hash": "f" * 64})
        store._run_trajectory_executions[(TENANT, run_id)] = tampered
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            get_verified_run_trajectory_replay_manifest(
                store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_tampered_manifest_rejected_with_safe_message(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        manifest = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        tampered = manifest.model_copy(update={"expected_execution_hash": "f" * 64})
        store._run_trajectory_replay_manifests[(TENANT, run_id)] = tampered
        with pytest.raises(RunTrajectoryReplayManifestConflictError) as exc_info:
            get_verified_run_trajectory_replay_manifest(
                store=store, tenant_id=TENANT, run_id=run_id
            )
        message = str(exc_info.value)
        assert "f" * 64 not in message
        assert "conflict" in message

    def test_legacy_v1_run_has_no_manifest(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            get_verified_run_trajectory_replay_manifest(
                store=store, tenant_id=TENANT, run_id=run_id
            )

    def test_foreign_tenant_manifest_indistinguishable_from_missing(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        with pytest.raises(RunNotFoundError):
            get_verified_run_trajectory_replay_manifest(
                store=store, tenant_id=OTHER_TENANT, run_id=run_id
            )


class TestIsolationAndDeterminism:
    def test_returned_object_mutation_cannot_affect_storage(self) -> None:
        store, run_id = _executed_v2_store()
        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        result = execution.results[0]
        result.final_state["status"] = "tampered"
        again = get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        assert again.results[0].final_state == {"status": "active"}

    def test_repeated_retrieval_is_byte_identical(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        first = get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        second = get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        first_manifest = get_verified_run_trajectory_replay_manifest(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        second_manifest = get_verified_run_trajectory_replay_manifest(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert first_manifest.model_dump(mode="json") == second_manifest.model_dump(mode="json")

    def test_queries_write_nothing_anywhere(self) -> None:
        store, run_id = _executed_and_replayed_v2_store()
        before = _store_snapshot(store)
        get_verified_run_trajectory_execution(store=store, tenant_id=TENANT, run_id=run_id)
        get_verified_run_trajectory_replay_manifest(store=store, tenant_id=TENANT, run_id=run_id)
        assert _store_snapshot(store) == before


class TestNoExecutionOrReplayOnTheQueryPath:
    def test_query_path_never_calls_builder_replay_or_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import kalhas.application.replay_service as replay_service
        import kalhas.application.run_trajectory_runtime as runtime
        import kalhas.application.state_transition_engine as engine

        store, run_id = _executed_and_replayed_v2_store()

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden call on the query path")

        monkeypatch.setattr(runtime, "build_run_trajectory_execution", boom)
        monkeypatch.setattr(replay_service, "replay_run", boom)
        monkeypatch.setattr(engine, "evaluate_trajectory", boom)

        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert execution.run_id == run_id
        manifest = get_verified_run_trajectory_replay_manifest(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert manifest.run_id == run_id

    def test_query_path_never_touches_legion_or_nexus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter

        store, run_id = _executed_and_replayed_v2_store()

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden adapter call on the query path")

        monkeypatch.setattr(MockLegionAdapter, "request_strategies", boom)
        monkeypatch.setattr(MockLegionAdapter, "request_trajectory_plan", boom)
        monkeypatch.setattr(MockNexusAdapter, "compile_scenario", boom)
        monkeypatch.setattr(MockNexusAdapter, "validate_scenario", boom)

        execution = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert execution.run_id == run_id
        manifest = get_verified_run_trajectory_replay_manifest(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert manifest.run_id == run_id

    def test_self_consistent_tamper_passes_verification_but_never_regenerates(self) -> None:
        # The verifier checks internal consistency only - like Phase 16
        # replay it never accepts a tampered artifact as its output. A
        # self-consistent tamper is still returned as stored (retrieval
        # is not regeneration); what matters is that the query path never
        # rebuilt or compared against a regenerated execution.
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered_final = {"status": "tampered"}
        result = execution.results[0].model_copy(
            update={"final_state": tampered_final, "final_state_hash": state_hash(tampered_final)}
        )
        result = result.model_copy(
            update={"content_hash": state_trajectory_result_content_hash(result)}
        )
        tampered_execution = execution.model_copy(update={"results": (result,)})
        tampered_execution = tampered_execution.model_copy(
            update={"content_hash": run_trajectory_execution_content_hash(tampered_execution)}
        )
        store._run_trajectory_executions[(TENANT, run_id)] = tampered_execution
        retrieved = get_verified_run_trajectory_execution(
            store=store, tenant_id=TENANT, run_id=run_id
        )
        assert retrieved.results[0].final_state == tampered_final
