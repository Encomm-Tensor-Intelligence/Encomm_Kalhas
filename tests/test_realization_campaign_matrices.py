"""Phase 25 runtime-3 realization-aware campaign trajectory matrix tests.

Covers the pure ``build_realization_campaign_trajectory_matrix`` builder
(exact 5 x 2 = 10-cell matrix, exactly K aggregate realizations - never
K x S - with seed-aligned provenance, exact strategy-major/seed-minor
ordering, every cell bound to its exact RunPlan and verified execution,
recomputed seed-aligned realization-aware input hashes, deterministic
identifier/content hash/assembled_at, and the full direct-builder
adversarial matrix) and the verified read-only query
``get_verified_realization_campaign_trajectory_matrix`` (COMPLETE gate,
world snapshot verification, exactly-once matrix preflight, exactly-once
per-run input verification and execution verification, exactly-once
builder call only after all verification, byte-identical repeated
output, no partial matrix on any failure, strict read-only behavior,
tenant isolation, and non-leaking public errors).

The observation matrix (pure builder + verified read-only query, 10
cells over exactly K seed-aligned realizations with exact metric-id
collections, binding-provenance agreement, preserved raw values, and the
full direct-builder/verified-query adversarial matrix) is covered here as
well, together with the statistics matrix (pure builder + verified
read-only query, exact descriptive-statistics proofs through the frozen
Phase 22 functions, and the full direct-builder/verified-query
adversarial matrix). The causal 84/103 acceptance fixture (exactly two
strategies, exactly two seeds, exactly four runs, two genuinely
different declared trajectory plans, and real guarded transitions whose
final 84/103 values are produced by the real state-transition engine)
closes the module. APIs, mock differentiation, and documentation belong
to their own slices.
"""

from __future__ import annotations

