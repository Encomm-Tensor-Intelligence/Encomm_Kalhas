"""Phase 25 observation-aware exact runtime-3 replay tests (Amendment 2).

Covers ``replay_realization_run``: successful exact replay (generic +
runtime-3 manifest pair, exact hashes and provenance, deterministic
timestamps), independent regeneration (builder spies, comparison-target
semantics, exactly-once input verification), the required prior
observation extraction (typed not-found, zero writes, no auto-extraction),
the full tamper matrix with zero-write proofs (input chain, execution,
self-consistently rehashed artifacts, observations, structural event
hash), the runtime-3 manifest verifier (every field parametrized, strict
revalidation, generic public messages, no mutation), pair
idempotency/asymmetry recovery (both/generic-only/runtime-3-only
identical states, conflicting or corrupt records blocked without
overwrite, partial-write recovery via a later identical replay), and the
gates/purity boundaries.
"""

from __future__ import annotations

import copy
import inspect
import subprocess
from typing import Any, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    ReplayHashMismatchError,
    RunInputIntegrityError,
    RunNotCompleteError,
    RunNotFoundError,
    TrajectoryReplayMismatchError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_errors import (
    RealizationReplayManifestConflictError,
    RealizationRunMetricObservationIntegrityError,
    RealizationRunMetricObservationNotFoundError,
    RealizationRunTrajectoryExecutionIntegrityError,
    RealizationRunTrajectoryReplayManifestConflictError,
    RealizationRunTrajectoryReplayManifestNotFoundError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_replay_manifest_content_hash,
    realization_run_trajectory_replay_manifest_identifier,
)
from kalhas.application.realization_integrity import (
    verify_realization_run_trajectory_replay_manifest_record,
)
from kalhas.application.realization_replay import replay_realization_run
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import (
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.state_transition_engine import state_hash
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import event_hash, execute_campaign
from kalhas.contracts.v1.execution import ReplayManifest
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryReplayManifest,
)

from tests.phase4_helpers import NOW, TENANT, prepare, start
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase25_helpers import (
    inject_unsupported_recorded_runtime,
    runtime_three_observation_store,
    runtime_three_store,
)


