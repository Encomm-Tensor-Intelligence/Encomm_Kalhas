"""Phase 18 pure matrix builder tests.

Proves ``build_campaign_trajectory_matrix`` assembles the exact
authoritative strategy x shared-seed matrix from verified records only:
one strategy x one seed and multi-strategy x multi-seed matrices in the
exact strategy-major/seed-minor RunPlan order; deterministic identifier,
timestamp, and content hash; result hash ordering preserved; cross-store
and insertion-order determinism; rejection of missing, additional,
duplicated, reordered, or foreign runs and of wrong strategy/seed/
run-plan/execution/world/campaign/runtime/input-hash identities; legacy
and unsupported runtime rejection; and no mutation, no store access, and
no execution/replay/evaluation/time/random/network behavior.
"""

from __future__ import annotations

import copy
from typing import TypedDict

import pytest
from kalhas.application.campaign_trajectory_runtime import (
    build_campaign_trajectory_matrix,
    campaign_trajectory_matrix_content_hash,
    campaign_trajectory_matrix_identifier,
)
from kalhas.application.domain_errors import (
    CampaignTrajectoryMatrixIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import (
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
    run_input_hash,
)
from kalhas.application.run_trajectory_runtime import (
    run_trajectory_execution_identifier,
)
from kalhas.application.strategy_trajectory_service import (
    strategy_candidate_content_hash,
)
from kalhas.application.structural_runtime import execute_campaign, execute_run
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.campaign_trajectory import CampaignTrajectoryMatrix
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.state_model import DomainStateModel
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.trajectory_execution import (
    RunTrajectoryExecution,
)
from kalhas.contracts.v1.transition import DomainStateTransition
from kalhas.contracts.v1.world import WorldVersion
from pydantic import ValidationError

from tests.phase4_helpers import NOW, TENANT, build_seed
from tests.phase16_helpers import build_model, build_trajectory_store, build_transition
from tests.test_contracts import VALID_PAYLOADS

HASH_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


class _BuilderKwargs(TypedDict):
    campaign: CampaignSpec
    world: WorldVersion
    strategies: tuple[StrategyCandidate, ...]
    seeds: tuple[ScenarioSeed, ...]
    run_plans: tuple[RunPlan, ...]
    executions: tuple[RunTrajectoryExecution, ...]


def _one_by_one_records() -> tuple[
    CampaignSpec,
    WorldVersion,
    tuple[StrategyCandidate, ...],
    tuple[ScenarioSeed, ...],
    tuple[RunPlan, ...],
    tuple[RunTrajectoryExecution, ...],
]:
    """Self-consistent minimal 1 strategy x 1 seed record set."""
    world = WorldVersion.model_validate(VALID_PAYLOADS[WorldVersion])
    strategy = StrategyCandidate.model_validate(VALID_PAYLOADS[StrategyCandidate])
    seed = ScenarioSeed.model_validate(VALID_PAYLOADS[ScenarioSeed])
    campaign = CampaignSpec(
        identifier="campaign-1",
        tenant_id=TENANT,
        name="Reference campaign",
        scenario_id="scenario-1",
        world_version_id=world.identifier,
        strategy_candidate_ids=[strategy.identifier],
        seed_ensemble=(seed,),
        created_at=NOW,
        metadata={},
    )
    plan = RunPlan(
        identifier="plan-0123456789abcdef",
        tenant_id=TENANT,
        campaign_id=campaign.identifier,
        world_version_id=world.identifier,
        strategy_candidate_id=strategy.identifier,
        scenario_seed_id=seed.identifier,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        input_hash=run_input_hash(
            world_content_hash=world.content_hash,
            strategy=strategy,
            seed=seed,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ),
        created_at=NOW,
    )
    run_id = run_identifier(plan)
    execution = RunTrajectoryExecution(
        identifier=run_trajectory_execution_identifier(
            run_id=run_id, runtime_version=TRAJECTORY_RUNTIME_VERSION
        ),
        tenant_id=TENANT,
        run_id=run_id,
        campaign_id=campaign.identifier,
        run_plan_id=plan.identifier,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategy_candidate_id=strategy.identifier,
        strategy_content_hash=strategy_candidate_content_hash(strategy),
        scenario_seed_id=seed.identifier,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        input_hash=plan.input_hash,
        trajectory_plan_set_hash=HASH_64,
        results=(),
        content_hash=HASH_64,
        executed_at=NOW,
    )
    return campaign, world, (strategy,), (seed,), (plan,), (execution,)


def _complete_v2_store(
    *,
    models: tuple[DomainStateModel, ...] = (),
    transitions: tuple[DomainStateTransition, ...] = (),
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    reverse_execution: bool = False,
) -> tuple[InMemoryScenarioStore, str]:
    """A store with every trajectory run executed (campaign COMPLETE)."""
    store, world_id = build_trajectory_store(
        state_models=models, transitions=transitions, seeds=seeds
    )
    run_ids = [run_identifier(plan) for plan in store.get_run_plans(TENANT, "campaign-1")]
    if reverse_execution:
        for run_id in reversed(run_ids):
            execute_run(store=store, tenant_id=TENANT, run_id=run_id)
    else:
        execute_campaign(store=store, tenant_id=TENANT, campaign_id="campaign-1")
    return store, world_id


def _builder_inputs(
    store: InMemoryScenarioStore, world_version_id: str
) -> tuple[
    CampaignSpec,
    WorldVersion,
    tuple[StrategyCandidate, ...],
    tuple[ScenarioSeed, ...],
    tuple[RunPlan, ...],
    tuple[RunTrajectoryExecution, ...],
]:
    campaign = store.get_campaign(TENANT, "campaign-1")
    run_plans = store.get_run_plans(TENANT, "campaign-1")
    executions = tuple(
        store.get_run_trajectory_execution(TENANT, run_identifier(plan)) for plan in run_plans
    )
    return (
        campaign,
        store.get_world(TENANT, world_version_id),
        store.get_strategy_candidates(TENANT, "campaign-1"),
        campaign.seed_ensemble,
        run_plans,
        executions,
    )


def _build(store: InMemoryScenarioStore, world_version_id: str) -> CampaignTrajectoryMatrix:
    campaign, world, strategies, seeds, run_plans, executions = _builder_inputs(
        store, world_version_id
    )
    return build_campaign_trajectory_matrix(
        campaign=campaign,
        world=world,
        strategies=strategies,
        seeds=seeds,
        run_plans=run_plans,
        executions=executions,
    )


def _builder_inputs_kwargs(store: InMemoryScenarioStore, world_version_id: str) -> _BuilderKwargs:
    campaign, world, strategies, seeds, run_plans, executions = _builder_inputs(
        store, world_version_id
    )
    return {
        "campaign": campaign,
        "world": world,
        "strategies": strategies,
        "seeds": seeds,
        "run_plans": run_plans,
        "executions": executions,
    }


def _deep_snapshot(value: object) -> object:
    return copy.deepcopy(value)


class TestValidMatrices:
    def test_one_strategy_one_seed(self) -> None:
        campaign, world, strategies, seeds, run_plans, executions = _one_by_one_records()
        matrix = build_campaign_trajectory_matrix(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
        )
        assert len(matrix.cells) == 1
        cell = matrix.cells[0]
        assert cell.sequence_position == 0
        assert cell.strategy_position == 0
        assert cell.seed_position == 0
        assert cell.run_id == run_identifier(run_plans[0])
        assert cell.run_plan_id == run_plans[0].identifier
        assert cell.strategy_candidate_id == strategies[0].identifier
        assert cell.scenario_seed_id == seeds[0].identifier
        assert cell.input_hash == run_plans[0].input_hash
        assert cell.trajectory_execution_id == executions[0].identifier
        assert cell.trajectory_execution_content_hash == executions[0].content_hash
        assert cell.trajectory_plan_set_hash == executions[0].trajectory_plan_set_hash
        assert cell.result_content_hashes == ()

    def test_multi_strategy_multi_seed_exact_cartesian_product(self) -> None:
        store, world_id = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        matrix = _build(store, world_id)
        campaign = store.get_campaign(TENANT, "campaign-1")
        seeds = campaign.seed_ensemble
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        assert matrix.ordered_strategy_candidate_ids == tuple(
            strategy.identifier for strategy in strategies
        )
        assert matrix.ordered_scenario_seed_ids == tuple(seed.identifier for seed in seeds)
        assert len(matrix.cells) == len(strategies) * len(seeds)
        # The exact complete Cartesian product: every (strategy, seed)
        # pair appears exactly once, in strategy-major seed-minor order.
        pairs = [(cell.strategy_position, cell.seed_position) for cell in matrix.cells]
        expected_pairs = [
            (strategy_position, seed_position)
            for strategy_position in range(len(strategies))
            for seed_position in range(len(seeds))
        ]
        assert pairs == expected_pairs
        assert len(set(pairs)) == len(pairs)

    def test_cells_match_exact_run_plan_order(self) -> None:
        store, world_id = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        matrix = _build(store, world_id)
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        assert [cell.run_plan_id for cell in matrix.cells] == [
            plan.identifier for plan in run_plans
        ]
        assert [cell.run_id for cell in matrix.cells] == [
            run_identifier(plan) for plan in run_plans
        ]

    def test_strategy_major_seed_minor_order_and_identical_seed_sequences(self) -> None:
        store, world_id = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        matrix = _build(store, world_id)
        seeds = store.get_campaign(TENANT, "campaign-1").seed_ensemble
        strategies = store.get_strategy_candidates(TENANT, "campaign-1")
        for strategy_position, strategy in enumerate(strategies):
            for seed_position, seed in enumerate(seeds):
                index = strategy_position * len(seeds) + seed_position
                cell = matrix.cells[index]
                assert cell.strategy_position == strategy_position
                assert cell.seed_position == seed_position
                assert cell.strategy_candidate_id == strategy.identifier
                assert cell.scenario_seed_id == seed.identifier
        # Every strategy receives the identical ordered seed identifiers.
        per_strategy_seeds = [
            [cell.scenario_seed_id for cell in matrix.cells[offset : offset + len(seeds)]]
            for offset in range(0, len(matrix.cells), len(seeds))
        ]
        assert all(sequence == per_strategy_seeds[0] for sequence in per_strategy_seeds)

    def test_result_content_hashes_preserve_execution_order(self) -> None:
        model_1 = build_model(state_model_id="sm-1", manifest_id="manifest-1")
        model_2 = build_model(state_model_id="sm-2", manifest_id="manifest-2")
        store, world_id = _complete_v2_store(
            models=(model_1, model_2),
            transitions=(build_transition(model_1), build_transition(model_2)),
        )
        matrix = _build(store, world_id)
        run_plans = store.get_run_plans(TENANT, "campaign-1")
        for cell, plan in zip(matrix.cells, run_plans, strict=True):
            execution = store.get_run_trajectory_execution(TENANT, run_identifier(plan))
            assert cell.result_content_hashes == tuple(
                result.content_hash for result in execution.results
            )
            assert len(cell.result_content_hashes) == 2

    def test_deterministic_identifier_timestamp_and_content_hash(self) -> None:
        store, world_id = _complete_v2_store()
        matrix = _build(store, world_id)
        campaign = store.get_campaign(TENANT, "campaign-1")
        world = store.get_world(TENANT, world_id)
        assert matrix.identifier == campaign_trajectory_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        )
        assert matrix.assembled_at == campaign.created_at
        assert matrix.content_hash == campaign_trajectory_matrix_content_hash(matrix)

    def test_cross_store_determinism(self) -> None:
        first_store, first_world = _complete_v2_store()
        second_store, second_world = _complete_v2_store()
        first = _build(first_store, first_world)
        second = _build(second_store, second_world)
        assert first.model_dump(mode="json") == second.model_dump(mode="json")
        assert first.identifier == second.identifier
        assert first.content_hash == second.content_hash

    def test_input_insertion_order_invariance(self) -> None:
        # Executing the same campaign's runs in reverse order yields the
        # identical matrix: the matrix depends only on the authoritative
        # recorded plan order, never on write/execution order.
        forward_store, forward_world = _complete_v2_store()
        reverse_store, reverse_world = _complete_v2_store(reverse_execution=True)
        forward = _build(forward_store, forward_world)
        reverse = _build(reverse_store, reverse_world)
        assert forward.model_dump(mode="json") == reverse.model_dump(mode="json")


