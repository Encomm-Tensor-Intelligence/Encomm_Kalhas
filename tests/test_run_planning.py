"""Tests for the pure deterministic run planner."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.run_planner import (
    RUNTIME_VERSION,
    plan_runs,
    run_input_hash,
    run_plan_identifier,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import ObservationRequirement, StrategyCandidate, StrategyRequest

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


def build_seeds(count: int = 2) -> tuple[ScenarioSeed, ...]:
    return tuple(
        ScenarioSeed(
            identifier=f"seed-{index}",
            tenant_id="tenant-1",
            seed_value=f"value-{index}",
        )
        for index in range(1, count + 1)
    )


def build_plans(
    seeds: tuple[ScenarioSeed, ...] = build_seeds(),
) -> tuple[tuple[RunPlan, ...], tuple[StrategyCandidate, ...]]:
    strategies = MockLegionAdapter().request_strategies(build_request())
    return (
        plan_runs(
            campaign_id="campaign-1",
            tenant_id="tenant-1",
            world_version_id=WORLD_VERSION_ID,
            world_content_hash=WORLD_CONTENT_HASH,
            strategies=strategies,
            seeds=seeds,
            created_at=NOW,
        ),
        strategies,
    )


class TestRunPlanner:
    def test_planned_count_is_strategies_times_seeds(self) -> None:
        seeds = build_seeds(3)
        plans, strategies = build_plans(seeds)
        assert len(plans) == len(strategies) * len(seeds) == 15

    def test_every_strategy_receives_every_seed_in_same_order(self) -> None:
        seeds = build_seeds(3)
        plans, _ = build_plans(seeds)
        seed_ids = [seed.identifier for seed in seeds]
        by_strategy: dict[str, list[str]] = {}
        for plan in plans:
            by_strategy.setdefault(plan.strategy_candidate_id, []).append(plan.scenario_seed_id)
        assert len(by_strategy) == 5
        for strategy_id, received in by_strategy.items():
            assert received == seed_ids, f"{strategy_id} did not receive seeds in order"

    def test_every_planned_run_references_same_world_version(self) -> None:
        plans, _ = build_plans()
        assert {plan.world_version_id for plan in plans} == {WORLD_VERSION_ID}

    def test_hashes_are_deterministic(self) -> None:
        first, _ = build_plans()
        second, _ = build_plans()
        assert [plan.input_hash for plan in first] == [plan.input_hash for plan in second]
        assert [plan.model_dump() for plan in first] == [plan.model_dump() for plan in second]

    def test_hashes_differ_across_strategies_and_seeds(self) -> None:
        plans, _ = build_plans()
        hashes = {plan.input_hash for plan in plans}
        assert len(hashes) == len(plans)  # every (strategy, seed) pair hashes uniquely

    def test_same_strategy_different_seeds_hash_differently(self) -> None:
        plans, _ = build_plans()
        baseline = [p for p in plans if p.strategy_candidate_id == "mock-baseline"]
        assert baseline[0].input_hash != baseline[1].input_hash

    def test_runtime_version_is_recorded(self) -> None:
        plans, _ = build_plans()
        assert {plan.runtime_version for plan in plans} == {RUNTIME_VERSION}

    def test_planned_state_is_always_planned(self) -> None:
        plans, _ = build_plans()
        assert {plan.planned_state for plan in plans} == {"planned"}

    def test_planner_never_uses_wall_clock(self) -> None:
        """created_at is an explicit input; the planner has no time dependency."""
        plans, _ = build_plans()
        assert {plan.created_at for plan in plans} == {NOW}

    def test_run_input_hash_is_deterministic_pure_function(self) -> None:
        strategies = MockLegionAdapter().request_strategies(build_request())
        seed = build_seeds(1)[0]
        first = run_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategies[0],
            seed=seed,
        )
        second = run_input_hash(
            world_content_hash=WORLD_CONTENT_HASH,
            strategy=strategies[0],
            seed=seed,
        )
        assert first == second
        assert len(first) == 64  # SHA-256 hex

    def test_identifiers_are_hash_derived_and_stable(self) -> None:
        plans, _ = build_plans()
        assert re.fullmatch(r"plan-[0-9a-f]{16}", plans[0].identifier)
        assert [p.identifier for p in plans] == [
            p.identifier
            for p in plan_runs(
                campaign_id="campaign-1",
                tenant_id="tenant-1",
                world_version_id=WORLD_VERSION_ID,
                world_content_hash=WORLD_CONTENT_HASH,
                strategies=MockLegionAdapter().request_strategies(build_request()),
                seeds=build_seeds(2),
                created_at=NOW,
            )
        ]

    def test_identifiers_are_unique_across_pairs(self) -> None:
        plans, _ = build_plans()
        assert len({p.identifier for p in plans}) == len(plans)

    def test_identifiers_are_collision_safe_for_delimiter_heavy_ids(self) -> None:
        """User-provided delimiters must not create identifier ambiguity."""
        heavy_seeds = tuple(
            ScenarioSeed(
                identifier=f"seed-{index}|part/part-part",
                tenant_id="tenant-1",
                seed_value="v",
            )
            for index in range(1, 3)
        )
        first = plan_runs(
            campaign_id="campaign|a/b-c",
            tenant_id="tenant-1",
            world_version_id=WORLD_VERSION_ID,
            world_content_hash=WORLD_CONTENT_HASH,
            strategies=MockLegionAdapter().request_strategies(build_request()),
            seeds=heavy_seeds,
            created_at=NOW,
        )
        second = plan_runs(
            campaign_id="campaign|a/b-c",
            tenant_id="tenant-1",
            world_version_id=WORLD_VERSION_ID,
            world_content_hash=WORLD_CONTENT_HASH,
            strategies=MockLegionAdapter().request_strategies(build_request()),
            seeds=heavy_seeds,
            created_at=NOW,
        )
        assert [p.identifier for p in first] == [p.identifier for p in second]
        assert len({p.identifier for p in first}) == len(first)
        assert all(re.fullmatch(r"plan-[0-9a-f]{16}", p.identifier) for p in first)

    def test_run_plan_identifier_function_is_deterministic(self) -> None:
        first = run_plan_identifier(
            campaign_id="a|b-c",
            world_version_id="world-x",
            strategy_candidate_id="s|1",
            scenario_seed_id="seed|1",
            runtime_version="1.0.0",
        )
        second = run_plan_identifier(
            campaign_id="a|b-c",
            world_version_id="world-x",
            strategy_candidate_id="s|1",
            scenario_seed_id="seed|1",
            runtime_version="1.0.0",
        )
        assert first == second
        assert re.fullmatch(r"plan-[0-9a-f]{16}", first)

    def test_run_plan_identifier_changes_with_any_input(self) -> None:
        base = dict(
            campaign_id="c1",
            world_version_id="w1",
            strategy_candidate_id="s1",
            scenario_seed_id="seed1",
            runtime_version="1.0.0",
        )
        baseline = run_plan_identifier(**base)
        for field in base:
            altered = dict(base)
            altered[field] = base[field] + "-x"
            assert run_plan_identifier(**altered) != baseline, f"{field} did not affect id"