def _replay_ready_store() -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign with prior explicit extraction."""
    store = runtime_three_observation_store()
    for plan in store.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=store, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return store


def _first_run_id(store: InMemoryScenarioStore) -> str:
    return run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])


def _assert_no_manifests(store: InMemoryScenarioStore) -> None:
    assert not store._replay_manifests
    assert not store._realization_run_trajectory_replay_manifests


def _stored_manifest_pair(
    store: InMemoryScenarioStore, run_id: str
) -> tuple[ReplayManifest, RealizationRunTrajectoryReplayManifest]:
    generic = store.get_replay_manifest(TENANT, run_id)
    realization = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
    return generic, realization


class TestSuccessfulReplay:
    def test_replay_requires_complete_run_and_prior_extraction(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        manifest = replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert isinstance(manifest, ReplayManifest)
        assert manifest.run_id == run_id

    def test_stores_exactly_one_generic_and_one_runtime3_manifest(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert len(store._replay_manifests) == 1
        assert len(store._realization_run_trajectory_replay_manifests) == 1
        generic, realization = _stored_manifest_pair(store, run_id)
        assert generic.identifier == f"replay-{run_id}"
        assert realization.identifier == realization_run_trajectory_replay_manifest_identifier(
            run_id
        )

    def test_runtime_versions_exactly_three(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic, realization = _stored_manifest_pair(store, run_id)
        assert generic.runtime_version == "3.0.0"
        assert realization.runtime_version == "3.0.0"

    def test_structural_expected_hash_exact(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic, _ = _stored_manifest_pair(store, run_id)
        status = store.get_run_status(TENANT, run_id)
        assert generic.expected_event_hash == status.event_hash

    def test_execution_hashes_exact_and_equal(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization = _stored_manifest_pair(store, run_id)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        assert realization.expected_execution_hash == execution.content_hash
        assert realization.recomputed_execution_hash == execution.content_hash

    def test_observation_hashes_exact_and_equal(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization = _stored_manifest_pair(store, run_id)
        observations = store.get_realization_run_metric_observation_set(TENANT, run_id)
        assert realization.expected_observation_set_hash == observations.content_hash
        assert realization.recomputed_observation_set_hash == observations.content_hash

    def test_realization_execution_observation_and_plan_set_references_exact(
        self,
    ) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization = _stored_manifest_pair(store, run_id)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        observations = store.get_realization_run_metric_observation_set(TENANT, run_id)
        verified = verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)
        assert realization.realization_run_trajectory_execution_id == execution.identifier
        assert realization.realization_run_metric_observation_set_id == observations.identifier
        assert realization.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
        assert verified.realization is not None
        assert realization.world_realization_id == verified.realization.identifier
        assert realization.world_realization_content_hash == verified.realization.content_hash

    def test_replayed_at_and_created_at_from_run_plan(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic, realization = _stored_manifest_pair(store, run_id)
        run_plan = store.get_run_plans(TENANT, "campaign-1")[0]
        assert generic.created_at == run_plan.created_at
        assert realization.replayed_at == run_plan.created_at

    def test_runtime3_manifest_content_hash_exact_and_self_covering(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization = _stored_manifest_pair(store, run_id)
        assert realization.content_hash == realization_run_trajectory_replay_manifest_content_hash(
            realization
        )


class TestIndependentRegeneration:
    def test_execution_builder_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kalhas.application import realization_replay as replay_module
        from kalhas.application.realization_trajectory_runtime import (
            build_realization_run_trajectory_execution as original_builder,
        )

        store = _replay_ready_store()
        run_id = _first_run_id(store)
        calls = 0

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(replay_module, "build_realization_run_trajectory_execution", counting)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert calls == 1

    def test_observation_builder_receives_regenerated_execution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kalhas.application import realization_replay as replay_module
        from kalhas.application.realization_run_metric_observation_service import (
            build_realization_run_metric_observation_set as original_observation_builder,
        )
        from kalhas.application.realization_trajectory_runtime import (
            build_realization_run_trajectory_execution as original_execution_builder,
        )

        store = _replay_ready_store()
        run_id = _first_run_id(store)
        stored_execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        regenerated = {}

        def execution_spy(*args: Any, **kwargs: Any) -> Any:
            result = original_execution_builder(*args, **kwargs)
            regenerated["execution"] = result
            return result

        received = {}

        def observation_spy(*args: Any, **kwargs: Any) -> Any:
            received["execution"] = kwargs.get("execution")
            return original_observation_builder(*args, **kwargs)

        monkeypatch.setattr(
            replay_module, "build_realization_run_trajectory_execution", execution_spy
        )
        monkeypatch.setattr(
            replay_module, "build_realization_run_metric_observation_set", observation_spy
        )
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert "execution" in regenerated
        assert received["execution"] is regenerated["execution"]
        assert received["execution"] is not stored_execution

    def test_stored_execution_and_observations_are_comparison_targets_only(
        self,
    ) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        execution_before = copy.deepcopy(
            store.get_realization_run_trajectory_execution(TENANT, run_id)
        )
        observations_before = copy.deepcopy(
            store.get_realization_run_metric_observation_set(TENANT, run_id)
        )
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert store.get_realization_run_trajectory_execution(TENANT, run_id) == execution_before
        assert (
            store.get_realization_run_metric_observation_set(TENANT, run_id) == observations_before
        )

    def test_cached_stored_events_never_used_as_replay_output(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        events_before = copy.deepcopy(store.get_run_events(TENANT, run_id))
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert store.get_run_events(TENANT, run_id) == events_before
        # The manifest's expected hash is the independently recomputed one.
        recomputed = event_hash(events_before)
        stored_generic = store.get_replay_manifest(TENANT, run_id)
        assert stored_generic.expected_event_hash == recomputed

    def test_trajectory_inputs_verified_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kalhas.application import realization_replay as replay_module

        store = _replay_ready_store()
        run_id = _first_run_id(store)
        calls = 0
        original = verify_run_trajectory_inputs

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(replay_module, "verify_run_trajectory_inputs", counting)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert calls == 1

    def test_no_direct_run_scoped_verifier_import_or_call(self) -> None:
        from kalhas.application import realization_replay as replay_module

        source = inspect.getsource(replay_module)
        assert "verify_run_inputs" not in source
        assert "import input_integrity" not in source


class TestRequiredExtraction:
    def test_replay_before_extraction_raises_typed_not_found(self) -> None:
        store = runtime_three_observation_store()
        run_id = _first_run_id(store)
        with pytest.raises(RealizationRunMetricObservationNotFoundError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)
        assert not store._realization_run_metric_observation_sets


class TestTamperFailures:
    def test_tampered_input_provenance_rejected_zero_writes(self) -> None:
        store = _replay_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[0])
        tampered = plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_tampered_execution_rejected_zero_writes(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        store._realization_run_trajectory_executions[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationRunTrajectoryExecutionIntegrityError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_self_consistent_rehashed_execution_raises_replay_mismatch(self) -> None:
        from kalhas.application.realization_identity import (
            realization_run_trajectory_execution_content_hash,
        )
        from kalhas.application.realization_trajectory_runtime import (
            realized_state_trajectory_result_content_hash,
        )
        from kalhas.application.trajectory_integrity import _trace_hash

        store = _replay_ready_store()
        run_id = _first_run_id(store)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        result = execution.results[0]
        tampered_state = dict(result.final_state)
        level = cast(int, tampered_state["level"])
        tampered_state["level"] = level + 1
        attempts = list(result.attempts)
        attempts[-1] = attempts[-1].model_copy(
            update={"after_state_hash": state_hash(tampered_state)}
        )
        tampered_result = result.model_copy(
            update={
                "final_state": tampered_state,
                "final_state_hash": state_hash(tampered_state),
                "attempts": tuple(attempts),
            }
        )
        tampered_result = tampered_result.model_copy(
            update={"trace_hash": _trace_hash(tampered_result.attempts)}
        )
        tampered_result = tampered_result.model_copy(
            update={"content_hash": realized_state_trajectory_result_content_hash(tampered_result)}
        )
        tampered_execution = execution.model_copy(
            update={"results": (tampered_result,) + execution.results[1:]}
        )
        tampered_execution = tampered_execution.model_copy(
            update={
                "content_hash": realization_run_trajectory_execution_content_hash(
                    tampered_execution
                )
            }
        )
        store._realization_run_trajectory_executions[(TENANT, run_id)] = tampered_execution
        with pytest.raises(TrajectoryReplayMismatchError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_tampered_observation_rejected_zero_writes(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        observations = store.get_realization_run_metric_observation_set(TENANT, run_id)
        tampered = observations.model_copy(update={"content_hash": "f" * 64})
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_self_consistent_rehashed_observation_rejected(self) -> None:
        from kalhas.application.realization_identity import (
            realization_run_metric_observation_set_content_hash,
        )

        store = _replay_ready_store()
        run_id = _first_run_id(store)
        observations = store.get_realization_run_metric_observation_set(TENANT, run_id)
        value = observations.observations[0]
        tampered_value = value.model_copy(update={"raw_value": 999})
        tampered = observations.model_copy(
            update={"observations": (tampered_value,) + observations.observations[1:]}
        )
        tampered = tampered.model_copy(
            update={"content_hash": realization_run_metric_observation_set_content_hash(tampered)}
        )
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationRunMetricObservationIntegrityError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_structural_event_hash_mismatch_rejected(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        status = store.get_run_status(TENANT, run_id)
        store.put_run_status(
            TENANT,
            run_id,
            status.model_copy(update={"event_hash": "f" * 64}),
        )
        with pytest.raises(ReplayHashMismatchError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)


class TestManifestVerifier:
    def _verified_fixture(self) -> tuple[InMemoryScenarioStore, str, Any, Any, Any]:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        verified = verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        observations = store.get_realization_run_metric_observation_set(TENANT, run_id)
        return store, run_id, verified, execution, observations

    def test_correct_manifest_accepted(self) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        verify_realization_run_trajectory_replay_manifest_record(
            manifest,
            inputs=verified.inputs,
            execution=execution,
            observation_set=observations,
            plan_set_hash=execution.trajectory_plan_set_hash,
        )  # must not raise

    def test_wrong_object_and_validator_bypass_rejected(self) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            verify_realization_run_trajectory_replay_manifest_record(
                object(),
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )
        payload = manifest.model_dump(mode="python")
        payload["runtime_version"] = "2.0.0"
        bypassed = RealizationRunTrajectoryReplayManifest.model_construct(**payload)
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            verify_realization_run_trajectory_replay_manifest_record(
                bypassed,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )

    @pytest.mark.parametrize(
        "field",
        [
            "identifier",
            "tenant_id",
            "run_id",
            "campaign_id",
            "realization_run_trajectory_execution_id",
            "realization_run_metric_observation_set_id",
            "world_version_id",
            "strategy_candidate_id",
            "scenario_seed_id",
            "world_realization_id",
            "world_realization_content_hash",
            "runtime_version",
            "input_hash",
            "trajectory_plan_set_hash",
            "expected_execution_hash",
            "recomputed_execution_hash",
            "expected_observation_set_hash",
            "recomputed_observation_set_hash",
            "replay_classification",
            "replayed_at",
            "content_hash",
        ],
    )
    def test_every_manifest_field_tampering_rejected(self, field: str) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        if field == "replayed_at":
            tampered = manifest.model_copy(update={"replayed_at": NOW.replace(year=2020)})
        elif field == "replay_classification":
            tampered = manifest.model_copy(update={"replay_classification": "inexact"})
        else:
            tampered = manifest.model_copy(update={field: f"tampered-{field}"})
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            verify_realization_run_trajectory_replay_manifest_record(
                tampered,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )

    def test_self_consistent_tenant_tamper_rejected(self) -> None:
        """A rehashed foreign-tenant manifest fails the ownership check.

        Changes only ``tenant_id`` to another valid non-empty tenant and
        recomputes the self-covering content hash; the verifier must
        reject it independently of hashes, references, and any
        expected-manifest comparison.
        """
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        manifest_before = copy.deepcopy(manifest)
        inputs_before = copy.deepcopy(verified.inputs)
        execution_before = copy.deepcopy(execution)
        observations_before = copy.deepcopy(observations)

        tampered = manifest.model_copy(update={"tenant_id": "tenant-other"})
        tampered = tampered.model_copy(
            update={
                "content_hash": realization_run_trajectory_replay_manifest_content_hash(tampered)
            }
        )
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError) as exc_info:
            verify_realization_run_trajectory_replay_manifest_record(
                tampered,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )
        assert exc_info.value.reason == "replay manifest tenant ownership mismatch"
        message = str(exc_info.value)
        for leaked in (TENANT, "tenant-other", "f" * 64, "0" * 64):
            assert leaked not in message
        # Neither the manifest nor any authoritative argument was modified.
        assert manifest == manifest_before
        assert verified.inputs == inputs_before
        assert execution == execution_before
        assert observations == observations_before
        # The correct manifest remains accepted.
        verify_realization_run_trajectory_replay_manifest_record(
            manifest,
            inputs=verified.inputs,
            execution=execution,
            observation_set=observations,
            plan_set_hash=execution.trajectory_plan_set_hash,
        )  # must not raise

    def test_recomputed_hash_does_not_hide_wrong_references(self) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        tampered = manifest.model_copy(
            update={"realization_run_trajectory_execution_id": "execution-other"}
        )
        tampered = tampered.model_copy(
            update={
                "content_hash": realization_run_trajectory_replay_manifest_content_hash(tampered)
            }
        )
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            verify_realization_run_trajectory_replay_manifest_record(
                tampered,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )

    def test_public_messages_never_leak_values(self) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        tampered = manifest.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError) as exc_info:
            verify_realization_run_trajectory_replay_manifest_record(
                tampered,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )
        message = str(exc_info.value)
        assert "conflict" in message
        for leaked in ("f" * 64, "0" * 64, "m-1", "execution-other"):
            assert leaked not in message

    def test_verifier_never_mutates_or_repairs(self) -> None:
        store, run_id, verified, execution, observations = self._verified_fixture()
        manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        manifest_before = copy.deepcopy(manifest)
        tampered = manifest.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            verify_realization_run_trajectory_replay_manifest_record(
                tampered,
                inputs=verified.inputs,
                execution=execution,
                observation_set=observations,
                plan_set_hash=execution.trajectory_plan_set_hash,
            )
        stored_after = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert stored_after == manifest_before
        assert manifest == manifest_before


class TestPairIdempotency:
    def test_repeated_replay_returns_byte_identical_manifests(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        first = replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic_before, realization_before = _stored_manifest_pair(store, run_id)
        second = replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert second == first
        generic_after, realization_after = _stored_manifest_pair(store, run_id)
        assert generic_after == generic_before
        assert realization_after == realization_before

    def test_generic_only_state_completes_missing_runtime3_manifest(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic_before, _ = _stored_manifest_pair(store, run_id)
        del store._realization_run_trajectory_replay_manifests[(TENANT, run_id)]
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic_after, realization_after = _stored_manifest_pair(store, run_id)
        assert generic_after == generic_before
        assert (
            realization_after.identifier
            == realization_run_trajectory_replay_manifest_identifier(run_id)
        )

    def test_runtime3_only_state_completes_missing_generic_manifest(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization_before = _stored_manifest_pair(store, run_id)
        del store._replay_manifests[(TENANT, run_id)]
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic_after, realization_after = _stored_manifest_pair(store, run_id)
        assert generic_after.identifier == f"replay-{run_id}"
        assert realization_after == realization_before

    def test_differing_generic_manifest_blocks_without_overwrite(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic, realization = _stored_manifest_pair(store, run_id)
        tampered = generic.model_copy(update={"expected_event_hash": "f" * 64})
        store._replay_manifests[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationReplayManifestConflictError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_replay_manifest(TENANT, run_id)
        assert stored == tampered
        # The pre-existing identical runtime-3 manifest is untouched.
        assert store.get_realization_run_trajectory_replay_manifest(TENANT, run_id) == realization

    def test_differing_runtime3_manifest_blocks_without_overwrite(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _, realization = _stored_manifest_pair(store, run_id)
        tampered = realization.model_copy(update={"expected_execution_hash": "f" * 64})
        store._realization_run_trajectory_replay_manifests[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationRunTrajectoryReplayManifestConflictError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        stored = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        assert stored == tampered

    def test_second_write_failure_then_identical_replay_completes_pair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)

        def broken_put(
            tenant: str, rid: str, manifest: RealizationRunTrajectoryReplayManifest
        ) -> None:
            raise RuntimeError("synthetic second-write failure")

        monkeypatch.setattr(store, "put_realization_run_trajectory_replay_manifest", broken_put)
        with pytest.raises(RuntimeError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        # The first write completed; the pair is partial.
        generic_partial = store.get_replay_manifest(TENANT, run_id)
        with pytest.raises(RealizationRunTrajectoryReplayManifestNotFoundError):
            store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
        monkeypatch.undo()
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        generic_after, realization_after = _stored_manifest_pair(store, run_id)
        assert generic_after == generic_partial
        assert (
            realization_after.identifier
            == realization_run_trajectory_replay_manifest_identifier(run_id)
        )

    def test_existing_artifacts_unchanged_throughout(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        execution_before = copy.deepcopy(
            store.get_realization_run_trajectory_execution(TENANT, run_id)
        )
        observations_before = copy.deepcopy(
            store.get_realization_run_metric_observation_set(TENANT, run_id)
        )
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        assert store.get_realization_run_trajectory_execution(TENANT, run_id) == execution_before
        assert (
            store.get_realization_run_metric_observation_set(TENANT, run_id) == observations_before
        )


class TestGatesAndBoundaries:
    def test_non_complete_run_rejected(self) -> None:
        store = runtime_three_store()
        run_id = _first_run_id(store)
        with pytest.raises(RunNotCompleteError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    @pytest.mark.parametrize("runtime", ["1.0.0", "2.0.0"])
    def test_other_recorded_runtimes_rejected(self, runtime: str) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=runtime)
        if runtime == TRAJECTORY_RUNTIME_VERSION:
            prepare_strategy_trajectory_plans(
                store=store,
                legion=MockLegionAdapter(),
                tenant_id=TENANT,
                campaign_id="campaign-1",
            )
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        run_id = run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])
        with pytest.raises(UnsupportedRuntimeVersionError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = _replay_ready_store()
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        run_id = inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
        _assert_no_manifests(store)

    def test_foreign_tenant_and_unknown_run_isolated(self) -> None:
        store = _replay_ready_store()
        run_id = _first_run_id(store)
        with pytest.raises(RunNotFoundError):
            replay_realization_run(store=store, tenant_id="tenant-other", run_id=run_id)
        with pytest.raises(RunNotFoundError):
            replay_realization_run(store=store, tenant_id=TENANT, run_id="run-unknown")
        _assert_no_manifests(store)

    def test_module_is_pure(self) -> None:
        from kalhas.application import realization_replay as replay_module

        source = inspect.getsource(replay_module)
        assert "extract_realization_run_metric_observations(" not in source
        assert "execute_realization_run" not in source
        assert "evaluate_trajectory" not in source
        assert "kalhas.adapters" not in source
        assert "import random" not in source
        assert "datetime.now" not in source
        assert "time.time(" not in source
        assert "urllib" not in source
        assert "requests" not in source
        assert "socket" not in source
        assert "open(" not in source

    def test_runtime2_replay_service_source_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--exit-code",
                "--",
                "kalhas/application/replay_service.py",
                "kalhas/application/run_metric_observation_service.py",
                "kalhas/application/structural_runtime.py",
                "kalhas/application/run_trajectory_runtime.py",
                "kalhas/application/trajectory_integrity.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout
