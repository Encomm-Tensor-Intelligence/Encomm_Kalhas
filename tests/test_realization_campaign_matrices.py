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

The observation matrix, statistics matrix, APIs, mock differentiation,
the acceptance fixture, and documentation belong to later slices.
"""

from __future__ import annotations

import copy
import inspect
import subprocess
from typing import Any, cast

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    RunInputIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_campaign_trajectory_query_service import (
    get_verified_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_campaign_trajectory_runtime import (
    build_realization_campaign_trajectory_matrix,
)
from kalhas.application.realization_errors import (
    RealizationCampaignTrajectoryMatrixIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_trajectory_matrix_content_hash,
    realization_trajectory_matrix_identifier,
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
from kalhas.application.world_uncertainty_identity import (
    seed_content_hash,
    world_realization_content_hash,
    world_realization_identifier,
)
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization

from tests.phase4_helpers import TENANT, prepare, start
from tests.phase20_helpers import build_observation_store, compile_observation_world
from tests.phase25_helpers import (
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
