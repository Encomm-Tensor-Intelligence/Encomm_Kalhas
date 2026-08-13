"""Focused tests for the Phase 25 runtime-3 run planner additions.

These tests prove ``plan_realization_runs`` mirrors the runtime-2
planner exactly in ordering and identity while binding each seed's
shared world realization content hash into every strategy's runtime-3
input hash: strategy-major/seed-minor order, one plan per (strategy,
seed) pair, identical plan identifiers across repeated planning, the
runtime-3 literal recorded, ``run_realization_input_hash`` covering
world/strategy/seed/realization/runtime-version and differing from the
frozen runtime-2 digest, the same seed realization hash appearing in
every strategy's run input for that seed, and a missing realization
failing closed before any plan is produced.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
    plan_runs,
    run_input_hash,
    run_realization_input_hash,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import ObservationRequirement, StrategyCandidate, StrategyRequest
from kalhas.contracts.v1.world_realization import WorldRealization

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

WORLD_VERSION_ID = "world-0123456789abcdef"
WORLD_CONTENT_HASH = "a" * 64


def build_request() -> StrategyRequest:
    return StrategyRequest(
        identifier="sr-1",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        required_observations=[
            ObservationRequirement(metric_id="m-1", description="observe m-1", required=True),
            ObservationRequirement(metric_id="m-2", description="observe m-2", required=False),
        ],
        requested_at=NOW,
    )


def build_strategies() -> tuple[StrategyCandidate, ...]:
    return MockLegionAdapter().request_strategies(build_request())


def build_seeds(count: int = 2) -> tuple[ScenarioSeed, ...]:
    return tuple(
        ScenarioSeed(
            identifier=f"seed-{index}",
            tenant_id="tenant-1",
            seed_value=f"value-{index}",
        )
        for index in range(1, count + 1)
    )


def build_realization(seed: ScenarioSeed, marker: str) -> WorldRealization:
    """A minimal contract-valid realization; only its content hash matters here."""
    return WorldRealization(
        identifier=f"realization-{seed.identifier}",
        tenant_id="tenant-1",
        scenario_id="scenario-1",
        world_version_id=WORLD_VERSION_ID,
        world_content_hash=WORLD_CONTENT_HASH,
        scenario_seed_id=seed.identifier,
        seed_content_hash="b" * 64,
        uncertainty_model_id=None,
        uncertainty_model_content_hash=None,
        sampler_version="sha256-counter-v1",
        quantization_policy="rational-round-half-even",
        quantization_fraction_bits=64,
        sampled_values=(),
        realized_initial_state_overrides=(),
        content_hash=f"{marker}{'c' * 63}",
        realized_at=NOW,
    )


def build_realizations(
    seeds: tuple[ScenarioSeed, ...],
) -> dict[str, WorldRealization]:
    return {
        seed.identifier: build_realization(seed, f"{index}") for index, seed in enumerate(seeds)
    }


def plan_realization(
    seeds: tuple[ScenarioSeed, ...] = build_seeds(),
) -> tuple[tuple[RunPlan, ...], tuple[StrategyCandidate, ...], dict[str, WorldRealization]]:
    strategies = build_strategies()
    realizations = build_realizations(seeds)
    plans = plan_realization_runs(
        campaign_id="campaign-1",
        tenant_id="tenant-1",
        world_version_id=WORLD_VERSION_ID,
        world_content_hash=WORLD_CONTENT_HASH,
        strategies=strategies,
        seeds=seeds,
        created_at=NOW,
        realizations=realizations,
    )
    return plans, strategies, realizations


class TestRealizationRunPlanner:
    def test_planned_count_is_strategies_times_seeds(self) -> None:
        seeds = build_seeds(3)
        plans, strategies, _ = plan_realization(seeds)
        assert len(plans) == len(strategies) * len(seeds) == 15

    def test_runtime_version_is_three_point_zero(self) -> None:
        plans, _, _ = plan_realization()
        assert {plan.runtime_version for plan in plans} == {REALIZATION_TRAJECTORY_RUNTIME_VERSION}

    def test_strategy_major_seed_minor_order_mirrors_runtime_two(self) -> None:
        seeds = build_seeds(3)
        strategies = build_strategies()
        realizations = build_realizations(seeds)
        runtime_three = plan_realization_runs(
            campaign_id="campaign-1",
            tenant_id="tenant-1",
            world_version_id=WORLD_VERSION_ID,
            world_content_hash=WORLD_CONTENT_HASH,
            strategies=strategies,
            seeds=seeds,
            created_at=NOW,
            realizations=realizations,
        )
        runtime_two = plan_runs(
            campaign_id="campaign-1",
            tenant_id="tenant-1",
            world_version_id=WORLD_VERSION_ID,
            world_content_hash=WORLD_CONTENT_HASH,
            strategies=strategies,
            seeds=seeds,
            created_at=NOW,
        )
        assert [(p.strategy_candidate_id, p.scenario_seed_id) for p in runtime_three] == [
            (p.strategy_candidate_id, p.scenario_seed_id) for p in runtime_two
        ]

    def test_planning_is_deterministic(self) -> None:
        seeds = build_seeds(2)
        first, _, _ = plan_realization(seeds)
        second, _, _ = plan_realization(seeds)
        assert [plan.model_dump() for plan in first] == [plan.model_dump() for plan in second]

    def test_same_seed_realization_bound_into_every_strategy_input(self) -> None:
        seeds = build_seeds(2)
        plans, _, realizations = plan_realization(seeds)
        for seed in seeds:
            by_strategy = [plan for plan in plans if plan.scenario_seed_id == seed.identifier]
            assert len(by_strategy) == 5  # one plan per strategy for this seed
            expected = realizations[seed.identifier].content_hash
            for plan in by_strategy:
                digest = run_realization_input_hash(
                    world_content_hash=WORLD_CONTENT_HASH,
                    strategy=next(
                        s for s in build_strategies() if s.identifier == plan.strategy_candidate_id
                    ),
                    seed=seed,
                    world_realization_content_hash=expected,
                )
                assert plan.input_hash == digest
                assert plan.input_hash == run_realization_input_hash(
                    world_content_hash=WORLD_CONTENT_HASH,
                    strategy=next(
                        s for s in build_strategies() if s.identifier == plan.strategy_candidate_id
                    ),
                    seed=seed,
                    world_realization_content_hash=realizations[seed.identifier].content_hash,
                )

    def test_different_seeds_produce_different_input_hashes(self) -> None:
        plans, _, _ = plan_realization()
        by_seed: dict[str, set[str]] = {}
        for plan in plans:
            by_seed.setdefault(plan.scenario_seed_id, set()).add(plan.input_hash)
        for hashes in by_seed.values():
            assert len(hashes) == 5  # strategies differ per seed
        assert by_seed["seed-1"] != by_seed["seed-2"]

    def test_missing_realization_fails_closed_before_any_plan(self) -> None:
        seeds = build_seeds(2)
        realizations = build_realizations(seeds)
        del realizations["seed-1"]
        with pytest.raises(KeyError):
            plan_realization_runs(
                campaign_id="campaign-1",
                tenant_id="tenant-1",
                world_version_id=WORLD_VERSION_ID,
                world_content_hash=WORLD_CONTENT_HASH,
                strategies=build_strategies(),
                seeds=seeds,
                created_at=NOW,
                realizations=realizations,
            )

    def test_runtime_three_hash_differs_from_runtime_two_digest(self) -> None:
        strategy = build_strategies()[0]
        seed = build_seeds(1)[0]
        realization = build_realization(seed, "1")
        runtime_three = run_realization_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            world_realization_content_hash=realization.content_hash,
        )
        runtime_two = run_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        )
        assert runtime_three != runtime_two

    def test_realization_hash_is_a_covering_input(self) -> None:
        strategy = build_strategies()[0]
        seed = build_seeds(1)[0]
        base = run_realization_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            world_realization_content_hash="d" * 64,
        )
        changed = run_realization_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            world_realization_content_hash="e" * 64,
        )
        assert base != changed

    def test_default_runtime_version_is_three_point_zero(self) -> None:
        strategy = build_strategies()[0]
        seed = build_seeds(1)[0]
        default = run_realization_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            world_realization_content_hash="d" * 64,
        )
        explicit = run_realization_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategy,
            seed=seed,
            world_realization_content_hash="d" * 64,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        )
        assert default == explicit

    def test_planner_never_uses_wall_clock(self) -> None:
        plans, _, _ = plan_realization()
        assert {plan.created_at for plan in plans} == {NOW}