import copy
import inspect
import math
import subprocess
import warnings
from datetime import timedelta
from typing import Any, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter, MockNexusAdapter
from kalhas.application.domain_errors import (
    CampaignNotCompleteError,
    CampaignNotFoundError,
    RunInputIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_metric_observation_query_service import (
    get_verified_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_metric_observation_runtime import (
    build_realization_campaign_metric_observation_matrix,
)
from kalhas.application.realization_campaign_metric_statistics_query_service import (
    get_verified_realization_campaign_metric_statistics,
)
from kalhas.application.realization_campaign_metric_statistics_runtime import (
    build_realization_campaign_metric_statistics_matrix,
)
from kalhas.application.realization_campaign_trajectory_query_service import (
    get_verified_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_campaign_trajectory_runtime import (
    build_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_errors import (
    RealizationCampaignMetricObservationMatrixIntegrityError,
    RealizationCampaignMetricStatisticsIntegrityError,
    RealizationCampaignTrajectoryMatrixIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_metric_observation_matrix_content_hash,
    realization_metric_observation_matrix_identifier,
    realization_metric_statistics_matrix_content_hash,
    realization_metric_statistics_matrix_identifier,
    realization_run_metric_observation_set_content_hash,
    realization_run_metric_observation_set_identifier,
    realization_trajectory_matrix_content_hash,
    realization_trajectory_matrix_identifier,
)
from kalhas.application.realization_replay import replay_realization_run
from kalhas.application.realization_run_metric_observation_service import (
    extract_realization_run_metric_observations,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
    run_realization_input_hash,
)
from kalhas.application.run_trajectory_inputs import verify_run_trajectory_inputs
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.realization_campaign_metric_observation import (
    RealizationCampaignMetricObservationMatrix,
)
from kalhas.contracts.v1.realization_campaign_metric_statistics import (
    RealizationCampaignMetricStatisticsMatrix,
)
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
)
from kalhas.contracts.v1.realization_run_metric_observation import (
    RealizationRunMetricObservationSet,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization

from tests.phase4_helpers import NOW, TENANT, build_seed, prepare, start
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase25_helpers import (
    ACCEPTANCE_BRANCH_X,
    ACCEPTANCE_BRANCH_Y,
    ACCEPTANCE_SEEDS,
    ACCEPTANCE_VALUE_X,
    ACCEPTANCE_VALUE_Y,
    acceptance_fixture_store,
    acceptance_observation_store,
    inject_unsupported_recorded_runtime,
    runtime_three_observation_store,
    runtime_three_store,
)

SEED_COUNT = 2
STRATEGY_COUNT = 5
CELL_COUNT = STRATEGY_COUNT * SEED_COUNT


def _matrix_ready_store() -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign (10 runs, executions stored)."""
    return runtime_three_observation_store()


def _first_run_id(store: InMemoryScenarioStore) -> str:
    return run_identifier(store.get_run_plans(TENANT, "campaign-1")[0])


def _verified_matrix_inputs(
    store: InMemoryScenarioStore,
) -> tuple[
    CampaignSpec,
    WorldVersion,
    tuple[StrategyCandidate, ...],
    tuple[RunPlan, ...],
    tuple[RealizationRunTrajectoryExecution, ...],
    tuple[WorldRealization, ...],
]:
    campaign = store.get_campaign(TENANT, "campaign-1")
    world = store.get_world(TENANT, campaign.world_version_id)
    strategies = store.get_strategy_candidates(TENANT, "campaign-1")
    run_plans = store.get_run_plans(TENANT, "campaign-1")
    executions = tuple(
        store.get_realization_run_trajectory_execution(TENANT, run_identifier(plan))
        for plan in run_plans
    )
    realizations: tuple[WorldRealization, WorldRealization] = (
        _require_realization(
            verify_run_trajectory_inputs(
                store=store, tenant_id=TENANT, run_id=run_identifier(run_plans[0])
            )
        ),
        _require_realization(
            verify_run_trajectory_inputs(
                store=store, tenant_id=TENANT, run_id=run_identifier(run_plans[1])
            )
        ),
    )
    return campaign, world, strategies, run_plans, executions, realizations


def _require_realization(verified: Any) -> WorldRealization:
    realization = verified.realization
    assert realization is not None
    return cast(WorldRealization, realization)


def _expect_rejection(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    strategies: tuple[StrategyCandidate, ...],
    seeds: tuple[ScenarioSeed, ...],
    run_plans: tuple[RunPlan, ...],
    executions: tuple[RealizationRunTrajectoryExecution, ...],
    realizations: tuple[WorldRealization, ...],
    error: type[Exception] = RealizationCampaignTrajectoryMatrixIntegrityError,
) -> None:
    with pytest.raises(error):
        build_realization_campaign_trajectory_matrix(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
            realizations=realizations,
        )


class TestHappyPath:
    def test_five_strategies_two_seeds_ten_cells(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.cells) == CELL_COUNT
        assert len(matrix.ordered_strategy_candidate_ids) == STRATEGY_COUNT
        assert len(matrix.ordered_scenario_seed_ids) == SEED_COUNT

    def test_exactly_two_aggregate_realizations_not_ten(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.ordered_world_realization_ids) == SEED_COUNT
        assert len(matrix.ordered_world_realization_content_hashes) == SEED_COUNT
        assert len(matrix.ordered_world_realization_ids) != CELL_COUNT

    def test_strategy_major_seed_minor_ordering(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        expected_pairs = [
            (strategy_position, seed_position)
            for strategy_position in range(STRATEGY_COUNT)
            for seed_position in range(SEED_COUNT)
        ]
        assert [
            (cell.strategy_position, cell.seed_position) for cell in matrix.cells
        ] == expected_pairs
        assert [cell.sequence_position for cell in matrix.cells] == list(range(CELL_COUNT))

    def test_same_seed_realization_across_all_five_strategies(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for seed_position in range(SEED_COUNT):
            seed_cells = [cell for cell in matrix.cells if cell.seed_position == seed_position]
            assert len(seed_cells) == STRATEGY_COUNT
            ids = {cell.world_realization_id for cell in seed_cells}
            hashes = {cell.world_realization_content_hash for cell in seed_cells}
            assert len(ids) == 1
            assert len(hashes) == 1
            assert ids.pop() == matrix.ordered_world_realization_ids[seed_position]
            assert hashes.pop() == matrix.ordered_world_realization_content_hashes[seed_position]

    def test_every_cell_binds_to_exact_run_plan_and_execution(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        for position, cell in enumerate(matrix.cells):
            plan = run_plans[position]
            execution = store.get_realization_run_trajectory_execution(TENANT, run_identifier(plan))
            assert cell.run_plan_id == plan.identifier
            assert cell.run_id == run_identifier(plan)
            assert cell.realization_run_trajectory_execution_id == execution.identifier
            assert cell.realization_run_trajectory_execution_content_hash == execution.content_hash
            assert cell.trajectory_plan_set_hash == execution.trajectory_plan_set_hash
            assert cell.result_content_hashes == tuple(
                result.content_hash for result in execution.results
            )

    def test_every_input_hash_recomputes_through_realization_hash(self) -> None:
        store = _matrix_ready_store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        seeds = campaign.seed_ensemble
        for cell in matrix.cells:
            recomputed = run_realization_input_hash(
                world_content_hash=world.content_hash,
                strategy=strategies[cell.strategy_position],
                seed=seeds[cell.seed_position],
                world_realization_content_hash=cell.world_realization_content_hash,
                runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
            )
            assert recomputed == cell.input_hash

    def test_identifier_content_hash_and_assembled_at_deterministic(self) -> None:
        store = _matrix_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.identifier == realization_trajectory_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        )
        assert matrix.content_hash == realization_trajectory_matrix_content_hash(matrix)
        assert matrix.assembled_at == campaign.created_at
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"

    def test_repeated_query_byte_identical_and_read_only(self) -> None:
        store = _matrix_ready_store()
        events_before = len(store._run_events)
        first = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second == first
        assert second.model_dump(mode="json") == first.model_dump(mode="json")
        # Strictly read-only: no new events, manifests, or artifacts.
        assert len(store._run_events) == events_before
        assert not store._realization_run_metric_observation_sets
        assert not store._replay_manifests
        assert not store._realization_run_trajectory_replay_manifests

    def test_inputs_and_stored_records_remain_unchanged(self) -> None:
        store = _matrix_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        executions = tuple(
            store.get_realization_run_trajectory_execution(TENANT, run_identifier(plan))
            for plan in run_plans
        )
        snapshots = (
            copy.deepcopy(campaign),
            copy.deepcopy(world),
            copy.deepcopy(strategies),
            copy.deepcopy(run_plans),
            copy.deepcopy(executions),
        )
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.get_campaign(TENANT, "campaign-1") == snapshots[0]
        assert store.get_world(TENANT, campaign.world_version_id) == snapshots[1]
        assert store.get_strategy_candidates(TENANT, "campaign-1") == snapshots[2]
        assert store.get_run_plans(TENANT, "campaign-1") == snapshots[3]
        for position, plan in enumerate(run_plans):
            assert (
                store.get_realization_run_trajectory_execution(TENANT, run_identifier(plan))
                == snapshots[4][position]
            )


class TestDirectBuilderAdversarial:
    @staticmethod
    def _inputs(store: InMemoryScenarioStore) -> tuple[Any, ...]:
        return _verified_matrix_inputs(store)

    def test_wrong_runtime_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, executions, realizations = self._inputs(store)
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        tampered_plans = tuple(
            plan.model_copy(update={"runtime_version": TRAJECTORY_RUNTIME_VERSION})
            for plan in run_plans
        )
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=tampered_plans,
            executions=executions,
            realizations=realizations,
            error=UnsupportedRuntimeVersionError,
        )

    @pytest.mark.parametrize("mode", ["missing", "additional", "reordered", "duplicated"])
    def test_run_plan_matrix_shape_rejected(self, mode: str) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, executions, realizations = self._inputs(store)
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        if mode == "missing":
            tampered = run_plans[:-1]
        elif mode == "additional":
            tampered = run_plans + (run_plans[0],)
        elif mode == "reordered":
            tampered = (run_plans[1], run_plans[0]) + run_plans[2:]
        else:
            tampered = (run_plans[0], run_plans[0]) + run_plans[2:]
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=tuple(tampered),
            executions=executions,
            realizations=realizations,
        )

    def test_strategy_and_seed_order_mismatch_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, executions, realizations = self._inputs(store)
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies[::-1],
            seeds=seeds,
            run_plans=store.get_run_plans(TENANT, "campaign-1"),
            executions=executions,
            realizations=realizations,
        )
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds[::-1],
            run_plans=store.get_run_plans(TENANT, "campaign-1"),
            executions=executions,
            realizations=realizations,
        )

    @pytest.mark.parametrize("mode", ["missing", "additional", "reordered", "duplicated"])
    def test_realization_collection_shape_rejected(self, mode: str) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, executions = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[4],
        )
        realizations = self._inputs(store)[5]
        if mode == "missing":
            tampered = realizations[:1]
        elif mode == "additional":
            tampered = realizations + realizations[:1]
        elif mode == "reordered":
            tampered = (realizations[1], realizations[0])
        else:
            tampered = (realizations[0], realizations[0])
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
            realizations=tuple(tampered),
        )

    def test_foreign_seed_and_foreign_world_realization_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, executions = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[4],
        )
        realizations = self._inputs(store)[5]
        foreign_seed = realizations[0].model_copy(update={"scenario_seed_id": "seed-foreign"})
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
            realizations=(foreign_seed, realizations[1]),
        )
        foreign_world = realizations[0].model_copy(update={"world_version_id": "world-other"})
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
            realizations=(foreign_world, realizations[1]),
        )

    def test_self_consistent_wrong_provenance_realization_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, executions = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[4],
        )
        realizations = self._inputs(store)[5]
        tampered = realizations[0].model_copy(update={"tenant_id": "tenant-other"})
        tampered = tampered.model_copy(
            update={"content_hash": world_realization_content_hash(tampered)}
        )
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
            realizations=(tampered, realizations[1]),
        )

    def test_execution_count_mismatch_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, realizations = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[5],
        )
        executions = self._inputs(store)[4]
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions[:-1],
            realizations=realizations,
        )

    @pytest.mark.parametrize(
        "field",
        [
            "tenant_id",
            "run_id",
            "run_plan_id",
            "campaign_id",
            "world_version_id",
            "world_content_hash",
            "strategy_candidate_id",
            "strategy_content_hash",
            "scenario_seed_id",
            "input_hash",
            "runtime_version",
            "identifier",
            "content_hash",
        ],
    )
    def test_execution_provenance_tamper_rejected(self, field: str) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, realizations = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[5],
        )
        executions = list(self._inputs(store)[4])
        executions[0] = executions[0].model_copy(update={field: f"tampered-{field}"})
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=tuple(executions),
            realizations=realizations,
        )

    def test_execution_realization_reference_tamper_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, realizations = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[5],
        )
        executions = list(self._inputs(store)[4])
        for field in ("world_realization_id", "world_realization_content_hash"):
            tampered = executions[0].model_copy(update={field: "f" * 64})
            _expect_rejection(
                campaign=campaign,
                world=world,
                strategies=strategies,
                seeds=seeds,
                run_plans=run_plans,
                executions=(tampered,) + tuple(executions[1:]),
                realizations=realizations,
            )

    def test_self_consistent_rehashed_execution_tamper_rejected(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, seeds, run_plans, realizations = (
            self._inputs(store)[0],
            self._inputs(store)[1],
            self._inputs(store)[2],
            self._inputs(store)[3],
            store.get_run_plans(TENANT, "campaign-1"),
            self._inputs(store)[5],
        )
        executions = list(self._inputs(store)[4])
        tampered = executions[0].model_copy(update={"tenant_id": "tenant-other"})
        from kalhas.application.realization_identity import (
            realization_run_trajectory_execution_content_hash,
        )

        tampered = tampered.model_copy(
            update={"content_hash": realization_run_trajectory_execution_content_hash(tampered)}
        )
        _expect_rejection(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=(tampered,) + tuple(executions[1:]),
            realizations=realizations,
        )

    def test_foreign_world_tenant_self_consistent_attack_rejected(self) -> None:
        """A foreign-tenant world with fully aligned hashes must be rejected.

        Changes only the world tenant and aligns every dependent record
        (realization tenants and content hashes, every affected RunPlan
        input hash, and execution input/realization/content hashes) so the
        shape is otherwise internally consistent - only the new
        campaign-world tenant binding can reject it.
        """
        from kalhas.application.realization_identity import (
            realization_run_trajectory_execution_content_hash,
        )

        store = _matrix_ready_store()
        campaign, world, strategies, run_plans, executions, realizations = self._inputs(store)
        seeds = campaign.seed_ensemble
        tampered_world = world.model_copy(update={"tenant_id": "tenant-other"})

        # Align realization tenants and recompute realization content hashes.
        tampered_realizations = tuple(
            realization.model_copy(update={"tenant_id": "tenant-other"})
            for realization in realizations
        )
        tampered_realizations = tuple(
            realization.model_copy(
                update={"content_hash": world_realization_content_hash(realization)}
            )
            for realization in tampered_realizations
        )

        # Recompute every affected RunPlan input hash.
        new_hashes: list[str] = []
        for position in range(len(run_plans)):
            strategy_position = position // len(seeds)
            seed_position = position % len(seeds)
            new_hashes.append(
                run_realization_input_hash(
                    world_content_hash=world.content_hash,
                    strategy=strategies[strategy_position],
                    seed=seeds[seed_position],
                    world_realization_content_hash=(
                        tampered_realizations[seed_position].content_hash
                    ),
                    runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
                )
            )
        tampered_plans = tuple(
            plan.model_copy(update={"input_hash": new_hashes[position]})
            for position, plan in enumerate(run_plans)
        )

        # Recompute execution input/realization/content hashes.
        tampered_executions: list[RealizationRunTrajectoryExecution] = []
        for position, execution in enumerate(executions):
            seed_position = position % len(seeds)
            tampered = execution.model_copy(
                update={
                    "input_hash": new_hashes[position],
                    "world_realization_id": (tampered_realizations[seed_position].identifier),
                    "world_realization_content_hash": (
                        tampered_realizations[seed_position].content_hash
                    ),
                }
            )
            tampered = tampered.model_copy(
                update={"content_hash": realization_run_trajectory_execution_content_hash(tampered)}
            )
            tampered_executions.append(tampered)

        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError) as exc_info:
            build_realization_campaign_trajectory_matrix(
                campaign=campaign,
                world=tampered_world,
                strategies=strategies,
                seeds=seeds,
                run_plans=tuple(tampered_plans),
                executions=tuple(tampered_executions),
                realizations=tampered_realizations,
            )
        assert exc_info.value.reason == "campaign world tenant mismatch"
        message = str(exc_info.value)
        for leaked in ("tenant-other", "tenant-1"):
            assert leaked not in message

    def test_alternate_seed_content_self_consistent_attack_rejected(self) -> None:
        """Alternate seed material with fully aligned hashes must be rejected.

        Retains the seed identifiers and tenants but changes every
        ``seed_value``, then recomputes the seed content hashes, the
        realization identifiers and content hashes, every affected RunPlan
        input hash, and execution input/realization/content hashes so the
        shape is otherwise internally consistent - only the exact campaign
        seed-content binding can reject it.
        """
        from kalhas.application.realization_identity import (
            realization_run_trajectory_execution_content_hash,
        )

        store = _matrix_ready_store()
        campaign, world, strategies, run_plans, executions, realizations = self._inputs(store)
        seeds = campaign.seed_ensemble
        tampered_seeds = tuple(
            seed.model_copy(update={"seed_value": f"{seed.seed_value}-alt"}) for seed in seeds
        )
        new_seed_hashes = [seed_content_hash(seed) for seed in tampered_seeds]

        # Recompute realization identifiers and content hashes.
        tampered_realizations: list[WorldRealization] = []
        for position, realization in enumerate(realizations):
            new_identifier = world_realization_identifier(
                world_version_id=realization.world_version_id,
                world_content_hash=realization.world_content_hash,
                scenario_seed_id=realization.scenario_seed_id,
                seed_content_hash_value=new_seed_hashes[position],
                uncertainty_model_id=realization.uncertainty_model_id,
                uncertainty_model_content_hash_value=(realization.uncertainty_model_content_hash),
                sampler_version=realization.sampler_version,
                quantization_policy=realization.quantization_policy,
                quantization_fraction_bits=realization.quantization_fraction_bits,
            )
            tampered = realization.model_copy(
                update={
                    "identifier": new_identifier,
                    "seed_content_hash": new_seed_hashes[position],
                }
            )
            tampered = tampered.model_copy(
                update={"content_hash": world_realization_content_hash(tampered)}
            )
            tampered_realizations.append(tampered)

        # Recompute every affected RunPlan input hash.
        new_hashes: list[str] = []
        for position in range(len(run_plans)):
            strategy_position = position // len(seeds)
            seed_position = position % len(seeds)
            new_hashes.append(
                run_realization_input_hash(
                    world_content_hash=world.content_hash,
                    strategy=strategies[strategy_position],
                    seed=tampered_seeds[seed_position],
                    world_realization_content_hash=(
                        tampered_realizations[seed_position].content_hash
                    ),
                    runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
                )
            )
        tampered_plans = tuple(
            plan.model_copy(update={"input_hash": new_hashes[position]})
            for position, plan in enumerate(run_plans)
        )

        # Recompute execution input/realization/content hashes.
        tampered_executions: list[RealizationRunTrajectoryExecution] = []
        for position, execution in enumerate(executions):
            seed_position = position % len(seeds)
            tampered = execution.model_copy(
                update={
                    "input_hash": new_hashes[position],
                    "world_realization_id": (tampered_realizations[seed_position].identifier),
                    "world_realization_content_hash": (
                        tampered_realizations[seed_position].content_hash
                    ),
                }
            )
            tampered = tampered.model_copy(
                update={"content_hash": realization_run_trajectory_execution_content_hash(tampered)}
            )
            tampered_executions.append(tampered)

        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError) as exc_info:
            build_realization_campaign_trajectory_matrix(
                campaign=campaign,
                world=world,
                strategies=strategies,
                seeds=tampered_seeds,
                run_plans=tuple(tampered_plans),
                executions=tuple(tampered_executions),
                realizations=tuple(tampered_realizations),
            )
        assert exc_info.value.reason == "seed ensemble content mismatch"
        message = str(exc_info.value)
        for leaked in ("seed", "-alt", "0" * 64):
            assert leaked not in message

    def test_no_input_mutation_on_rejection(self) -> None:
        store = _matrix_ready_store()
        campaign, world, strategies, run_plans, executions, realizations = self._inputs(store)
        seeds = campaign.seed_ensemble
        before = (
            copy.deepcopy(campaign),
            copy.deepcopy(world),
            copy.deepcopy(strategies),
            copy.deepcopy(seeds),
            copy.deepcopy(run_plans),
            copy.deepcopy(executions),
            copy.deepcopy(realizations),
        )
        tampered_plans = run_plans[:-1]
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError):
            build_realization_campaign_trajectory_matrix(
                campaign=campaign,
                world=world,
                strategies=strategies,
                seeds=seeds,
                run_plans=tampered_plans,
                executions=executions,
                realizations=realizations,
            )
        assert campaign == before[0]
        assert world == before[1]
        assert strategies == before[2]
        assert seeds == before[3]
        assert run_plans == before[4]
        assert executions == before[5]
        assert realizations == before[6]


class TestVerifiedQueryAdversarial:
    def test_non_complete_campaign_rejected(self) -> None:
        store = runtime_three_store()
        from kalhas.application.domain_errors import CampaignNotCompleteError

        with pytest.raises(CampaignNotCompleteError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("missing_index", [0, 4, 9])
    def test_missing_execution_prevents_any_matrix(self, missing_index: int) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[missing_index])
        del store._realization_run_trajectory_executions[(TENANT, run_id)]
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("corrupt_index", [0, 4, 9])
    def test_corrupt_execution_prevents_any_matrix(self, corrupt_index: int) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[corrupt_index])
        execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
        tampered = execution.model_copy(update={"content_hash": "f" * 64})
        store._realization_run_trajectory_executions[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_candidate_collection_mismatch_rejected(self) -> None:
        store = _matrix_ready_store()
        candidates = store.get_strategy_candidates(TENANT, "campaign-1")
        store._strategy_candidates[(TENANT, "campaign-1")] = candidates[:4]
        with pytest.raises(RunInputIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("mode", ["missing", "reordered", "duplicated", "tampered"])
    def test_run_plan_matrix_violations_rejected(self, mode: str) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        if mode == "missing":
            store._run_plans[(TENANT, "campaign-1")] = plans[:-1]
        elif mode == "reordered":
            store._run_plans[(TENANT, "campaign-1")] = (
                plans[1],
                plans[0],
            ) + plans[2:]
        elif mode == "duplicated":
            store._run_plans[(TENANT, "campaign-1")] = plans + (plans[0],)
        else:
            store._run_plans[(TENANT, "campaign-1")] = (
                plans[0].model_copy(update={"input_hash": "f" * 64}),
            ) + plans[1:]
        with pytest.raises(RunInputIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = _matrix_ready_store()
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_runtime_two_campaign_rejected(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        prepare_strategy_trajectory_plans(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_preflight_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _matrix_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )
        from kalhas.application.realization_campaign_service import (
            preflight_realization_run_plan_matrix as original_preflight,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_preflight(*args, **kwargs)

        monkeypatch.setattr(query_module, "preflight_realization_run_plan_matrix", counting)
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_input_verifier_called_exactly_once_per_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        calls = 0
        original = verify_run_trajectory_inputs
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(query_module, "verify_run_trajectory_inputs", counting)
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == len(plans)

    def test_execution_verifier_called_exactly_once_per_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        calls = 0
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )
        from kalhas.application.realization_integrity import (
            verify_realization_run_trajectory_execution_record as original_verifier,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_verifier(*args, **kwargs)

        monkeypatch.setattr(
            query_module, "verify_realization_run_trajectory_execution_record", counting
        )
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == len(plans)

    def test_builder_called_exactly_once_after_all_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _matrix_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )
        from kalhas.application.realization_campaign_trajectory_runtime import (
            build_realization_campaign_trajectory_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(query_module, "build_realization_campaign_trajectory_matrix", counting)
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_builder_never_called_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        del store._realization_run_trajectory_executions[(TENANT, run_identifier(plans[4]))]
        calls = 0
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )
        from kalhas.application.realization_campaign_trajectory_runtime import (
            build_realization_campaign_trajectory_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(query_module, "build_realization_campaign_trajectory_matrix", counting)
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert calls == 0

    def test_failures_are_read_only_and_never_partial(self) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        events_before = len(store._run_events)
        del store._realization_run_trajectory_executions[(TENANT, run_identifier(plans[9]))]
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert len(store._run_events) == events_before
        assert not store._realization_run_trajectory_replay_manifests
        assert not store._replay_manifests
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state is CampaignState.COMPLETE

    def test_tenant_isolation(self) -> None:
        store = _matrix_ready_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id="tenant-other", campaign_id="campaign-1"
            )
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-unknown"
            )

    def test_public_errors_never_leak_values(self) -> None:
        store = _matrix_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        execution = store.get_realization_run_trajectory_execution(TENANT, run_identifier(plans[0]))
        store._realization_run_trajectory_executions[(TENANT, run_identifier(plans[0]))] = (
            execution.model_copy(update={"content_hash": "f" * 64})
        )
        with pytest.raises(RealizationCampaignTrajectoryMatrixIntegrityError) as exc_info:
            get_verified_realization_campaign_trajectory_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        message = str(exc_info.value)
        assert "integrity" in message
        for leaked in ("f" * 64, "0" * 64, "seed-1", "m-1", "level"):
            assert leaked not in message


class TestPurity:
    def test_builder_and_query_are_pure_and_read_only(self) -> None:
        from kalhas.application import (
            realization_campaign_trajectory_query_service as query_module,
        )
        from kalhas.application import (
            realization_campaign_trajectory_runtime as runtime_module,
        )

        for module in (query_module, runtime_module):
            source = inspect.getsource(module)
            assert "kalhas.adapters" not in source
            assert "import random" not in source
            assert "datetime.now" not in source
            assert "time.time(" not in source
            assert "urllib" not in source
            assert "requests" not in source
            assert "socket" not in source
            assert "open(" not in source
        query_source = inspect.getsource(query_module)
        assert "put_" not in query_source
        assert "evaluate_trajectory" not in query_source
        assert "import replay" not in query_source
        assert "replay_service" not in query_source
        assert "import matrix" not in query_source

    def test_runtime2_and_phase24_sources_unchanged(self) -> None:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--exit-code",
                "--",
                "kalhas/application/campaign_trajectory_runtime.py",
                "kalhas/application/campaign_trajectory_query_service.py",
                "kalhas/application/run_trajectory_runtime.py",
                "kalhas/application/trajectory_integrity.py",
                "kalhas/application/replay_service.py",
                "kalhas/application/world_realization_builder.py",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stdout


# ---------------------------------------------------------------------------
# Runtime-3 realization-aware campaign metric-observation matrix
# ---------------------------------------------------------------------------


def _observation_ready_store(
    store: InMemoryScenarioStore | None = None,
) -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign with every run's observation set extracted.

    Explicitly extracts every run's observation set through the real
    extraction service before any observation-matrix query, so the
    verified query finds every set already stored.
    """
    effective = store if store is not None else _matrix_ready_store()
    for plan in effective.get_run_plans(TENANT, "campaign-1"):
        extract_realization_run_metric_observations(
            store=effective, tenant_id=TENANT, run_id=run_identifier(plan)
        )
    return effective


def _verified_observation_inputs(
    store: InMemoryScenarioStore,
) -> tuple[
    CampaignSpec,
    RealizationCampaignTrajectoryMatrix,
    tuple[RealizationRunMetricObservationSet, ...],
]:
    campaign = store.get_campaign(TENANT, "campaign-1")
    trajectory_matrix = get_verified_realization_campaign_trajectory_matrix(
        store=store, tenant_id=TENANT, campaign_id="campaign-1"
    )
    observation_sets = tuple(
        store.get_realization_run_metric_observation_set(TENANT, cell.run_id)
        for cell in trajectory_matrix.cells
    )
    return campaign, trajectory_matrix, observation_sets


def _expect_observation_rejection(
    *,
    campaign: CampaignSpec,
    trajectory_matrix: RealizationCampaignTrajectoryMatrix,
    observation_sets: tuple[RealizationRunMetricObservationSet, ...],
    error: type[Exception] = RealizationCampaignMetricObservationMatrixIntegrityError,
) -> None:
    with pytest.raises(error):
        build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )


def _differing_level_seeds() -> tuple[ScenarioSeed, ScenarioSeed]:
    """Two seeds whose realized levels differ, so m-1 raw values differ."""
    probe = _matrix_ready_store()
    campaign = probe.get_campaign(TENANT, "campaign-1")
    world = probe.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    plan = probe.get_run_plans(TENANT, "campaign-1")[0]
    realized_by_level: dict[int, ScenarioSeed] = {}
    for index in range(64):
        seed = build_seed(identifier=f"seed-scan-{index}")
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=plan.created_at,
        )
        level = next(
            override.value
            for override in realization.realized_initial_state_overrides
            if override.state_field_id == "level"
        )
        assert isinstance(level, int)
        realized_by_level.setdefault(level, seed)
        if len(realized_by_level) >= 2:
            break
    assert len(realized_by_level) >= 2, "expected two seeds with differing realized levels"
    values = list(realized_by_level.values())
    return values[0], values[1]


def _differing_raw_value_store() -> InMemoryScenarioStore:
    """A fully executed campaign whose two seeds realize different levels."""
    return _observation_ready_store(runtime_three_observation_store(seeds=_differing_level_seeds()))


class TestObservationMatrixHappyPath:
    def test_five_strategies_two_seeds_ten_cells(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.cells) == CELL_COUNT
        assert len(matrix.ordered_strategy_candidate_ids) == STRATEGY_COUNT
        assert len(matrix.ordered_scenario_seed_ids) == SEED_COUNT

    def test_exactly_two_seed_aligned_realizations_not_ten(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.ordered_world_realization_ids) == SEED_COUNT
        assert len(matrix.ordered_world_realization_content_hashes) == SEED_COUNT
        assert len(matrix.ordered_world_realization_ids) != CELL_COUNT

    def test_exact_ordered_metrics(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_metric_ids == ("m-1", "m-2")
        for cell in matrix.cells:
            assert [observation.metric_id for observation in cell.observations] == [
                "m-1",
                "m-2",
            ]

    def test_exact_trajectory_cell_order_and_references(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        trajectory_matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        expected_pairs = [
            (strategy_position, seed_position)
            for strategy_position in range(STRATEGY_COUNT)
            for seed_position in range(SEED_COUNT)
        ]
        assert [
            (cell.strategy_position, cell.seed_position) for cell in matrix.cells
        ] == expected_pairs
        assert [cell.sequence_position for cell in matrix.cells] == list(range(CELL_COUNT))
        for cell, trajectory_cell in zip(matrix.cells, trajectory_matrix.cells, strict=True):
            assert cell.run_id == trajectory_cell.run_id
            assert cell.run_plan_id == trajectory_cell.run_plan_id
            assert cell.strategy_candidate_id == trajectory_cell.strategy_candidate_id
            assert cell.scenario_seed_id == trajectory_cell.scenario_seed_id
            assert cell.input_hash == trajectory_cell.input_hash
            assert (
                cell.realization_run_trajectory_execution_id
                == trajectory_cell.realization_run_trajectory_execution_id
            )
            assert (
                cell.realization_run_trajectory_execution_content_hash
                == trajectory_cell.realization_run_trajectory_execution_content_hash
            )
            assert cell.world_realization_id == trajectory_cell.world_realization_id
            assert (
                cell.world_realization_content_hash
                == trajectory_cell.world_realization_content_hash
            )

    def test_exact_observation_set_references_and_content_hashes(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for cell in matrix.cells:
            assert (
                cell.realization_run_metric_observation_set_id
                == realization_run_metric_observation_set_identifier(
                    run_id=cell.run_id,
                    runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
                )
            )
            stored = store.get_realization_run_metric_observation_set(TENANT, cell.run_id)
            assert cell.realization_run_metric_observation_set_content_hash == stored.content_hash
            assert (
                cell.realization_run_metric_observation_set_content_hash
                == realization_run_metric_observation_set_content_hash(stored)
            )

    def test_same_seed_realization_across_all_five_strategies(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for seed_position in range(SEED_COUNT):
            seed_cells = [cell for cell in matrix.cells if cell.seed_position == seed_position]
            assert len(seed_cells) == STRATEGY_COUNT
            ids = {cell.world_realization_id for cell in seed_cells}
            hashes = {cell.world_realization_content_hash for cell in seed_cells}
            assert len(ids) == 1
            assert len(hashes) == 1
            assert ids.pop() == matrix.ordered_world_realization_ids[seed_position]
            assert hashes.pop() == matrix.ordered_world_realization_content_hashes[seed_position]

    def test_raw_values_preserved_exactly(self) -> None:
        store = _observation_ready_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for cell in matrix.cells:
            stored = store.get_realization_run_metric_observation_set(TENANT, cell.run_id)
            assert cell.observations == stored.observations

    def test_identifier_content_hash_and_assembled_at_deterministic(self) -> None:
        store = _observation_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.identifier == realization_metric_observation_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        )
        assert matrix.content_hash == realization_metric_observation_matrix_content_hash(matrix)
        assert matrix.assembled_at == campaign.created_at
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"

    def test_repeated_query_byte_identical_and_read_only(self) -> None:
        store = _observation_ready_store()
        events_before = len(store._run_events)
        sets_before = dict(store._realization_run_metric_observation_sets)
        first = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second == first
        assert second.model_dump(mode="json") == first.model_dump(mode="json")
        # Strictly read-only: no new events, manifests, or artifacts.
        assert len(store._run_events) == events_before
        assert store._realization_run_metric_observation_sets == sets_before
        assert not store._replay_manifests
        assert not store._realization_run_trajectory_replay_manifests

    def test_inputs_and_stored_records_remain_unchanged(self) -> None:
        store = _observation_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        trajectory_matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        observation_sets = tuple(
            store.get_realization_run_metric_observation_set(TENANT, cell.run_id)
            for cell in trajectory_matrix.cells
        )
        snapshots = (copy.deepcopy(campaign), copy.deepcopy(observation_sets))
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.get_campaign(TENANT, "campaign-1") == snapshots[0]
        for position, cell in enumerate(trajectory_matrix.cells):
            assert (
                store.get_realization_run_metric_observation_set(TENANT, cell.run_id)
                == snapshots[1][position]
            )

    def test_differing_legitimate_raw_values_remain_accepted(self) -> None:
        store = _differing_raw_value_store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        seed_zero_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 0
        }
        seed_one_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 1
        }
        assert len(seed_zero_values) == 1
        assert len(seed_one_values) == 1
        assert seed_zero_values != seed_one_values
        # The second metric (ratio) is untargeted and identical everywhere.
        assert {cell.observations[1].raw_value for cell in matrix.cells} == {0.0}


class TestObservationMatrixDirectBuilderAdversarial:
    @staticmethod
    def _inputs(store: InMemoryScenarioStore) -> tuple[Any, ...]:
        return _verified_observation_inputs(store)

    def test_wrong_trajectory_runtime_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = trajectory_matrix.model_copy(
            update={"runtime_version": TRAJECTORY_RUNTIME_VERSION}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=tampered,
            observation_sets=observation_sets,
            error=UnsupportedRuntimeVersionError,
        )

    def test_wrong_observation_runtime_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(
            update={"runtime_version": TRAJECTORY_RUNTIME_VERSION}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
            error=UnsupportedRuntimeVersionError,
        )

    def test_tampered_trajectory_matrix_identifier_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = trajectory_matrix.model_copy(update={"identifier": "tampered-matrix"})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=tampered,
            observation_sets=observation_sets,
        )

    def test_tampered_trajectory_matrix_content_hash_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = trajectory_matrix.model_copy(update={"content_hash": "f" * 64})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=tampered,
            observation_sets=observation_sets,
        )

    @pytest.mark.parametrize("mode", ["missing", "additional", "reordered", "duplicated"])
    def test_observation_set_collection_shape_rejected(self, mode: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        if mode == "missing":
            tampered = observation_sets[:-1]
        elif mode == "additional":
            tampered = observation_sets + (observation_sets[0],)
        elif mode == "reordered":
            tampered = (observation_sets[1], observation_sets[0]) + observation_sets[2:]
        else:
            tampered = (observation_sets[0], observation_sets[0]) + observation_sets[2:]
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=tuple(tampered),
        )

    @pytest.mark.parametrize(
        "field", ["tenant_id", "campaign_id", "scenario_id", "world_version_id"]
    )
    def test_self_consistent_trajectory_ownership_tamper_rejected(self, field: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = trajectory_matrix.model_copy(update={field: "tampered-matrix-field"})
        tampered = tampered.model_copy(
            update={"content_hash": realization_trajectory_matrix_content_hash(tampered)}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=tampered,
            observation_sets=observation_sets,
        )

    def test_campaign_strategy_and_seed_order_mismatch_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered_strategies = campaign.model_copy(
            update={"strategy_candidate_ids": tuple(reversed(campaign.strategy_candidate_ids))}
        )
        _expect_observation_rejection(
            campaign=tampered_strategies,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        seeds = campaign.seed_ensemble
        tampered_seeds = campaign.model_copy(update={"seed_ensemble": (seeds[1], seeds[0])})
        _expect_observation_rejection(
            campaign=tampered_seeds,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )

    @pytest.mark.parametrize(
        "field",
        [
            "tenant_id",
            "run_id",
            "run_plan_id",
            "campaign_id",
            "scenario_id",
            "world_version_id",
            "world_content_hash",
            "strategy_candidate_id",
            "scenario_seed_id",
            "input_hash",
        ],
    )
    def test_observation_set_provenance_tamper_rejected(self, field: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={field: "tampered-set-field"})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    @pytest.mark.parametrize(
        "field",
        [
            "realization_run_trajectory_execution_id",
            "realization_run_trajectory_execution_content_hash",
        ],
    )
    def test_execution_reference_tamper_rejected(self, field: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={field: "f" * 64})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    @pytest.mark.parametrize("field", ["world_realization_id", "world_realization_content_hash"])
    def test_realization_reference_tamper_rejected(self, field: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={field: "f" * 64})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    def test_observation_set_identifier_tamper_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={"identifier": "tampered-set"})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    def test_observation_set_content_hash_tamper_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={"content_hash": "f" * 64})
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    def test_self_consistent_rehashed_observation_tamper_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = observation_sets[0].model_copy(update={"tenant_id": "tenant-other"})
        tampered = tampered.model_copy(
            update={"content_hash": realization_run_metric_observation_set_content_hash(tampered)}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(tampered,) + tuple(observation_sets[1:]),
        )

    @pytest.mark.parametrize("mode", ["reordered", "missing"])
    def test_differing_metric_collections_rejected(self, mode: str) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        source = observation_sets[1]
        if mode == "reordered":
            observations = tuple(reversed(source.observations))
        else:
            observations = source.observations[:1]
        tampered = source.model_copy(update={"observations": observations})
        tampered = tampered.model_copy(
            update={"content_hash": realization_run_metric_observation_set_content_hash(tampered)}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(observation_sets[0], tampered) + tuple(observation_sets[2:]),
        )

    def test_binding_provenance_mismatch_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        source = observation_sets[1]
        tampered_observation = source.observations[0].model_copy(
            update={"binding_id": "binding-tampered"}
        )
        tampered = source.model_copy(
            update={"observations": (tampered_observation,) + source.observations[1:]}
        )
        tampered = tampered.model_copy(
            update={"content_hash": realization_run_metric_observation_set_content_hash(tampered)}
        )
        _expect_observation_rejection(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=(observation_sets[0], tampered) + tuple(observation_sets[2:]),
        )

    def test_differing_legitimate_raw_values_direct_builder(self) -> None:
        store = _differing_raw_value_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        matrix = build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        seed_zero_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 0
        }
        seed_one_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 1
        }
        assert seed_zero_values != seed_one_values

    def test_no_input_mutation_on_rejection(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        before = (
            copy.deepcopy(campaign),
            copy.deepcopy(trajectory_matrix),
            copy.deepcopy(observation_sets),
        )
        tampered_sets = observation_sets[:-1]
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            build_realization_campaign_metric_observation_matrix(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=tampered_sets,
            )
        assert campaign == before[0]
        assert trajectory_matrix == before[1]
        assert observation_sets == before[2]


class TestObservationMatrixVerifiedQueryAdversarial:
    def test_non_complete_campaign_rejected(self) -> None:
        store = runtime_three_store()
        with pytest.raises(CampaignNotCompleteError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_observations_not_previously_extracted_rejected(self) -> None:
        store = _matrix_ready_store()
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("missing_index", [0, 4, 9])
    def test_missing_observation_set_prevents_any_matrix(self, missing_index: int) -> None:
        store = _observation_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[missing_index])
        del store._realization_run_metric_observation_sets[(TENANT, run_id)]
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    @pytest.mark.parametrize("corrupt_index", [0, 4, 9])
    def test_corrupt_observation_set_prevents_any_matrix(self, corrupt_index: int) -> None:
        store = _observation_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[corrupt_index])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        tampered = stored.model_copy(update={"content_hash": "f" * 64})
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = tampered
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_runtime_two_campaign_rejected(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        prepare_strategy_trajectory_plans(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = _observation_ready_store()
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_tenant_isolation(self) -> None:
        store = _observation_ready_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id="tenant-other", campaign_id="campaign-1"
            )
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-unknown"
            )

    def test_trajectory_query_called_exactly_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _observation_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_query_service as query_module,
        )
        from kalhas.application.realization_campaign_trajectory_query_service import (
            get_verified_realization_campaign_trajectory_matrix as original_query,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_query(*args, **kwargs)

        monkeypatch.setattr(
            query_module,
            "get_verified_realization_campaign_trajectory_matrix",
            counting,
        )
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_observation_getter_called_exactly_once_per_cell(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _observation_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_query_service as query_module,
        )
        from kalhas.application.realization_run_metric_observation_service import (
            get_verified_realization_run_metric_observation_set as original_getter,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_getter(*args, **kwargs)

        monkeypatch.setattr(
            query_module,
            "get_verified_realization_run_metric_observation_set",
            counting,
        )
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == CELL_COUNT

    def test_builder_called_exactly_once_after_all_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _observation_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_query_service as query_module,
        )
        from kalhas.application.realization_campaign_metric_observation_runtime import (
            build_realization_campaign_metric_observation_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            query_module,
            "build_realization_campaign_metric_observation_matrix",
            counting,
        )
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_builder_never_called_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _observation_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        del store._realization_run_metric_observation_sets[(TENANT, run_identifier(plans[4]))]
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_query_service as query_module,
        )
        from kalhas.application.realization_campaign_metric_observation_runtime import (
            build_realization_campaign_metric_observation_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            query_module,
            "build_realization_campaign_metric_observation_matrix",
            counting,
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert calls == 0

    def test_failures_are_read_only_and_never_partial(self) -> None:
        store = _observation_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        events_before = len(store._run_events)
        sets_before = len(store._realization_run_metric_observation_sets)
        run_id = run_identifier(plans[9])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert len(store._run_events) == events_before
        assert len(store._realization_run_metric_observation_sets) == sets_before
        assert not store._realization_run_trajectory_replay_manifests
        assert not store._replay_manifests
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state is CampaignState.COMPLETE

    def test_public_errors_never_leak_values(self) -> None:
        store = _observation_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[0])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError) as exc_info:
            get_verified_realization_campaign_metric_observation_matrix(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        message = str(exc_info.value)
        assert "integrity" in message
        for leaked in ("f" * 64, "0" * 64, "seed-1", "m-1", "level", "units"):
            assert leaked not in message


class TestObservationMatrixPurity:
    def test_builder_and_query_are_pure_and_read_only(self) -> None:
        from kalhas.application import (
            realization_campaign_metric_observation_query_service as query_module,
        )
        from kalhas.application import (
            realization_campaign_metric_observation_runtime as runtime_module,
        )

        for module in (runtime_module, query_module):
            source = inspect.getsource(module)
            assert "kalhas.adapters" not in source
            assert "import random" not in source
            assert "datetime.now" not in source
            assert "time.time(" not in source
            assert "urllib" not in source
            assert "requests" not in source
            assert "socket" not in source
            assert "open(" not in source
        query_source = inspect.getsource(query_module)
        assert "put_" not in query_source
        assert "extract_realization_run_metric_observations" not in query_source
        assert "evaluate_trajectory" not in query_source
        assert "import replay" not in query_source
        assert "replay_service" not in query_source
        assert "import matrix" not in query_source


class TestObservationMatrixTrustBoundary:
    """Corrective micro-slice: strict trust-boundary verification of the pure builder.

    An independent review reproduced three direct-builder fail-open cases (foreign
    trajectory-result provenance, validator-bypassed raw values, and a
    shifted observed_at), each self-consistently rehashed. The corrected
    builder strictly revalidates every supplied artifact against its
    complete contract immediately after the runtime gates, requires the
    set's ``observed_at`` to equal the campaign ``created_at``, requires
    every observation's trajectory-result content hash to be a member of
    its trajectory cell's ordered result content hashes, and converts any
    construction-time validation/index/attribute failure into the typed
    matrix integrity error.
    """

    @staticmethod
    def _inputs(store: InMemoryScenarioStore) -> tuple[Any, ...]:
        return _verified_observation_inputs(store)

    @staticmethod
    def _rehashed_set(
        observation_set: RealizationRunMetricObservationSet,
    ) -> RealizationRunMetricObservationSet:
        """Recompute the content hash of a tampered set (two-step copy)."""
        return observation_set.model_copy(
            update={
                "content_hash": realization_run_metric_observation_set_content_hash(observation_set)
            }
        )

    @staticmethod
    def _tampered_observation_set(
        observation_set: RealizationRunMetricObservationSet,
        *,
        observation_position: int,
        **updates: Any,
    ) -> RealizationRunMetricObservationSet:
        tampered_observation = observation_set.observations[observation_position].model_copy(
            update=updates
        )
        replaced = observation_set.model_copy(
            update={
                "observations": (
                    observation_set.observations[:observation_position]
                    + (tampered_observation,)
                    + observation_set.observations[observation_position + 1 :]
                )
            }
        )
        return TestObservationMatrixTrustBoundary._rehashed_set(replaced)

    def _expect_rejection(
        self,
        campaign: CampaignSpec,
        trajectory_matrix: RealizationCampaignTrajectoryMatrix,
        observation_sets: tuple[RealizationRunMetricObservationSet, ...],
        *,
        reason: str | None = None,
        error: type[Exception] = RealizationCampaignMetricObservationMatrixIntegrityError,
    ) -> None:
        with pytest.raises(error) as exc_info:
            build_realization_campaign_metric_observation_matrix(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=observation_sets,
            )
        if reason is not None:
            assert cast(Any, exc_info.value).reason == reason

    def test_foreign_trajectory_result_hash_attack_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = self._tampered_observation_set(
            observation_sets[1],
            observation_position=0,
            trajectory_result_content_hash="f" * 64,
        )
        self._expect_rejection(
            campaign,
            trajectory_matrix,
            (observation_sets[0], tampered) + tuple(observation_sets[2:]),
            reason="observation trajectory result reference mismatch",
        )

    def test_raw_value_bool_integer_kind_attack_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        # m-1 (level) is the integer-kind metric; a validator-bypassed
        # boolean must fail the strict contract revalidation.
        tampered = self._tampered_observation_set(
            observation_sets[1], observation_position=0, raw_value=True
        )
        self._expect_rejection(
            campaign,
            trajectory_matrix,
            (observation_sets[0], tampered) + tuple(observation_sets[2:]),
            reason="observation set violates its contract",
        )

    def test_raw_value_non_finite_attack_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        # m-2 (ratio) is the number-kind metric; a non-finite float must
        # fail the strict contract revalidation.
        tampered = self._tampered_observation_set(
            observation_sets[1], observation_position=1, raw_value=float("inf")
        )
        self._expect_rejection(
            campaign,
            trajectory_matrix,
            (observation_sets[0], tampered) + tuple(observation_sets[2:]),
            reason="observation set violates its contract",
        )

    def test_observed_at_shift_attack_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        shifted = observation_sets[1].model_copy(
            update={"observed_at": observation_sets[1].observed_at + timedelta(days=1)}
        )
        tampered = self._rehashed_set(shifted)
        self._expect_rejection(
            campaign,
            trajectory_matrix,
            (observation_sets[0], tampered) + tuple(observation_sets[2:]),
            reason="observation set observed_at mismatch",
        )

    def test_self_consistent_invalid_cell_position_rejected(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered_cells = (
            trajectory_matrix.cells[0].model_copy(update={"strategy_position": 99}),
        ) + tuple(trajectory_matrix.cells[1:])
        tampered_matrix = trajectory_matrix.model_copy(update={"cells": tampered_cells})
        tampered_matrix = tampered_matrix.model_copy(
            update={"content_hash": realization_trajectory_matrix_content_hash(tampered_matrix)}
        )
        # The typed matrix integrity error is raised - never a raw
        # IndexError or ValidationError.
        self._expect_rejection(
            campaign,
            tampered_matrix,
            observation_sets,
        )

    def test_rehashed_wrong_runtime_still_unsupported(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = self._rehashed_set(
            observation_sets[1].model_copy(update={"runtime_version": TRAJECTORY_RUNTIME_VERSION})
        )
        # The explicit runtime gate fires before any revalidation, so the
        # typed unsupported-version error is preserved even when the set
        # is self-consistently rehashed.
        self._expect_rejection(
            campaign,
            trajectory_matrix,
            (observation_sets[0], tampered) + tuple(observation_sets[2:]),
            error=UnsupportedRuntimeVersionError,
        )

    def test_correct_result_hashes_remain_accepted(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        matrix = build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        for cell, trajectory_cell in zip(matrix.cells, trajectory_matrix.cells, strict=True):
            for observation in cell.observations:
                assert (
                    observation.trajectory_result_content_hash
                    in trajectory_cell.result_content_hashes
                )

    def test_differing_legitimate_raw_values_still_accepted(self) -> None:
        store = _differing_raw_value_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        matrix = build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        seed_zero_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 0
        }
        seed_one_values = {
            cell.observations[0].raw_value for cell in matrix.cells if cell.seed_position == 1
        }
        assert seed_zero_values != seed_one_values

    def test_trust_boundary_checks_precede_cell_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        tampered = self._tampered_observation_set(
            observation_sets[1],
            observation_position=0,
            trajectory_result_content_hash="f" * 64,
        )
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_runtime as runtime_module,
        )

        original = runtime_module._construct_matrix

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime_module, "_construct_matrix", counting)
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            build_realization_campaign_metric_observation_matrix(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(observation_sets[0], tampered) + tuple(observation_sets[2:]),
            )
        # The trust-boundary rejection happens before any matrix-cell
        # construction.
        assert calls == 0

    def test_construction_runs_exactly_once_on_valid_inputs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_observation_runtime as runtime_module,
        )

        original = runtime_module._construct_matrix

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime_module, "_construct_matrix", counting)
        matrix = build_realization_campaign_metric_observation_matrix(
            campaign=campaign,
            trajectory_matrix=trajectory_matrix,
            observation_sets=observation_sets,
        )
        assert calls == 1
        assert matrix.content_hash == realization_metric_observation_matrix_content_hash(matrix)

    def test_no_input_mutation_on_trust_boundary_rejection(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        before = (
            copy.deepcopy(campaign),
            copy.deepcopy(trajectory_matrix),
            copy.deepcopy(observation_sets),
        )
        tampered = self._tampered_observation_set(
            observation_sets[1],
            observation_position=0,
            trajectory_result_content_hash="f" * 64,
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            build_realization_campaign_metric_observation_matrix(
                campaign=campaign,
                trajectory_matrix=trajectory_matrix,
                observation_sets=(observation_sets[0], tampered) + tuple(observation_sets[2:]),
            )
        assert campaign == before[0]
        assert trajectory_matrix == before[1]
        assert observation_sets == before[2]

    def test_public_errors_never_leak_values_direct_builder(self) -> None:
        store = _observation_ready_store()
        campaign, trajectory_matrix, observation_sets = self._inputs(store)
        attackers = (
            self._tampered_observation_set(
                observation_sets[1], observation_position=0, raw_value=True
            ),
            self._tampered_observation_set(
                observation_sets[1], observation_position=1, raw_value=float("inf")
            ),
            self._rehashed_set(
                observation_sets[1].model_copy(
                    update={"observed_at": observation_sets[1].observed_at + timedelta(days=1)}
                )
            ),
        )
        for tampered in attackers:
            with pytest.raises(
                RealizationCampaignMetricObservationMatrixIntegrityError
            ) as exc_info:
                build_realization_campaign_metric_observation_matrix(
                    campaign=campaign,
                    trajectory_matrix=trajectory_matrix,
                    observation_sets=(observation_sets[0], tampered) + tuple(observation_sets[2:]),
                )
            message = str(exc_info.value)
            assert "integrity" in message
            for leaked in ("True", "inf", "f" * 64, "0" * 64, "m-1", "level", "units", "2026"):
                assert leaked not in message


# ---------------------------------------------------------------------------
# Runtime-3 realization-aware campaign metric-statistics matrix
# ---------------------------------------------------------------------------


def _statistics_ready_store() -> InMemoryScenarioStore:
    """A fully executed runtime-3 campaign with every observation set extracted."""
    return _observation_ready_store()


def _verified_statistics_inputs(store: InMemoryScenarioStore) -> tuple[Any, ...]:
    """The completely verified source observation matrix of a statistics-ready store."""
    observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
        store=store, tenant_id=TENANT, campaign_id="campaign-1"
    )
    return (observation_matrix,)


def _statistics_rehash(
    matrix: RealizationCampaignMetricObservationMatrix,
) -> RealizationCampaignMetricObservationMatrix:
    """Recompute the self-covering content hash over tampered content (two-step copy)."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
        )
        digest = realization_metric_observation_matrix_content_hash(matrix)
    return matrix.model_copy(update={"content_hash": digest})


def _statistics_self_consistent_copy(
    matrix: RealizationCampaignMetricObservationMatrix,
    **updates: object,
) -> RealizationCampaignMetricObservationMatrix:
    """A ``model_copy``-tampered matrix with a recomputed self-covering hash."""
    return _statistics_rehash(matrix.model_copy(update=updates))


def _statistics_replace_cell(
    matrix: RealizationCampaignMetricObservationMatrix,
    cell_index: int,
    *,
    observations: tuple[object, ...] | None = None,
    **overrides: object,
) -> RealizationCampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one cell replaced."""
    cell = matrix.cells[cell_index]
    if observations is None:
        observations = cell.observations
    replaced = cell.model_copy(update={"observations": observations, **overrides})
    tampered = matrix.model_copy(
        update={"cells": matrix.cells[:cell_index] + (replaced,) + matrix.cells[cell_index + 1 :]}
    )
    return _statistics_rehash(tampered)


def _statistics_tamper_observation(
    matrix: RealizationCampaignMetricObservationMatrix,
    cell_index: int,
    metric_position: int,
    **updates: object,
) -> RealizationCampaignMetricObservationMatrix:
    """A self-consistent matrix copy with one observation's fields replaced.

    ``model_copy`` bypasses the nested observation validators, which is
    exactly how validator-bypassed raw values (bool, NaN, Infinity, huge
    integers, wrong kinds) are injected for defense-in-depth tests.
    """
    cell = matrix.cells[cell_index]
    observations = list(cell.observations)
    observations[metric_position] = observations[metric_position].model_copy(update=updates)
    return _statistics_replace_cell(matrix, cell_index, observations=tuple(observations))


def _expect_statistics_rejection(
    observation_matrix: RealizationCampaignMetricObservationMatrix,
    *,
    error: type[Exception] = RealizationCampaignMetricStatisticsIntegrityError,
    reason: str | None = None,
) -> None:
    with pytest.raises(error) as exc_info:
        build_realization_campaign_metric_statistics_matrix(observation_matrix=observation_matrix)
    if reason is not None:
        assert cast(Any, exc_info.value).reason == reason


def _seeds_with_levels(*levels: int) -> tuple[ScenarioSeed, ...]:
    """Scan candidate seeds until one is found for every requested realized level.

    Returns the seeds ordered exactly by the requested level order, so a
    campaign built on them yields deterministic raw level values in the
    exact seed order.
    """
    probe = _matrix_ready_store()
    campaign = probe.get_campaign(TENANT, "campaign-1")
    world = probe.get_world(TENANT, campaign.world_version_id)
    catalog = extract_world_catalog(world)
    plan = probe.get_run_plans(TENANT, "campaign-1")[0]
    found: dict[int, ScenarioSeed] = {}
    for index in range(256):
        seed = build_seed(identifier=f"seed-statistics-{index}")
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=catalog.uncertainty_model,
            seed=seed,
            realized_at=plan.created_at,
        )
        level = next(
            override.value
            for override in realization.realized_initial_state_overrides
            if override.state_field_id == "level"
        )
        assert isinstance(level, int)
        if level in levels and level not in found:
            found[level] = seed
        if len(found) == len(levels):
            break
    assert len(found) == len(levels), f"expected seeds for levels {levels}"
    return tuple(found[level] for level in levels)


