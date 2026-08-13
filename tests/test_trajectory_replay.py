"""Phase 16 exact trajectory replay tests.

Proves legacy (1.0.0) replay is byte-identical to the pre-Phase 16
behavior and never requires or creates a trajectory replay manifest;
that trajectory (2.0.0) replay independently regenerates the complete
expected execution from recorded inputs, requires exact full-object and
content-hash equality with the stored authoritative artifact, and only
then stores both replay manifests; that every tamper class - state,
result, attempt, hash, order, plan-set, runtime, seed, and
self-consistent hash recomputation - is rejected with a typed safe
error and zero manifests written; that a missing execution is rejected;
that replay never calls LEGION; and that repeated replay is
deterministic and can never overwrite a different stored manifest.
"""

from __future__ import annotations

import inspect

import pytest
from kalhas.application.domain_errors import (
    RunNotFoundError,
    RunTrajectoryExecutionIntegrityError,
    RunTrajectoryExecutionNotFoundError,
    RunTrajectoryReplayManifestNotFoundError,
    TrajectoryReplayMismatchError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.replay_service import replay_run
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
from kalhas.contracts.v1.execution import RunState
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

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _run_ids(store: InMemoryScenarioStore, campaign_id: str = "campaign-1") -> tuple[str, ...]:
    return tuple(run_identifier(plan) for plan in store.get_run_plans(TENANT, campaign_id))


def _executed_v2_store() -> tuple[InMemoryScenarioStore, str]:
    model = build_model()
    transition = build_transition(model)
    store, _ = build_trajectory_store(state_models=(model,), transitions=(transition,))
    run_id = _run_ids(store)[0]
    execute_run(store=store, tenant_id=TENANT, run_id=run_id)
    return store, run_id


class TestLegacyReplay:
    def test_v1_replay_unchanged_and_creates_no_trajectory_manifest(self) -> None:
        store, world_id = build_store()
        prepared = prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        run_id = run_identifier(prepared.run_plans[0])
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        manifest = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert manifest.replay_classification == "exact"
        assert manifest.expected_event_hash == store.get_run_status(TENANT, run_id).event_hash
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_unsupported_version_rejected_before_replay_manifests(self) -> None:
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
        status = store.get_run_status(TENANT, run_id)
        # Fake a COMPLETE status so replay reaches the runtime gate.
        store.put_run_status(
            TENANT,
            run_id,
            status.model_copy(update={"state": RunState.COMPLETE, "event_hash": HASH_64}),
        )
        with pytest.raises(UnsupportedRuntimeVersionError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)


class TestExactTrajectoryReplay:
    def test_v2_replay_creates_both_manifests(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        manifest = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert manifest.run_id == run_id
        trajectory_manifest = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        assert trajectory_manifest.run_trajectory_execution_id == execution.identifier
        assert trajectory_manifest.expected_execution_hash == execution.content_hash
        assert trajectory_manifest.recomputed_execution_hash == execution.content_hash
        assert trajectory_manifest.replay_classification == "exact"
        assert trajectory_manifest.replayed_at == execution.executed_at
        # Structural replay still produced the exact event hash.
        assert manifest.expected_event_hash == store.get_run_status(TENANT, run_id).event_hash

    def test_v2_replay_independently_regenerates_structural_events(self) -> None:
        store, run_id = _executed_v2_store()
        # Wipe the cached event stream: replay must regenerate it from
        # recorded inputs (the recomputed hash must still match), never
        # serve the stored events - and it never rewrites the stream.
        store.put_run_events(TENANT, run_id, ())
        manifest = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert manifest.expected_event_hash == store.get_run_status(TENANT, run_id).event_hash
        assert store.get_run_events(TENANT, run_id) == ()

    def test_v2_replay_never_reads_cached_trajectory_output(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        # A stored artifact tampered self-consistently (final state, its
        # hash, and both content hashes recomputed) passes the record
        # verification - yet replay must NOT accept it as its output: the
        # independently regenerated execution differs, so replay fails.
        tampered_final = {"status": "tampered"}
        tampered_result = execution.results[0].model_copy(
            update={
                "final_state": tampered_final,
                "final_state_hash": state_hash(tampered_final),
            }
        )
        tampered_result = tampered_result.model_copy(
            update={"content_hash": state_trajectory_result_content_hash(tampered_result)}
        )
        tampered_execution = execution.model_copy(update={"results": (tampered_result,)})
        tampered_execution = tampered_execution.model_copy(
            update={"content_hash": run_trajectory_execution_content_hash(tampered_execution)}
        )
        store._run_trajectory_executions[(TENANT, run_id)] = tampered_execution
        with pytest.raises(TrajectoryReplayMismatchError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_replay_never_calls_legion(self) -> None:
        signature = inspect.signature(replay_run)
        assert list(signature.parameters) == ["store", "tenant_id", "run_id"]


class TestTamperedExecutionRejected:
    def _inject(
        self, store: InMemoryScenarioStore, run_id: str, execution: RunTrajectoryExecution
    ) -> None:
        store._run_trajectory_executions[(TENANT, run_id)] = execution

    def _replay_fails_integrity(self, store: InMemoryScenarioStore, run_id: str) -> None:
        with pytest.raises(RunTrajectoryExecutionIntegrityError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_tampered_state_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered_result = execution.results[0].model_copy(
            update={"initial_state": {"status": "tampered"}}
        )
        self._inject(store, run_id, execution.model_copy(update={"results": (tampered_result,)}))
        self._replay_fails_integrity(store, run_id)

    def test_tampered_result_identity_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered_result = execution.results[0].model_copy(
            update={"trajectory_plan_id": "trajectory-plan-ghost"}
        )
        self._inject(store, run_id, execution.model_copy(update={"results": (tampered_result,)}))
        self._replay_fails_integrity(store, run_id)

    def test_tampered_attempt_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_attempt = result.attempts[0].model_copy(update={"after_state_hash": HASH_64})
        tampered_result = result.model_copy(update={"attempts": (tampered_attempt,)})
        self._inject(store, run_id, execution.model_copy(update={"results": (tampered_result,)}))
        self._replay_fails_integrity(store, run_id)

    def test_tampered_result_hash_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered_result = execution.results[0].model_copy(update={"content_hash": HASH_64})
        self._inject(store, run_id, execution.model_copy(update={"results": (tampered_result,)}))
        self._replay_fails_integrity(store, run_id)

    def test_tampered_result_order_rejected(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        store, _ = build_trajectory_store(
            state_models=(model_1, model_2),
            transitions=(build_transition(model_1), build_transition(model_2)),
        )
        run_id = _run_ids(store)[0]
        execute_run(store=store, tenant_id=TENANT, run_id=run_id)
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        assert len(execution.results) == 2
        swapped = execution.model_copy(update={"results": tuple(reversed(execution.results))})
        self._inject(store, run_id, swapped)
        self._replay_fails_integrity(store, run_id)

    def test_tampered_plan_set_hash_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"trajectory_plan_set_hash": HASH_64})
        self._inject(store, run_id, tampered)
        self._replay_fails_integrity(store, run_id)

    def test_tampered_runtime_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"runtime_version": "1.0.0"})
        self._inject(store, run_id, tampered)
        self._replay_fails_integrity(store, run_id)

    def test_tampered_seed_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"scenario_seed_id": "seed-ghost"})
        self._inject(store, run_id, tampered)
        self._replay_fails_integrity(store, run_id)

    def test_self_consistent_tampering_still_rejected_by_regeneration(self) -> None:
        store, run_id = _executed_v2_store()
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        tampered_final = {"status": "tampered"}
        tampered_result = execution.results[0].model_copy(
            update={
                "final_state": tampered_final,
                "final_state_hash": state_hash(tampered_final),
            }
        )
        tampered_result = tampered_result.model_copy(
            update={"content_hash": state_trajectory_result_content_hash(tampered_result)}
        )
        tampered_execution = execution.model_copy(update={"results": (tampered_result,)})
        tampered_execution = tampered_execution.model_copy(
            update={"content_hash": run_trajectory_execution_content_hash(tampered_execution)}
        )
        # The record verification passes: every recomputed hash is
        # self-consistent. Only the authoritative regeneration catches it.
        self._inject(store, run_id, tampered_execution)
        with pytest.raises(TrajectoryReplayMismatchError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_missing_execution_rejected(self) -> None:
        store, run_id = _executed_v2_store()
        del store._run_trajectory_executions[(TENANT, run_id)]
        with pytest.raises(RunTrajectoryExecutionNotFoundError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        with pytest.raises(RunNotFoundError):
            store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RunTrajectoryReplayManifestNotFoundError):
            store.get_run_trajectory_replay_manifest(TENANT, run_id)


class TestRepeatedReplay:
    def test_repeated_replay_is_deterministic(self) -> None:
        store, run_id = _executed_v2_store()
        first = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        second = replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert first == second
        assert store.get_run_trajectory_replay_manifest(
            TENANT, run_id
        ) == store.get_run_trajectory_replay_manifest(TENANT, run_id)

    def test_replay_cannot_overwrite_a_different_manifest(self) -> None:
        from kalhas.application.domain_errors import RunTrajectoryReplayManifestConflictError

        store, run_id = _executed_v2_store()
        replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_run_trajectory_replay_manifest(TENANT, run_id)
        # Inject a genuinely different record directly into storage: a
        # different expected/recomputed execution hash.
        different = RunTrajectoryReplayManifest.model_validate(
            {
                **stored.model_dump(mode="python"),
                "expected_execution_hash": HASH_64,
                "recomputed_execution_hash": HASH_64,
            }
        )
        assert different != stored
        store._run_trajectory_replay_manifests[(TENANT, run_id)] = different
        with pytest.raises(RunTrajectoryReplayManifestConflictError):
            replay_run(store=store, tenant_id=TENANT, run_id=run_id)
        # The stored manifest was not overwritten.
        assert store.get_run_trajectory_replay_manifest(TENANT, run_id) == different
