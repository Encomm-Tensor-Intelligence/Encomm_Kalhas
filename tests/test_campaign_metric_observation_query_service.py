"""Phase 21 campaign metric-observation matrix query-service tests.

Proves ``get_verified_campaign_metric_observation_matrix`` returns the
complete deterministic strategy x shared-seed observation matrix of a
COMPLETE runtime-2.0.0 campaign only after the entire collection is
verified: the Phase 18 trajectory matrix is the authoritative layout
(obtained through the existing verified Phase 18 query service), and
every run's Phase 20 observation set is obtained through the existing
verified Phase 20 query path - one missing, foreign, corrupted, or
validator-bypassed set rejects the whole matrix atomically. Also proves
unknown/foreign campaigns (404 mapping), non-COMPLETE campaigns
(invalid-state mapping), legacy/unsupported runtime (conflict mapping),
missing/corrupted Phase 18 inputs preserving their existing typed
mappings, byte-identical repeated retrieval, deep-copy isolation, no
matrix storage, no automatic extraction, no execution/replay/repair/
lifecycle mutation, and a completely unchanged store snapshot.
"""

from __future__ import annotations

import copy

import pytest
from kalhas.application.campaign_metric_observation_query_service import (
    get_verified_campaign_metric_observation_matrix,
)
from kalhas.application.domain_errors import (
    CampaignMetricObservationMatrixIntegrityError,
    CampaignNotCompleteError,
    CampaignNotFoundError,
    CampaignTrajectoryMatrixIntegrityError,
    RunTrajectoryExecutionIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import LEGACY_STRUCTURAL_RUNTIME_VERSION
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_metric_observation import CampaignMetricObservationMatrix
from kalhas.contracts.v1.run_metric_observation import (
    RunMetricObservationSet,
    RunMetricObservationValue,
)
from pydantic import ValidationError

from tests.phase4_helpers import TENANT, build_seed, build_store, prepare, start
from tests.phase21_helpers import complete_observation_campaign

OTHER_TENANT = "tenant-other"


@pytest.fixture(scope="module")
def complete_store() -> tuple[InMemoryScenarioStore, tuple[str, ...]]:
    """A COMPLETE 5-strategy x 1-seed campaign with verified sets for every run."""
    store, _world_id, run_ids = complete_observation_campaign()
    return store, run_ids


@pytest.fixture()
def fresh_store() -> tuple[InMemoryScenarioStore, tuple[str, ...]]:
    """A fresh COMPLETE campaign for tampering tests (never shared)."""
    store, _world_id, run_ids = complete_observation_campaign()
    return store, run_ids


def _query(store: InMemoryScenarioStore) -> CampaignMetricObservationMatrix:
    return get_verified_campaign_metric_observation_matrix(
        store=store, tenant_id=TENANT, campaign_id="campaign-1"
    )


def _store_snapshot(store: InMemoryScenarioStore) -> object:
    """A deep snapshot of every store collection (safe with deepcopy)."""
    return copy.deepcopy(store.__dict__)


def _tampered_set(
    stored: RunMetricObservationSet,
    **updates: object,
) -> RunMetricObservationSet:
    return stored.model_copy(update=updates)


class TestValidQueries:
    def test_valid_completed_v2_campaign(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = complete_store
        matrix = _query(store)
        assert isinstance(matrix, CampaignMetricObservationMatrix)
        assert matrix.campaign_id == "campaign-1"
        assert matrix.runtime_version == "2.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.identifier.startswith("metric-observation-matrix-")
        assert len(matrix.content_hash) == 64
        assert matrix.assembled_at == store.get_campaign(TENANT, "campaign-1").created_at
        assert len(matrix.cells) == len(run_ids) == 5

    def test_multi_strategy_multi_seed_matrix(self) -> None:
        store, _world_id, run_ids = complete_observation_campaign(
            seeds=(build_seed(), build_seed(identifier="seed-2"))
        )
        matrix = _query(store)
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        seeds = store.get_campaign(TENANT, "campaign-1").seed_ensemble
        assert len(matrix.cells) == len(strategies) * len(seeds) == len(run_ids) == 10
        pairs = [(cell.strategy_position, cell.seed_position) for cell in matrix.cells]
        assert pairs == [
            (strategy_position, seed_position)
            for strategy_position in range(len(strategies))
            for seed_position in range(len(seeds))
        ]
        width = len(seeds)
        per_strategy = [
            [cell.scenario_seed_id for cell in matrix.cells[offset : offset + width]]
            for offset in range(0, len(matrix.cells), width)
        ]
        assert all(sequence == per_strategy[0] for sequence in per_strategy)
        assert per_strategy[0] == [seed.identifier for seed in seeds]

    def test_phase18_matrix_is_authoritative_layout(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        from kalhas.application.campaign_trajectory_query_service import (
            get_verified_campaign_trajectory_matrix,
        )

        store, _run_ids = complete_store
        matrix = _query(store)
        trajectory_matrix = get_verified_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.cells) == len(trajectory_matrix.cells)
        for cell, reference in zip(matrix.cells, trajectory_matrix.cells, strict=True):
            assert cell.sequence_position == reference.sequence_position
            assert cell.strategy_position == reference.strategy_position
            assert cell.seed_position == reference.seed_position
            assert cell.run_id == reference.run_id
            assert cell.run_plan_id == reference.run_plan_id
            assert cell.strategy_candidate_id == reference.strategy_candidate_id
            assert cell.scenario_seed_id == reference.scenario_seed_id
            assert cell.input_hash == reference.input_hash
            assert cell.trajectory_execution_id == reference.trajectory_execution_id
            assert (
                cell.trajectory_execution_content_hash
                == reference.trajectory_execution_content_hash
            )
        assert matrix.ordered_strategy_candidate_ids == (
            trajectory_matrix.ordered_strategy_candidate_ids
        )
        assert matrix.ordered_scenario_seed_ids == trajectory_matrix.ordered_scenario_seed_ids

    def test_phase20_verified_getter_used_for_every_run(
        self,
        complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import kalhas.application.campaign_metric_observation_query_service as query_module
        from kalhas.application.run_metric_observation_service import (
            get_verified_run_metric_observation_set as real_getter,
        )

        store, run_ids = complete_store
        called: list[str] = []

        def recording_getter(
            *, store: InMemoryScenarioStore, tenant_id: str, run_id: str
        ) -> RunMetricObservationSet:
            called.append(run_id)
            return real_getter(store=store, tenant_id=tenant_id, run_id=run_id)

        monkeypatch.setattr(
            query_module, "get_verified_run_metric_observation_set", recording_getter
        )
        matrix = _query(store)
        assert called == list(run_ids)
        for cell, run_id in zip(matrix.cells, called, strict=True):
            assert cell.run_id == run_id

    def test_empty_bindings_campaign_returns_all_empty_cells(self) -> None:
        store, _world_id, _run_ids = complete_observation_campaign(with_bindings=False)
        matrix = _query(store)
        assert matrix.ordered_metric_ids == ()
        assert len(matrix.cells) == 5
        assert all(cell.observations == () for cell in matrix.cells)

    def test_repeated_retrieval_is_byte_identical(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, _run_ids = complete_store
        first = _query(store)
        second = _query(store)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_returned_matrix_is_frozen_and_detached(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, _run_ids = complete_store
        matrix = _query(store)
        with pytest.raises(ValidationError):
            matrix.cells = ()
        again = _query(store)
        assert again == matrix
        assert again is not matrix


class TestRejections:
    def test_campaign_not_complete_rejected(self) -> None:
        store, _world_id, _run_ids = complete_observation_campaign(execute=False)
        assert store.get_campaign_status(TENANT, "campaign-1").state == CampaignState.RUNNING
        with pytest.raises(CampaignNotCompleteError):
            _query(store)

    def test_unknown_campaign_raises_typed_not_found(self) -> None:
        store, _world_id, _run_ids = complete_observation_campaign()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-unknown"
            )

    def test_foreign_tenant_campaign_indistinguishable_from_missing(self) -> None:
        store, _world_id, _run_ids = complete_observation_campaign()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_metric_observation_matrix(
                store=store, tenant_id=OTHER_TENANT, campaign_id="campaign-1"
            )

    def test_legacy_campaign_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id, runtime_version=LEGACY_STRUCTURAL_RUNTIME_VERSION)
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        with pytest.raises(UnsupportedRuntimeVersionError):
            _query(store)

    def test_unsupported_runtime_rejected(self) -> None:
        store, world_id = build_store()
        prepare(store, world_id, runtime_version="3.0.0")
        start(store)
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT,
            "campaign-1",
            status.model_copy(update={"state": CampaignState.COMPLETE}),
        )
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            _query(store)
        assert "3.0.0" in str(exc_info.value)

    def test_missing_observation_set_rejects_whole_matrix(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        del store._run_metric_observation_sets[(TENANT, run_ids[2])]
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)
        # Atomic: the remaining sets are untouched and no partial result
        # or matrix storage appeared.
        assert len(store._run_metric_observation_sets) == len(run_ids) - 1
        assert not hasattr(store, "_campaign_metric_observation_matrices")

    def test_corrupted_observation_set_rejects_whole_matrix(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = _tampered_set(
            stored, content_hash="1" * 64
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)

    def test_tampered_observation_value_rejects_whole_matrix(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        tampered_value = stored.observations[0].model_copy(update={"raw_value": 99})
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = _tampered_set(
            stored, observations=(tampered_value,) + stored.observations[1:]
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)

    def test_validator_bypassed_bool_raw_value_rejected(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        value_payload = stored.observations[0].model_dump(mode="python")
        value_payload["raw_value"] = True
        tampered_value = RunMetricObservationValue.model_construct(**value_payload)
        set_payload = stored.model_dump(mode="python")
        set_payload["observations"] = (tampered_value,) + stored.observations[1:]
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = (
            RunMetricObservationSet.model_construct(**set_payload)
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)

    def test_validator_bypassed_nan_raw_value_rejected(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        stored = store.get_run_metric_observation_set(TENANT, run_ids[0])
        value_payload = stored.observations[1].model_dump(mode="python")
        value_payload["raw_value"] = float("nan")
        tampered_value = RunMetricObservationValue.model_construct(**value_payload)
        set_payload = stored.model_dump(mode="python")
        set_payload["observations"] = stored.observations[:1] + (tampered_value,)
        store._run_metric_observation_sets[(TENANT, run_ids[0])] = (
            RunMetricObservationSet.model_construct(**set_payload)
        )
        with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
            _query(store)

    def test_failure_is_deterministic_and_never_partial(
        self, fresh_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = fresh_store
        del store._run_metric_observation_sets[(TENANT, run_ids[-1])]
        for _ in range(2):
            with pytest.raises(CampaignMetricObservationMatrixIntegrityError):
                _query(store)
        assert len(store._run_metric_observation_sets) == len(run_ids) - 1
        assert not hasattr(store, "_campaign_metric_observation_matrices")

    def test_missing_phase18_execution_preserves_existing_mapping(self) -> None:
        store, _world_id, run_ids = complete_observation_campaign()
        del store._run_trajectory_executions[(TENANT, run_ids[1])]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_corrupted_phase18_execution_preserves_existing_mapping(self) -> None:
        store, _world_id, run_ids = complete_observation_campaign()
        execution = store.get_run_trajectory_execution(TENANT, run_ids[0])
        store._run_trajectory_executions[(TENANT, run_ids[0])] = execution.model_copy(
            update={"world_content_hash": "f" * 64}
        )
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            _query(store)
        assert "f" * 64 not in str(exc_info.value)

    def test_missing_phase18_world_preserves_existing_mapping(self) -> None:
        store, world_id, _run_ids = complete_observation_campaign()
        del store._worlds[(TENANT, world_id)]
        del store._manifests[(TENANT, world_id)]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)


class TestReadOnlyBehavior:
    def test_query_never_triggers_extraction(
        self,
        complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import kalhas.application.run_metric_observation_service as service

        store, _run_ids = complete_store

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden extraction on the matrix query path")

        monkeypatch.setattr(service, "extract_run_metric_observations", boom)
        matrix = _query(store)
        assert matrix.campaign_id == "campaign-1"

    def test_query_never_calls_execution_replay_or_evaluation(
        self,
        complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import kalhas.application.replay_service as replay_service
        import kalhas.application.run_trajectory_runtime as runtime
        import kalhas.application.state_transition_engine as engine
        import kalhas.application.structural_runtime as structural_runtime

        store, _run_ids = complete_store

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden call on the matrix query path")

        monkeypatch.setattr(runtime, "build_run_trajectory_execution", boom)
        monkeypatch.setattr(replay_service, "replay_run", boom)
        monkeypatch.setattr(engine, "evaluate_trajectory", boom)
        monkeypatch.setattr(structural_runtime, "execute_run", boom)
        monkeypatch.setattr(structural_runtime, "execute_campaign", boom)

        matrix = _query(store)
        assert matrix.campaign_id == "campaign-1"

    def test_query_never_touches_legion_or_nexus(
        self,
        complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter

        store, _run_ids = complete_store

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden adapter call on the matrix query path")

        monkeypatch.setattr(MockLegionAdapter, "request_strategies", boom)
        monkeypatch.setattr(MockLegionAdapter, "request_trajectory_plan", boom)
        monkeypatch.setattr(MockNexusAdapter, "compile_scenario", boom)
        monkeypatch.setattr(MockNexusAdapter, "validate_scenario", boom)

        matrix = _query(store)
        assert matrix.campaign_id == "campaign-1"

    def test_no_matrix_storage_collection_exists(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, _run_ids = complete_store
        assert not hasattr(store, "_campaign_metric_observation_matrices")
        _query(store)
        assert not hasattr(store, "_campaign_metric_observation_matrices")

    def test_complete_store_snapshot_unchanged(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, _run_ids = complete_store
        before = _store_snapshot(store)
        _query(store)
        _query(store)
        assert _store_snapshot(store) == before

    def test_lifecycle_state_unchanged(
        self, complete_store: tuple[InMemoryScenarioStore, tuple[str, ...]]
    ) -> None:
        store, run_ids = complete_store
        status_before = store.get_campaign_status(TENANT, "campaign-1").model_dump(mode="json")
        run_states_before = {
            run_id: store.get_run_status(TENANT, run_id).model_dump(mode="json")
            for run_id in run_ids
        }
        _query(store)
        assert (
            store.get_campaign_status(TENANT, "campaign-1").model_dump(mode="json") == status_before
        )
        for run_id, state in run_states_before.items():
            assert store.get_run_status(TENANT, run_id).model_dump(mode="json") == state