def _statistics_store_with_seeds(seeds: tuple[ScenarioSeed, ...]) -> InMemoryScenarioStore:
    """A fully executed campaign with a custom seed ensemble and extracted observation sets."""
    return _observation_ready_store(runtime_three_observation_store(seeds=cast(Any, seeds)))


class TestStatisticsMatrixHappyPath:
    def test_five_strategies_two_metrics_ten_summaries(self) -> None:
        store = _statistics_ready_store()
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.summaries) == STRATEGY_COUNT * 2
        assert len(matrix.ordered_strategy_candidate_ids) == STRATEGY_COUNT
        assert matrix.ordered_metric_ids == ("m-1", "m-2")

    def test_every_summary_has_exactly_two_seed_ordered_values(self) -> None:
        store = _statistics_ready_store()
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for summary in matrix.summaries:
            assert len(summary.ordered_observed_values) == SEED_COUNT
            assert summary.observation_count == SEED_COUNT

    def test_exact_strategy_major_metric_minor_order(self) -> None:
        store = _statistics_ready_store()
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        expected_pairs = [
            (strategy_position, metric_position)
            for strategy_position in range(STRATEGY_COUNT)
            for metric_position in range(2)
        ]
        assert [
            (summary.strategy_position, summary.metric_position) for summary in matrix.summaries
        ] == expected_pairs
        assert [summary.strategy_candidate_id for summary in matrix.summaries] == [
            matrix.ordered_strategy_candidate_ids[strategy_position]
            for strategy_position, _metric_position in expected_pairs
        ]
        assert [summary.metric_id for summary in matrix.summaries] == [
            "m-1",
            "m-2",
        ] * STRATEGY_COUNT

    def test_exact_source_matrix_identity_and_tuples_preserved(self) -> None:
        store = _statistics_ready_store()
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.source_metric_observation_matrix_id == observation_matrix.identifier
        assert (
            matrix.source_metric_observation_matrix_content_hash == observation_matrix.content_hash
        )
        assert matrix.tenant_id == observation_matrix.tenant_id
        assert matrix.campaign_id == observation_matrix.campaign_id
        assert matrix.scenario_id == observation_matrix.scenario_id
        assert matrix.world_version_id == observation_matrix.world_version_id
        assert matrix.world_content_hash == observation_matrix.world_content_hash
        assert (
            matrix.ordered_strategy_candidate_ids
            == observation_matrix.ordered_strategy_candidate_ids
        )
        assert matrix.ordered_scenario_seed_ids == observation_matrix.ordered_scenario_seed_ids
        assert matrix.ordered_metric_ids == observation_matrix.ordered_metric_ids
        assert (
            matrix.ordered_world_realization_ids == observation_matrix.ordered_world_realization_ids
        )
        assert (
            matrix.ordered_world_realization_content_hashes
            == observation_matrix.ordered_world_realization_content_hashes
        )

    def test_metric_units_from_authoritative_reference(self) -> None:
        store = _statistics_ready_store()
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        for summary in matrix.summaries:
            assert summary.metric_unit == ("units" if summary.metric_id == "m-1" else "percent")

    def test_identifier_content_hash_and_summarized_at_deterministic(self) -> None:
        store = _statistics_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        matrix = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.identifier == realization_metric_statistics_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
            source_metric_observation_matrix_id=observation_matrix.identifier,
        )
        assert matrix.identifier.startswith("realization-metric-statistics-matrix-")
        assert len(matrix.identifier) == len("realization-metric-statistics-matrix-") + 16
        assert matrix.content_hash == realization_metric_statistics_matrix_content_hash(matrix)
        assert matrix.summarized_at == observation_matrix.assembled_at == campaign.created_at
        assert matrix.runtime_version == "3.0.0"
        assert matrix.comparison_mode == "identical_conditions"
        assert matrix.statistics_mode == "descriptive"

    def test_repeated_query_byte_identical_and_read_only(self) -> None:
        store = _statistics_ready_store()
        events_before = len(store._run_events)
        sets_before = dict(store._realization_run_metric_observation_sets)
        first = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second == first
        assert second.model_dump(mode="json") == first.model_dump(mode="json")
        # Strictly read-only: no new events, manifests, or artifacts.
        assert len(store._run_events) == events_before
        assert store._realization_run_metric_observation_sets == sets_before
        assert not store._replay_manifests
        assert not store._realization_run_trajectory_replay_manifests

    def test_inputs_and_stored_records_remain_unchanged(self) -> None:
        store = _statistics_ready_store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        snapshots = (copy.deepcopy(campaign), copy.deepcopy(observation_matrix))
        get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.get_campaign(TENANT, "campaign-1") == snapshots[0]
        after = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert after == snapshots[1]


class TestStatisticsMatrixExactAlgorithm:
    def _matrix(self, store: InMemoryScenarioStore) -> RealizationCampaignMetricObservationMatrix:
        return get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )

    def _statistics(
        self, store: InMemoryScenarioStore
    ) -> RealizationCampaignMetricStatisticsMatrix:
        return build_realization_campaign_metric_statistics_matrix(
            observation_matrix=self._matrix(store)
        )

    def test_differing_level_values_in_exact_seed_order(self) -> None:
        # The seeds are ordered level-2 first, level-1 second, so the raw
        # values arrive in the exact seed order (2, 1) - never sorted.
        store = _statistics_store_with_seeds(_seeds_with_levels(2, 1))
        statistics = self._statistics(store)
        first = statistics.summaries[0]
        assert first.metric_id == "m-1"
        assert first.ordered_observed_values == (2, 1)
        assert first.observation_count == 2

    def test_exact_min_max_mean_median_std_two_levels(self) -> None:
        store = _statistics_store_with_seeds(_seeds_with_levels(1, 2))
        statistics = self._statistics(store)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (1, 2)
        assert first.minimum == 1.0
        assert first.maximum == 2.0
        assert first.arithmetic_mean == 1.5
        assert first.median == 1.5
        assert first.population_standard_deviation == 0.5
        # Every strategy shares the identical seed-aligned values.
        for summary in statistics.summaries:
            if summary.metric_id == "m-1":
                assert summary.ordered_observed_values == (1, 2)
                assert summary.arithmetic_mean == 1.5
                assert summary.population_standard_deviation == 0.5

    def test_ratio_zero_zero_produces_all_zero_statistics(self) -> None:
        store = _statistics_ready_store()
        statistics = self._statistics(store)
        for summary in statistics.summaries:
            if summary.metric_id == "m-2":
                assert summary.ordered_observed_values == (0.0, 0.0)
                assert summary.minimum == 0.0
                assert summary.maximum == 0.0
                assert summary.arithmetic_mean == 0.0
                assert summary.median == 0.0
                assert summary.population_standard_deviation == 0.0

    def test_single_seed_population_standard_deviation_exactly_zero(self) -> None:
        store = _statistics_store_with_seeds(_seeds_with_levels(1))
        statistics = self._statistics(store)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (1,)
        assert first.observation_count == 1
        assert first.minimum == 1.0
        assert first.maximum == 1.0
        assert first.arithmetic_mean == 1.0
        assert first.median == 1.0
        assert first.population_standard_deviation == 0.0

    def test_even_median_two_seeds(self) -> None:
        store = _statistics_store_with_seeds(_seeds_with_levels(1, 2))
        statistics = self._statistics(store)
        # (1 + 2) / 2, computed through math.fsum.
        assert statistics.summaries[0].median == 1.5

    def test_odd_median_three_seeds(self) -> None:
        store = _statistics_store_with_seeds(_seeds_with_levels(0, 1, 2))
        statistics = self._statistics(store)
        first = statistics.summaries[0]
        assert first.ordered_observed_values == (0, 1, 2)
        assert first.minimum == 0.0
        assert first.maximum == 2.0
        assert first.arithmetic_mean == 1.0
        assert first.median == 1.0
        assert first.population_standard_deviation == math.sqrt(2 / 3)

    def test_raw_integer_and_float_types_preserved(self) -> None:
        store = _statistics_ready_store()
        statistics = self._statistics(store)
        for summary in statistics.summaries:
            if summary.metric_id == "m-1":
                assert all(type(value) is int for value in summary.ordered_observed_values)
                assert all(not isinstance(value, bool) for value in summary.ordered_observed_values)
            else:
                assert all(type(value) is float for value in summary.ordered_observed_values)

    def test_zero_metrics_produces_empty_summaries(self) -> None:
        store = _statistics_ready_store()
        matrix = self._matrix(store)
        cells = tuple(cell.model_copy(update={"observations": ()}) for cell in matrix.cells)
        stripped = _statistics_self_consistent_copy(matrix, ordered_metric_ids=(), cells=cells)
        statistics = build_realization_campaign_metric_statistics_matrix(
            observation_matrix=stripped
        )
        assert statistics.ordered_metric_ids == ()
        assert statistics.summaries == ()
        assert statistics.source_metric_observation_matrix_id == stripped.identifier
        assert len(statistics.content_hash) == 64


