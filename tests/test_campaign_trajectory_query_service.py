"""Phase 18 campaign trajectory matrix query-service tests.

Proves ``get_verified_campaign_trajectory_matrix`` returns the complete
deterministic strategy x shared-seed matrix of a COMPLETE runtime-2.0.0
campaign only after the entire collection is verified through the
existing Phase 16/17 pipelines; that non-COMPLETE, unknown, foreign,
legacy, and unsupported campaigns fail with the typed errors; that a
missing or corrupted execution, corrupted run-plan matrix, candidate or
seed order drift, and missing or corrupted trajectory plans inside a
COMPLETE campaign are all atomic matrix integrity failures (no partial
matrix); that repeated retrieval is byte-identical and the returned
matrix is deep-copy isolated; that the query path performs no writes,
no execution, replay, evaluation, LEGION, or NEXUS calls; and that the
complete store snapshot stays unchanged.
"""

from __future__ import annotations

import copy

import pytest
from kalhas.application.campaign_trajectory_query_service import (
    get_verified_campaign_trajectory_matrix,
)
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    CampaignTrajectoryMatrixIntegrityError,
    RunInputIntegrityError,
    RunTrajectoryExecutionIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    run_identifier,
)
from kalhas.application.strategy_trajectory_service import (
    _preflight_run_plan_matrix,
    preflight_run_plan_matrix,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.transition import DomainStateTransition
from pydantic import ValidationError

from tests.phase4_helpers import TENANT, build_seed, build_store, prepare, start
from tests.phase16_helpers import build_model, build_trajectory_store, build_transition

OTHER_TENANT = "tenant-other"


def _complete_v2_store(
    *,
    models: tuple[DomainStateModel, ...] = (),
    transitions: tuple[DomainStateTransition, ...] = (),
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
) -> tuple[InMemoryScenarioStore, str]:
    store, world_id = build_trajectory_store(
        state_models=models, transitions=transitions, seeds=seeds
    )
    execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    return store, world_id


def _query(store: InMemoryScenarioStore) -> CampaignTrajectoryMatrix:
    return get_verified_campaign_trajectory_matrix(
        store=store, tenant_id=TENANT, campaign_id="campaign-1"
    )


def _store_snapshot(store: InMemoryScenarioStore) -> object:
    """A deep snapshot of every store collection (safe with deepcopy)."""
    return copy.deepcopy(store.__dict__)


class TestValidQueries:
    def test_valid_completed_v2_campaign(self) -> None:
        store, _ = _complete_v2_store()
        matrix = _query(store)
        assert isinstance(matrix, CampaignTrajectoryMatrix)
        assert matrix.campaign_id == "campaign-1"
        assert matrix.runtime_version == "2.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.assembled_at == store.get_campaign(TENANT, "campaign-1").created_at

    def test_multi_strategy_multi_seed_matrix(self) -> None:
        model = build_model()
        store, _ = _complete_v2_store(
            models=(model,),
            transitions=(build_transition(model),),
            seeds=(build_seed(), build_seed(identifier="seed-2")),
        )
        matrix = _query(store)
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        seeds = store.get_campaign(TENANT, "campaign-1").seed_ensemble
        assert len(matrix.cells) == len(strategies) * len(seeds)
        assert len(matrix.cells) == 10

    def test_exact_complete_cartesian_product(self) -> None:
        store, _ = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        matrix = _query(store)
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        seeds = store.get_campaign(TENANT, "campaign-1").seed_ensemble
        pairs = [(cell.strategy_position, cell.seed_position) for cell in matrix.cells]
        assert pairs == [
            (strategy_position, seed_position)
            for strategy_position in range(len(strategies))
            for seed_position in range(len(seeds))
        ]
        # Every strategy receives the identical ordered seed identifiers.
        width = len(seeds)
        per_strategy = [
            [cell.scenario_seed_id for cell in matrix.cells[offset : offset + width]]
            for offset in range(0, len(matrix.cells), width)
        ]
        assert all(sequence == per_strategy[0] for sequence in per_strategy)
        assert per_strategy[0] == [seed.identifier for seed in seeds]

    def test_empty_results_world_matrix_valid(self) -> None:
        store, _ = _complete_v2_store()
        matrix = _query(store)
        assert all(cell.result_content_hashes == () for cell in matrix.cells)

    def test_matrix_binds_every_cell_to_its_verified_execution(self) -> None:
        store, _ = _complete_v2_store()
        matrix = _query(store)
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        for cell, plan in zip(matrix.cells, run_plans, strict=True):
            execution = store.get_run_trajectory_execution(TENANT, run_identifier(plan))
            assert cell.run_id == run_identifier(plan)
            assert cell.run_plan_id == plan.identifier
            assert cell.input_hash == plan.input_hash
            assert cell.trajectory_execution_id == execution.identifier
            assert cell.trajectory_execution_content_hash == execution.content_hash
            assert cell.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
            assert cell.result_content_hashes == tuple(
                result.content_hash for result in execution.results
            )


class TestRejections:
    def test_campaign_not_complete_rejected(self) -> None:
        store, _ = build_trajectory_store()
        with pytest.raises(CampaignNotCompleteError):
            _query(store)

    def test_running_campaign_rejected(self) -> None:
        # build_trajectory_store leaves the campaign exactly RUNNING.
        store, _ = build_trajectory_store()
        assert store.get_campaign_status(TENANT, "campaign-1").state == CampaignState.RUNNING
        with pytest.raises(CampaignNotCompleteError):
            _query(store)

    def test_unknown_campaign_raises_typed_not_found(self) -> None:
        store, _ = build_trajectory_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-unknown"
            )

    def test_foreign_tenant_campaign_indistinguishable_from_missing(self) -> None:
        store, _ = _complete_v2_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_campaign_trajectory_matrix(
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
        # Force COMPLETE so the query reaches the recorded-runtime gate.
        status = store.get_campaign_status(TENANT, "campaign-1")
        store.update_campaign_status(
            TENANT,
            "campaign-1",
            status.model_copy(update={"state": CampaignState.COMPLETE}),
        )
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            _query(store)
        assert "3.0.0" in str(exc_info.value)

    def test_missing_execution_in_complete_campaign_is_integrity_failure(self) -> None:
        store, _ = _complete_v2_store()
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        del store._run_trajectory_executions[(TENANT, run_identifier(run_plans[2]))]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_corrupted_execution_rejected(self) -> None:
        store, _ = _complete_v2_store()
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(run_plans[0])
        execution = store.get_run_trajectory_execution(TENANT, run_id)
        store._run_trajectory_executions[(TENANT, run_id)] = execution.model_copy(
            update={"world_content_hash": "f" * 64}
        )
        with pytest.raises(RunTrajectoryExecutionIntegrityError) as exc_info:
            _query(store)
        assert "f" * 64 not in str(exc_info.value)

    def test_corrupted_run_plan_matrix_rejected(self) -> None:
        store, _ = _complete_v2_store()
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        tampered = run_plans[0].model_copy(update={"input_hash": "f" * 64})
        store._run_plans[(TENANT, "campaign-1")] = (tampered,) + run_plans[1:]
        with pytest.raises(RunInputIntegrityError):
            _query(store)

    def test_missing_run_plan_matrix_rejected(self) -> None:
        store, _ = _complete_v2_store()
        del store._run_plans[(TENANT, "campaign-1")]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_candidate_order_drift_rejected(self) -> None:
        store, _ = _complete_v2_store()
        candidates = list(store.get_strategy_candidates(TENANT, "campaign-1"))
        candidates[0], candidates[1] = candidates[1], candidates[0]
        store._strategy_candidates[(TENANT, "campaign-1")] = tuple(candidates)
        with pytest.raises(RunInputIntegrityError):
            _query(store)

    def test_seed_order_drift_rejected(self) -> None:
        store, _ = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        campaign = store.get_campaign(TENANT, "campaign-1")
        drifted = campaign.model_copy(update={"seed_ensemble": campaign.seed_ensemble[::-1]})
        store._campaigns[(TENANT, "campaign-1")] = drifted
        with pytest.raises(RunInputIntegrityError):
            _query(store)

    def test_missing_strategy_candidates_rejected(self) -> None:
        store, _ = _complete_v2_store()
        del store._strategy_candidates[(TENANT, "campaign-1")]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_missing_world_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        del store._worlds[(TENANT, world_id)]
        del store._manifests[(TENANT, world_id)]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_missing_trajectory_plans_in_complete_campaign_rejected(self) -> None:
        model = build_model()
        store, _ = _complete_v2_store(models=(model,), transitions=(build_transition(model),))
        del store._strategy_trajectory_plans[(TENANT, "campaign-1")]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_corrupted_trajectory_plan_collection_rejected(self) -> None:
        model = build_model()
        store, _ = _complete_v2_store(models=(model,), transitions=(build_transition(model),))
        plans = store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        tampered = plans[0].model_copy(update={"state_model_identifier": "state-model-foreign"})
        store._strategy_trajectory_plans[(TENANT, "campaign-1")] = (tampered,) + plans[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)

    def test_atomic_failure_never_returns_partial_matrix(self) -> None:
        store, _ = _complete_v2_store()
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        del store._run_trajectory_executions[(TENANT, run_identifier(run_plans[-1]))]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            _query(store)
        # The failure is atomic: no partial result was produced and the
        # store (which never receives the matrix) is unchanged.
        assert store.get_run_trajectory_execution(TENANT, run_identifier(run_plans[0])) is not None
        assert not hasattr(store, "_campaign_trajectory_matrices")


class TestIsolationAndDeterminism:
    def test_repeated_retrieval_is_byte_identical(self) -> None:
        store, _ = _complete_v2_store()
        first = _query(store)
        second = _query(store)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    def test_returned_matrix_is_frozen_and_detached(self) -> None:
        store, _ = _complete_v2_store()
        matrix = _query(store)
        with pytest.raises(ValidationError):
            matrix.cells = ()
        again = _query(store)
        assert again == matrix
        assert again is not matrix

    def test_complete_store_snapshot_unchanged(self) -> None:
        store, _ = _complete_v2_store()
        before = _store_snapshot(store)
        _query(store)
        _query(store)
        assert _store_snapshot(store) == before

    def test_public_preflight_alias_keeps_private_behavior(self) -> None:
        # The extracted public preflight is the exact same function the
        # private name used to be: existing call sites keep their
        # behavior and the new query reuses the same check.
        assert preflight_run_plan_matrix is _preflight_run_plan_matrix


class TestNoForbiddenCalls:
    def test_query_path_never_calls_execution_replay_or_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import kalhas.application.replay_service as replay_service
        import kalhas.application.run_trajectory_runtime as runtime
        import kalhas.application.state_transition_engine as engine
        import kalhas.application.structural_runtime as structural_runtime

        store, _ = _complete_v2_store()

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden call on the matrix query path")

        monkeypatch.setattr(runtime, "build_run_trajectory_execution", boom)
        monkeypatch.setattr(replay_service, "replay_run", boom)
        monkeypatch.setattr(engine, "evaluate_trajectory", boom)
        monkeypatch.setattr(structural_runtime, "execute_run", boom)
        monkeypatch.setattr(structural_runtime, "execute_campaign", boom)

        matrix = _query(store)
        assert matrix.campaign_id == "campaign-1"

    def test_query_path_never_touches_legion_or_nexus(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter

        store, _ = _complete_v2_store()

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden adapter call on the matrix query path")

        monkeypatch.setattr(MockLegionAdapter, "request_strategies", boom)
        monkeypatch.setattr(MockLegionAdapter, "request_trajectory_plan", boom)
        monkeypatch.setattr(MockNexusAdapter, "compile_scenario", boom)
        monkeypatch.setattr(MockNexusAdapter, "validate_scenario", boom)

        matrix = _query(store)
        assert matrix.campaign_id == "campaign-1"