class TestRejections:
    def test_missing_cell_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        kwargs["executions"] = executions[:-1]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_additional_cell_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        kwargs["executions"] = executions + (executions[0],)
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_duplicate_run_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        # Two identical executions for two different plans: the second
        # binds to the wrong run identity.
        kwargs["executions"] = (executions[0], executions[0]) + executions[2:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_reordered_cell_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        swapped = list(executions)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        kwargs["executions"] = tuple(swapped)
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_reordered_run_plans_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        run_plans = kwargs["run_plans"]
        assert isinstance(run_plans, tuple)
        swapped = list(run_plans)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        kwargs["run_plans"] = tuple(swapped)
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_strategy_order_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        strategies = kwargs["strategies"]
        assert isinstance(strategies, tuple)
        kwargs["strategies"] = (strategies[1], strategies[0]) + strategies[2:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_seed_order_rejected(self) -> None:
        store, world_id = _complete_v2_store(seeds=(build_seed(), build_seed(identifier="seed-2")))
        kwargs = _builder_inputs_kwargs(store, world_id)
        seeds = kwargs["seeds"]
        assert isinstance(seeds, tuple)
        kwargs["seeds"] = (seeds[1], seeds[0])
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_execution_strategy_identity_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        tampered = executions[0].model_copy(update={"strategy_candidate_id": "foreign-strategy"})
        kwargs["executions"] = (tampered,) + executions[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_execution_seed_identity_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        tampered = executions[0].model_copy(update={"scenario_seed_id": "foreign-seed"})
        kwargs["executions"] = (tampered,) + executions[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_execution_run_plan_identity_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        tampered = executions[0].model_copy(update={"run_plan_id": "plan-foreign"})
        kwargs["executions"] = (tampered,) + executions[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_world_identity_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        world = kwargs["world"]
        assert isinstance(world, WorldVersion)
        kwargs["world"] = world.model_copy(update={"identifier": "world-foreign"})
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_world_content_hash_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        world = kwargs["world"]
        assert isinstance(world, WorldVersion)
        kwargs["world"] = world.model_copy(update={"content_hash": "f" * 64})
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_campaign_identity_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        campaign = kwargs["campaign"]
        assert isinstance(campaign, CampaignSpec)
        kwargs["campaign"] = campaign.model_copy(update={"identifier": "campaign-foreign"})
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_wrong_run_plan_input_hash_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        run_plans = kwargs["run_plans"]
        assert isinstance(run_plans, tuple)
        tampered = run_plans[0].model_copy(update={"input_hash": "f" * 64})
        kwargs["run_plans"] = (tampered,) + run_plans[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_foreign_execution_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        tampered = executions[0].model_copy(update={"run_id": "run-foreign"})
        kwargs["executions"] = (tampered,) + executions[1:]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError):
            build_campaign_trajectory_matrix(**kwargs)

    def test_legacy_runtime_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        run_plans = kwargs["run_plans"]
        assert isinstance(run_plans, tuple)
        legacy = run_plans[0].model_copy(update={"runtime_version": "1.0.0"})
        kwargs["run_plans"] = (legacy,) + run_plans[1:]
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            build_campaign_trajectory_matrix(**kwargs)
        assert "1.0.0" in str(exc_info.value)

    def test_unsupported_runtime_rejected(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        run_plans = kwargs["run_plans"]
        assert isinstance(run_plans, tuple)
        unsupported = run_plans[0].model_copy(update={"runtime_version": "3.0.0"})
        kwargs["run_plans"] = (unsupported,) + run_plans[1:]
        with pytest.raises(UnsupportedRuntimeVersionError) as exc_info:
            build_campaign_trajectory_matrix(**kwargs)
        assert "3.0.0" in str(exc_info.value)

    def test_rejected_reason_never_leaks_into_public_message(self) -> None:
        store, world_id = _complete_v2_store()
        kwargs = _builder_inputs_kwargs(store, world_id)
        executions = kwargs["executions"]
        assert isinstance(executions, tuple)
        kwargs["executions"] = executions[:-1]
        with pytest.raises(CampaignTrajectoryMatrixIntegrityError) as exc_info:
            build_campaign_trajectory_matrix(**kwargs)
        message = str(exc_info.value)
        assert "execution count mismatch" not in message
        assert "integrity" in message


class TestPurityAndIsolation:
    def test_no_input_mutation(self) -> None:
        store, world_id = _complete_v2_store()
        campaign, world, strategies, seeds, run_plans, executions = _builder_inputs(store, world_id)
        before = (
            _deep_snapshot(campaign),
            _deep_snapshot(world),
            _deep_snapshot(strategies),
            _deep_snapshot(seeds),
            _deep_snapshot(run_plans),
            _deep_snapshot(executions),
        )
        build_campaign_trajectory_matrix(
            campaign=campaign,
            world=world,
            strategies=strategies,
            seeds=seeds,
            run_plans=run_plans,
            executions=executions,
        )
        after = (
            _deep_snapshot(campaign),
            _deep_snapshot(world),
            _deep_snapshot(strategies),
            _deep_snapshot(seeds),
            _deep_snapshot(run_plans),
            _deep_snapshot(executions),
        )
        assert after == before

    def test_returned_matrix_is_a_fresh_detached_object(self) -> None:
        store, world_id = _complete_v2_store()
        matrix = _build(store, world_id)
        again = _build(store, world_id)
        assert again is not matrix
        assert again == matrix
        # The matrix is fully frozen: mutation attempts are rejected and
        # can never reach storage.
        with pytest.raises(ValidationError):
            matrix.cells = ()

    def test_builder_never_calls_execution_replay_or_evaluation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import kalhas.application.replay_service as replay_service
        import kalhas.application.run_trajectory_runtime as runtime
        import kalhas.application.state_transition_engine as engine
        import kalhas.application.structural_runtime as structural_runtime

        store, world_id = _complete_v2_store()

        def boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("forbidden call in the pure builder")

        monkeypatch.setattr(runtime, "build_run_trajectory_execution", boom)
        monkeypatch.setattr(replay_service, "replay_run", boom)
        monkeypatch.setattr(engine, "evaluate_trajectory", boom)
        monkeypatch.setattr(structural_runtime, "execute_run", boom)
        monkeypatch.setattr(structural_runtime, "execute_campaign", boom)

        matrix = _build(store, world_id)
        assert len(matrix.cells) >= 1