class TestStatisticsMatrixDirectBuilderAdversarial:
    @staticmethod
    def _inputs(store: InMemoryScenarioStore) -> tuple[Any, ...]:
        return _verified_statistics_inputs(store)

    def test_wrong_runtime_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = observation_matrix.model_copy(
            update={"runtime_version": TRAJECTORY_RUNTIME_VERSION}
        )
        _expect_statistics_rejection(tampered, error=UnsupportedRuntimeVersionError)

    def test_wrong_comparison_mode_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = observation_matrix.model_copy(update={"comparison_mode": "other"})
        _expect_statistics_rejection(tampered)

    def test_source_identifier_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = observation_matrix.model_copy(update={"identifier": "tampered-matrix"})
        _expect_statistics_rejection(tampered, reason="source matrix identifier mismatch")

    def test_source_content_hash_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = observation_matrix.model_copy(update={"content_hash": "f" * 64})
        _expect_statistics_rejection(tampered, reason="source matrix content hash mismatch")

    def test_self_consistent_rehashed_identity_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_self_consistent_copy(
            observation_matrix, campaign_id="campaign-foreign"
        )
        _expect_statistics_rejection(tampered, reason="source matrix identifier mismatch")

    @pytest.mark.parametrize("mode", ["missing", "additional", "duplicated", "reordered"])
    def test_cell_collection_shape_rejected(self, mode: str) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        cells = observation_matrix.cells
        if mode == "missing":
            tampered_cells = cells[:-1]
        elif mode == "additional":
            tampered_cells = cells + (cells[0],)
        elif mode == "duplicated":
            tampered_cells = (cells[0], cells[0]) + cells[2:]
        else:
            tampered_cells = (cells[1], cells[0]) + cells[2:]
        tampered = _statistics_self_consistent_copy(observation_matrix, cells=tampered_cells)
        _expect_statistics_rejection(tampered)

    def test_cell_sequence_position_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(observation_matrix, 0, sequence_position=1)
        _expect_statistics_rejection(tampered)

    def test_cell_strategy_position_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(observation_matrix, 1, strategy_position=1)
        _expect_statistics_rejection(tampered)

    def test_cell_seed_position_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(observation_matrix, 1, seed_position=0)
        _expect_statistics_rejection(tampered)

    def test_foreign_strategy_identity_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(
            observation_matrix, 0, strategy_candidate_id="strategy-foreign"
        )
        _expect_statistics_rejection(tampered)

    def test_foreign_seed_identity_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(observation_matrix, 0, scenario_seed_id="seed-foreign")
        _expect_statistics_rejection(tampered)

    def test_realization_identity_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(observation_matrix, 0, world_realization_id="f" * 64)
        _expect_statistics_rejection(tampered)

    def test_realization_content_hash_tamper_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_replace_cell(
            observation_matrix, 0, world_realization_content_hash="f" * 64
        )
        _expect_statistics_rejection(tampered)

    @pytest.mark.parametrize("mode", ["missing", "reordered"])
    def test_differing_metric_collection_rejected(self, mode: str) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        source = observation_matrix.cells[1]
        if mode == "reordered":
            observations = tuple(reversed(source.observations))
        else:
            observations = source.observations[:1]
        tampered = _statistics_replace_cell(observation_matrix, 1, observations=observations)
        _expect_statistics_rejection(tampered)

    def test_binding_provenance_mismatch_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        tampered = _statistics_tamper_observation(
            observation_matrix, 1, 0, binding_id="binding-foreign"
        )
        _expect_statistics_rejection(
            tampered, reason="observation binding provenance mismatch across cells"
        )

    @pytest.mark.parametrize("raw", [True, "5", 1.5])
    def test_raw_value_validator_bypass_rejected(self, raw: object) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        # m-1 is the integer-kind metric: bool and string never count as
        # integers, and a float never matches the integer kind.
        tampered = _statistics_tamper_observation(observation_matrix, 1, 0, raw_value=raw)
        _expect_statistics_rejection(tampered)

    @pytest.mark.parametrize("raw", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_raw_value_rejected(self, raw: float) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        # m-2 is the number-kind metric; NaN and Infinity are never numbers.
        tampered = _statistics_tamper_observation(observation_matrix, 1, 1, raw_value=raw)
        _expect_statistics_rejection(tampered)

    def test_huge_integer_float_conversion_overflow_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        # A valid exact integer of kind "integer" that cannot convert to a
        # finite float must reject the complete matrix, never clamp.
        tampered = _statistics_tamper_observation(observation_matrix, 1, 0, raw_value=10**400)
        _expect_statistics_rejection(tampered)

    def test_derived_non_finite_statistics_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        # Both strategy-0 m-2 observations become 1e308: math.fsum overflows
        # to infinity, so the derived mean and median are non-finite.
        tampered = _statistics_tamper_observation(observation_matrix, 0, 1, raw_value=1e308)
        tampered = _statistics_tamper_observation(tampered, 1, 1, raw_value=1e308)
        _expect_statistics_rejection(tampered)

    def test_model_construct_validator_bypass_rejected(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        payload = observation_matrix.model_dump(mode="python")
        payload["cells"][0]["observations"][0]["raw_value"] = True
        bypassed = RealizationCampaignMetricObservationMatrix.model_construct(**payload)
        _expect_statistics_rejection(bypassed)

    def test_no_input_mutation_on_rejection(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        before = copy.deepcopy(observation_matrix)
        tampered = _statistics_tamper_observation(
            observation_matrix, 1, 0, binding_id="binding-foreign"
        )
        with pytest.raises(RealizationCampaignMetricStatisticsIntegrityError):
            build_realization_campaign_metric_statistics_matrix(observation_matrix=tampered)
        assert observation_matrix == before

    def test_public_errors_never_leak_values_direct_builder(self) -> None:
        store = _statistics_ready_store()
        (observation_matrix,) = self._inputs(store)
        attackers = (
            observation_matrix.model_copy(update={"content_hash": "f" * 64}),
            _statistics_tamper_observation(observation_matrix, 1, 0, raw_value=True),
            _statistics_tamper_observation(observation_matrix, 1, 0, raw_value=10**400),
            _statistics_tamper_observation(observation_matrix, 1, 1, raw_value=float("inf")),
        )
        for tampered in attackers:
            with pytest.raises(RealizationCampaignMetricStatisticsIntegrityError) as exc_info:
                build_realization_campaign_metric_statistics_matrix(observation_matrix=tampered)
            message = str(exc_info.value)
            assert "integrity" in message
            for leaked in ("True", "inf", "f" * 64, "0" * 64, "m-1", "level", "units", "2026"):
                assert leaked not in message


class TestStatisticsMatrixVerifiedQueryAdversarial:
    def test_non_complete_campaign_rejected(self) -> None:
        store = runtime_three_store()
        with pytest.raises(CampaignNotCompleteError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_missing_observation_sets_no_auto_extraction(self) -> None:
        store = _matrix_ready_store()
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        # Nothing was extracted automatically.
        assert not store._realization_run_metric_observation_sets

    @pytest.mark.parametrize("corrupt_index", [0, 4, 9])
    def test_corrupt_observation_set_prevents_any_statistics(self, corrupt_index: int) -> None:
        store = _statistics_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[corrupt_index])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_runtime_two_campaign_rejected(self) -> None:
        store = build_observation_store()
        world_version_id = compile_observation_world(store)
        prepare(store, world_version_id, runtime_version=TRAJECTORY_RUNTIME_VERSION)
        prepare_strategy_trajectory_plans(
            store=store,
            legion=MockLegionAdapter(),
            tenant_id=TENANT,
            campaign_id="campaign-1",
        )
        start(store)
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_unsupported_recorded_runtime_rejected(self) -> None:
        store = _statistics_ready_store()
        plan = store.get_run_plans(TENANT, "campaign-1")[0]
        inject_unsupported_recorded_runtime(store, campaign_id="campaign-1", plan=plan)
        with pytest.raises(UnsupportedRuntimeVersionError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )

    def test_tenant_isolation(self) -> None:
        store = _statistics_ready_store()
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id="tenant-other", campaign_id="campaign-1"
            )
        with pytest.raises(CampaignNotFoundError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-unknown"
            )

    def test_observation_matrix_query_called_exactly_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _statistics_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_statistics_query_service as stats_query_module,
        )
        from kalhas.application.realization_campaign_metric_observation_query_service import (
            get_verified_realization_campaign_metric_observation_matrix as original_query,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_query(*args, **kwargs)

        monkeypatch.setattr(
            stats_query_module,
            "get_verified_realization_campaign_metric_observation_matrix",
            counting,
        )
        get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_statistics_builder_called_exactly_once_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _statistics_ready_store()
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_statistics_query_service as stats_query_module,
        )
        from kalhas.application.realization_campaign_metric_statistics_runtime import (
            build_realization_campaign_metric_statistics_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            stats_query_module,
            "build_realization_campaign_metric_statistics_matrix",
            counting,
        )
        get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert calls == 1

    def test_statistics_builder_never_called_on_source_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _statistics_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[4])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        calls = 0
        from kalhas.application import (
            realization_campaign_metric_statistics_query_service as stats_query_module,
        )
        from kalhas.application.realization_campaign_metric_statistics_runtime import (
            build_realization_campaign_metric_statistics_matrix as original_builder,
        )

        def counting(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            stats_query_module,
            "build_realization_campaign_metric_statistics_matrix",
            counting,
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert calls == 0

    def test_failures_are_read_only_and_never_partial(self) -> None:
        store = _statistics_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        events_before = len(store._run_events)
        sets_before = len(store._realization_run_metric_observation_sets)
        run_id = run_identifier(plans[9])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError):
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        assert len(store._run_events) == events_before
        assert len(store._realization_run_metric_observation_sets) == sets_before
        assert not store._realization_run_trajectory_replay_manifests
        assert not store._replay_manifests
        status = store.get_campaign_status(TENANT, "campaign-1")
        assert status.state is CampaignState.COMPLETE

    def test_public_errors_never_leak_values(self) -> None:
        store = _statistics_ready_store()
        plans = store.get_run_plans(TENANT, "campaign-1")
        run_id = run_identifier(plans[0])
        stored = store.get_realization_run_metric_observation_set(TENANT, run_id)
        store._realization_run_metric_observation_sets[(TENANT, run_id)] = stored.model_copy(
            update={"content_hash": "f" * 64}
        )
        with pytest.raises(RealizationCampaignMetricObservationMatrixIntegrityError) as exc_info:
            get_verified_realization_campaign_metric_statistics(
                store=store, tenant_id=TENANT, campaign_id="campaign-1"
            )
        message = str(exc_info.value)
        assert "integrity" in message
        for leaked in ("f" * 64, "0" * 64, "seed-1", "m-1", "level", "units"):
            assert leaked not in message


class TestStatisticsMatrixPurity:
    def test_builder_and_query_are_pure_and_read_only(self) -> None:
        from kalhas.application import (
            realization_campaign_metric_statistics_query_service as query_module,
        )
        from kalhas.application import (
            realization_campaign_metric_statistics_runtime as runtime_module,
        )

        for module in (runtime_module, query_module):
            source = inspect.getsource(module)
            assert "kalhas.adapters" not in source
            assert "import random" not in source
            assert "datetime.now" not in source
            assert "time.time(" not in source
            assert "urllib" not in source
            assert "requests" not in source
            assert "socket" not in source
            assert "open(" not in source
        runtime_source = inspect.getsource(runtime_module)
        # The statistics are computed only through the frozen Phase 22
        # functions - never reimplemented, and never via NumPy/pandas or
        # the standard-library statistics module.
        assert "from kalhas.application.campaign_metric_statistics_runtime import" in runtime_source
        assert "import numpy" not in runtime_source
        assert "import pandas" not in runtime_source
        assert "import statistics" not in runtime_source
        assert "OutcomeVector" not in runtime_source
        assert "MetricOutcome" not in runtime_source
        assert "DecisionBrief" not in runtime_source
        assert "import rank" not in runtime_source
        assert "import score" not in runtime_source
        query_source = inspect.getsource(query_module)
        assert "put_" not in query_source
        assert "extract_realization_run_metric_observations" not in query_source
        assert "evaluate_trajectory" not in query_source
        assert "import replay" not in query_source
        assert "replay_service" not in query_source
        assert "import matrix" not in query_source

    def test_no_api_or_later_phase_surfaces(self) -> None:
        from kalhas.application import (
            realization_campaign_metric_statistics_query_service as query_module,
        )
        from kalhas.application import (
            realization_campaign_metric_statistics_runtime as runtime_module,
        )

        for module in (runtime_module, query_module):
            source = inspect.getsource(module)
            assert "kalhas.api" not in source
            assert "FastAPI" not in source
            assert "routes" not in source


class TestAcceptanceFixtureCausal84_103:
    """The causal 84/103 runtime-3 acceptance fixture, end to end.

    Runs the real lifecycle over the acceptance store (declarations ->
    compile -> prepare -> declared plans -> start -> execute -> explicit
    extraction -> verified matrix queries -> replay) and proves the
    causal chain: fixed seeds select distinct discrete branches, the
    real guarded transitions produce exactly 84 and 103 through the real
    state-transition engine, and every aggregate (execution, observation
    set, trajectory/observation/statistics matrices, replay manifests)
    verifies through the public integrity pipeline. No artifact is
    constructed directly, no private store collection is injected, and
    no final state, observation, execution, realization, hash, or matrix
    is ever monkeypatched.
    """

    def _store(self) -> InMemoryScenarioStore:
        return acceptance_observation_store()

    def _plans(self, store: InMemoryScenarioStore) -> tuple[RunPlan, ...]:
        return store.get_run_plans(TENANT, "campaign-1")

    def _executions(
        self, store: InMemoryScenarioStore
    ) -> tuple[RealizationRunTrajectoryExecution, ...]:
        return tuple(
            store.get_realization_run_trajectory_execution(TENANT, run_identifier(plan))
            for plan in self._plans(store)
        )

    def test_shape_exactly_two_strategies_two_seeds_four_cells(self) -> None:
        store = self._store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        plans = self._plans(store)
        assert [candidate.identifier for candidate in strategies] == ["mock-a", "mock-b"]
        assert campaign.seed_ensemble == ACCEPTANCE_SEEDS
        assert len(plans) == 4
        # Exactly K=2 aggregate realizations - never strategy x seed.
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert len(matrix.ordered_world_realization_ids) == 2
        assert len(matrix.ordered_world_realization_content_hashes) == 2
        assert len(matrix.cells) == 4
        assert len(self._executions(store)) == 4

    def test_strategy_major_seed_minor_order_exact(self) -> None:
        store = self._store()
        expected_pairs = [
            ("mock-a", "seed-0"),
            ("mock-a", "seed-2"),
            ("mock-b", "seed-0"),
            ("mock-b", "seed-2"),
        ]
        plans = self._plans(store)
        assert [(plan.strategy_candidate_id, plan.scenario_seed_id) for plan in plans] == (
            expected_pairs
        )
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_strategy_candidate_ids == ("mock-a", "mock-b")
        assert matrix.ordered_scenario_seed_ids == ("seed-0", "seed-2")
        assert [
            (cell.strategy_candidate_id, cell.scenario_seed_id) for cell in matrix.cells
        ] == expected_pairs
        observation_matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert [
            (cell.strategy_candidate_id, cell.scenario_seed_id) for cell in observation_matrix.cells
        ] == expected_pairs

    def test_two_genuinely_different_declared_plans(self) -> None:
        store = self._store()
        plans = store.get_strategy_trajectory_plans(TENANT, "campaign-1")
        assert len(plans) == 2
        by_strategy = {plan.strategy_candidate_id: plan for plan in plans}
        plan_a = by_strategy["mock-a"]
        plan_b = by_strategy["mock-b"]
        assert [r.transition_id for r in plan_a.transition_references] == ["t-x", "t-y"]
        assert [r.transition_id for r in plan_b.transition_references] == ["t-y", "t-x"]
        # The authoritative reference orders differ position by position
        # (different deterministic transition identifiers), and the plan
        # content hashes therefore differ.
        assert [r.transition_identifier for r in plan_a.transition_references] != [
            r.transition_identifier for r in plan_b.transition_references
        ]
        assert plan_a.content_hash != plan_b.content_hash
        assert [r.sequence_position for r in plan_a.transition_references] == [0, 1]
        assert [r.sequence_position for r in plan_b.transition_references] == [0, 1]

    def test_seed_branch_selection_proven(self) -> None:
        # The fixed seeds are proven to realize different discrete
        # branches of the level field under the acceptance world; the
        # guard of exactly one transition matches each branch.
        store = acceptance_fixture_store()
        compiled = MockNexusAdapter(store).compile_scenario(TENANT, "scenario-1")
        world = store.get_world(TENANT, compiled.version.identifier)
        catalog = extract_world_catalog(world)
        assert catalog.uncertainty_model is not None
        realizations: dict[str, WorldRealization] = {}
        for seed in ACCEPTANCE_SEEDS:
            realizations[seed.identifier] = build_world_realization(
                world=world,
                state_models=catalog.state_models,
                model=catalog.uncertainty_model,
                seed=seed,
                realized_at=NOW,
            )
        assert realizations["seed-0"].identifier != realizations["seed-2"].identifier
        assert realizations["seed-0"].content_hash != realizations["seed-2"].content_hash
        for seed_id, branch in (
            ("seed-0", ACCEPTANCE_BRANCH_X),
            ("seed-2", ACCEPTANCE_BRANCH_Y),
        ):
            overrides = realizations[seed_id].realized_initial_state_overrides
            level = next(
                override.value for override in overrides if override.state_field_id == "level"
            )
            assert level == branch

    def test_same_seed_binds_identical_realization_across_strategies(self) -> None:
        store = self._store()
        matrix = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        executions = self._executions(store)
        # Runs 0 and 2 share seed-0; runs 1 and 3 share seed-2 - the
        # identical realization identity and content hash are bound into
        # both strategies' executions and the seed-aligned matrix tuples.
        assert executions[0].world_realization_id == executions[2].world_realization_id
        assert executions[0].world_realization_id == matrix.ordered_world_realization_ids[0]
        assert executions[1].world_realization_id == executions[3].world_realization_id
        assert executions[1].world_realization_id == matrix.ordered_world_realization_ids[1]
        assert (
            executions[0].world_realization_content_hash
            == executions[2].world_realization_content_hash
        )
        assert (
            executions[0].world_realization_content_hash
            == matrix.ordered_world_realization_content_hashes[0]
        )
        assert (
            executions[1].world_realization_content_hash
            == matrix.ordered_world_realization_content_hashes[1]
        )
        # The seed-aligned tuple agrees with every cell of the same seed.
        for cell in matrix.cells:
            if cell.scenario_seed_id == "seed-0":
                assert cell.world_realization_id == matrix.ordered_world_realization_ids[0]
            else:
                assert cell.world_realization_id == matrix.ordered_world_realization_ids[1]

    def test_attempts_prove_guarded_transition_produced_each_value(self) -> None:
        store = self._store()
        expected_attempts = {
            ("mock-a", "seed-0"): (
                ("t-x", "applied"),
                ("t-y", "guard_not_satisfied"),
            ),
            ("mock-a", "seed-2"): (
                ("t-x", "guard_not_satisfied"),
                ("t-y", "applied"),
            ),
            ("mock-b", "seed-0"): (
                ("t-y", "guard_not_satisfied"),
                ("t-x", "applied"),
            ),
            ("mock-b", "seed-2"): (
                ("t-y", "applied"),
                ("t-x", "guard_not_satisfied"),
            ),
        }
        executions = self._executions(store)
        for plan, execution in zip(self._plans(store), executions, strict=True):
            result = execution.results[0]
            assert [
                (attempt.transition_id, attempt.outcome) for attempt in result.attempts
            ] == list(expected_attempts[(plan.strategy_candidate_id, plan.scenario_seed_id)])
            # The realized initial level is the branch value; the final
            # level is the causal target of the applied transition.
            expected_initial = (
                ACCEPTANCE_BRANCH_X if plan.scenario_seed_id == "seed-0" else ACCEPTANCE_BRANCH_Y
            )
            expected_final = (
                ACCEPTANCE_VALUE_X if plan.scenario_seed_id == "seed-0" else ACCEPTANCE_VALUE_Y
            )
            assert result.initial_state["level"] == expected_initial
            assert result.final_state["level"] == expected_final

    def test_final_observed_values_84_and_103(self) -> None:
        store = self._store()
        for plan in self._plans(store):
            run_id = run_identifier(plan)
            observation_set = store.get_realization_run_metric_observation_set(TENANT, run_id)
            expected = (
                ACCEPTANCE_VALUE_X if plan.scenario_seed_id == "seed-0" else ACCEPTANCE_VALUE_Y
            )
            assert [value.raw_value for value in observation_set.observations] == [expected]
            assert all(type(value.raw_value) is int for value in observation_set.observations)

    def test_observation_matrix_exactly_84_103_per_strategy(self) -> None:
        store = self._store()
        matrix = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert matrix.ordered_metric_ids == ("m-1",)
        for strategy in ("mock-a", "mock-b"):
            cells = [cell for cell in matrix.cells if cell.strategy_candidate_id == strategy]
            # Exactly [84, 103] in exact seed order.
            assert [cell.observations[0].raw_value for cell in cells] == [
                ACCEPTANCE_VALUE_X,
                ACCEPTANCE_VALUE_Y,
            ]

    def test_statistics_exact_for_each_strategy(self) -> None:
        store = self._store()
        statistics = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert statistics.ordered_metric_ids == ("m-1",)
        assert [summary.strategy_candidate_id for summary in statistics.summaries] == [
            "mock-a",
            "mock-b",
        ]
        assert [summary.metric_id for summary in statistics.summaries] == ["m-1", "m-1"]
        for summary in statistics.summaries:
            assert summary.ordered_observed_values == (
                ACCEPTANCE_VALUE_X,
                ACCEPTANCE_VALUE_Y,
            )
            assert summary.observation_count == 2
            assert summary.minimum == 84.0
            assert summary.maximum == 103.0
            assert summary.arithmetic_mean == 93.5
            assert summary.median == 93.5
            assert summary.population_standard_deviation == 9.5

    def test_replay_regenerates_same_execution_and_observation_hashes(self) -> None:
        store = self._store()
        for plan in self._plans(store):
            run_id = run_identifier(plan)
            execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
            observation_set = store.get_realization_run_metric_observation_set(TENANT, run_id)
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
            manifest = store.get_realization_run_trajectory_replay_manifest(TENANT, run_id)
            generic = store.get_replay_manifest(TENANT, run_id)
            assert manifest.realization_run_trajectory_execution_id == execution.identifier
            assert manifest.realization_run_metric_observation_set_id == observation_set.identifier
            assert manifest.expected_execution_hash == execution.content_hash
            assert manifest.recomputed_execution_hash == execution.content_hash
            assert manifest.expected_observation_set_hash == observation_set.content_hash
            assert manifest.recomputed_observation_set_hash == observation_set.content_hash
            assert manifest.runtime_version == "3.0.0"
            assert manifest.replay_classification == "exact"
            assert generic.input_hash == execution.input_hash
            # Repeated replay is idempotent: byte-identical manifests.
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_id)
            assert store.get_realization_run_trajectory_replay_manifest(TENANT, run_id) == manifest
            assert store.get_replay_manifest(TENANT, run_id) == generic

    def test_public_integrity_pipeline_verifies_state_chains(self) -> None:
        store = self._store()
        for plan in self._plans(store):
            run_id = run_identifier(plan)
            verified = verify_run_trajectory_inputs(store=store, tenant_id=TENANT, run_id=run_id)
            realization = _require_realization(verified)
            assert verified.inputs.run_plan.runtime_version == "3.0.0"
            assert verified.inputs.run_plan == plan
            assert realization.scenario_seed_id == plan.scenario_seed_id
            execution = store.get_realization_run_trajectory_execution(TENANT, run_id)
            assert execution.world_realization_id == realization.identifier
            assert execution.world_realization_content_hash == realization.content_hash
            assert execution.input_hash == plan.input_hash
            assert execution.strategy_candidate_id == plan.strategy_candidate_id
            assert execution.scenario_seed_id == plan.scenario_seed_id

    def test_repeated_queries_byte_identical_and_read_only(self) -> None:
        store = self._store()
        events_before = len(store._run_events)
        activity_before = dict(store._operational_activity)
        first = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second = get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second.model_dump(mode="json") == first.model_dump(mode="json")
        first_obs = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second_obs = get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second_obs.model_dump(mode="json") == first_obs.model_dump(mode="json")
        first_stats = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second_stats = get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second_stats.model_dump(mode="json") == first_stats.model_dump(mode="json")
        # Read-only: no events, no operational activity, no new artifacts.
        assert len(store._run_events) == events_before
        assert store._operational_activity == activity_before
        assert store._replay_manifests == {}

    def test_repeated_preparation_is_deterministic(self) -> None:
        first = acceptance_observation_store()
        second = acceptance_observation_store()
        assert first.get_run_plans(TENANT, "campaign-1") == second.get_run_plans(
            TENANT, "campaign-1"
        )
        for plan in self._plans(first):
            run_id = run_identifier(plan)
            assert first.get_realization_run_trajectory_execution(
                TENANT, run_id
            ) == second.get_realization_run_trajectory_execution(TENANT, run_id)
            assert first.get_realization_run_metric_observation_set(
                TENANT, run_id
            ) == second.get_realization_run_metric_observation_set(TENANT, run_id)
        first_matrix = get_verified_realization_campaign_trajectory_matrix(
            store=first, tenant_id=TENANT, campaign_id="campaign-1"
        )
        second_matrix = get_verified_realization_campaign_trajectory_matrix(
            store=second, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert second_matrix.model_dump(mode="json") == first_matrix.model_dump(mode="json")

    def test_no_input_contracts_mutated_by_replay_and_queries(self) -> None:
        store = self._store()
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, campaign.world_version_id)
        snapshots = (
            copy.deepcopy(campaign),
            copy.deepcopy(world),
            copy.deepcopy(store.get_manifest(TENANT, campaign.world_version_id)),
            copy.deepcopy(store.get_strategy_candidates(TENANT, "campaign-1")),
            copy.deepcopy(self._plans(store)),
            copy.deepcopy(store.get_strategy_trajectory_plans(TENANT, "campaign-1")),
            copy.deepcopy(
                tuple(
                    store.get_run_status(TENANT, run_identifier(plan))
                    for plan in self._plans(store)
                )
            ),
        )
        for plan in self._plans(store):
            replay_realization_run(store=store, tenant_id=TENANT, run_id=run_identifier(plan))
        get_verified_realization_campaign_trajectory_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        get_verified_realization_campaign_metric_observation_matrix(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        get_verified_realization_campaign_metric_statistics(
            store=store, tenant_id=TENANT, campaign_id="campaign-1"
        )
        assert store.get_campaign(TENANT, "campaign-1") == snapshots[0]
        assert store.get_world(TENANT, campaign.world_version_id) == snapshots[1]
        assert store.get_manifest(TENANT, campaign.world_version_id) == snapshots[2]
        assert store.get_strategy_candidates(TENANT, "campaign-1") == snapshots[3]
        assert self._plans(store) == snapshots[4]
        assert store.get_strategy_trajectory_plans(TENANT, "campaign-1") == snapshots[5]
        assert (
            tuple(store.get_run_status(TENANT, run_identifier(plan)) for plan in self._plans(store))
            == snapshots[6]
        )

    def test_no_rankings_scores_outcomes_evidence_or_domain_execution(self) -> None:
        store = self._store()
        # No evaluation profiles, no runtime-2 artifacts, no runtime-2
        # observation sets, no operational activity, and no replay
        # manifests were produced by the service-level acceptance flow.
        assert store._evaluation_profiles == {}
        assert store._run_trajectory_executions == {}
        assert store._run_metric_observation_sets == {}
        assert store._operational_activity == {}
        assert store._replay_manifests == {}
        # The only domain-pack records are the declaration-time
        # registration and binding used by the state model - never an
        # execution record (no domain-pack execution surface exists).
        assert set(store._domain_pack_manifests) == {("tenant-1", "manifest-1")}
        assert set(store._domain_pack_bindings) == {("tenant-1", "scenario-1", "manifest-1")}
        # Every stored observation value is a plain numeric raw value of
        # the level field - no score, outcome, or evidence structures.
        for plan in self._plans(store):
            observation_set = store.get_realization_run_metric_observation_set(
                TENANT, run_identifier(plan)
            )
            for value in observation_set.observations:
                assert isinstance(value.raw_value, int)
                assert not isinstance(value.raw_value, bool)

    def test_temporary_seam_fully_restored(self) -> None:
        """The preparation-count alignment is scoped and fully restored.

        The acceptance fixture's only explicit seam aligns
        ``EXPECTED_STRATEGY_SET_SIZE`` to the sanctioned two-candidate
        test adapter for the duration of the single preparation call.
        Before fixture construction, after the preparation call, and
        after the complete fixture returns, the production module
        constants are exactly 5 again and every module global of both
        carrier modules is byte-identical to the pre-fixture snapshot.
        """
        from kalhas.application import campaign_service as campaign_service_module
        from kalhas.application import (
            realization_campaign_service as realization_campaign_service_module,
        )

        # The constant is imported (not re-exported) by the preparation
        # module; the mypy ignore is scoped to that single access.
        expected_size = (
            realization_campaign_service_module.EXPECTED_STRATEGY_SET_SIZE  # type: ignore[attr-defined]
        )
        assert expected_size == 5
        assert campaign_service_module.EXPECTED_STRATEGY_SET_SIZE == 5
        realization_globals_before = dict(realization_campaign_service_module.__dict__)
        campaign_globals_before = dict(campaign_service_module.__dict__)

        store = acceptance_observation_store()

        # Fully restored after the complete fixture returns.
        assert (
            realization_campaign_service_module.EXPECTED_STRATEGY_SET_SIZE  # type: ignore[attr-defined]
        ) == 5
        assert campaign_service_module.EXPECTED_STRATEGY_SET_SIZE == 5
        assert realization_campaign_service_module.__dict__ == realization_globals_before
        assert campaign_service_module.__dict__ == campaign_globals_before

        # The temporary alignment took effect exactly where intended:
        # the stored campaign holds exactly two strategies and four
        # run plans - never more, never fewer.
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        plans = store.get_run_plans(TENANT, "campaign-1")
        assert [candidate.identifier for candidate in strategies] == ["mock-a", "mock-b"]
        assert len(plans) == 4
