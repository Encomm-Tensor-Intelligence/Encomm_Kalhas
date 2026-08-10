"""Pure run planning: one deterministic RunPlan per (strategy, seed) pair.

The planner never uses random values or wall-clock time; every input is
passed in. Run order is stable: strategies in candidate order, seeds in
ensemble order, so every strategy receives every seed in the exact same
seed order. Every run references the same immutable world version.
"""

from __future__ import annotations

from typing import Literal

from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime
from kalhas.contracts.v1.strategy import StrategyCandidate

LEGACY_STRUCTURAL_RUNTIME_VERSION = "1.0.0"
TRAJECTORY_RUNTIME_VERSION: Literal["2.0.0"] = "2.0.0"
RUNTIME_VERSION = TRAJECTORY_RUNTIME_VERSION


def run_identifier(run_plan: RunPlan) -> str:
    """The deterministic run identifier for a run plan."""
    return f"run-{run_plan.identifier}"


def run_input_hash(
    *,
    world_content_hash: str,
    strategy: StrategyCandidate,
    seed: ScenarioSeed,
    runtime_version: str = RUNTIME_VERSION,
) -> str:
    """Deterministic SHA-256 over world content hash, strategy, seed, and runtime version."""
    canonical = canonical_json(
        {
            "runtime_version": runtime_version,
            "seed": seed.model_dump(mode="json"),
            "strategy": strategy.model_dump(mode="json"),
            "world_content_hash": world_content_hash,
        }
    )
    return sha256_hex(canonical)


def run_plan_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    strategy_candidate_id: str,
    scenario_seed_id: str,
    runtime_version: str,
) -> str:
    """Deterministic, collision-safe RunPlan identifier.

    Hash-derived from the canonical tuple of identity inputs, so
    user-provided delimiter characters cannot create ambiguity and identical
    inputs always yield the same identifier.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "strategy_candidate_id": strategy_candidate_id,
            "scenario_seed_id": scenario_seed_id,
            "runtime_version": runtime_version,
        }
    )
    return f"plan-{sha256_hex(canonical)[:16]}"


def plan_runs(
    *,
    campaign_id: str,
    tenant_id: str,
    world_version_id: str,
    world_content_hash: str,
    strategies: tuple[StrategyCandidate, ...],
    seeds: tuple[ScenarioSeed, ...],
    created_at: AwareDatetime,
    runtime_version: str = RUNTIME_VERSION,
) -> tuple[RunPlan, ...]:
    """Generate one RunPlan per (strategy, seed) pair, in stable order.

    Planned run count equals ``len(strategies) * len(seeds)``; the seed
    ensemble is the sole source of run multiplicity.
    """
    plans: list[RunPlan] = []
    for strategy in strategies:
        for seed in seeds:
            plans.append(
                RunPlan(
                    identifier=run_plan_identifier(
                        campaign_id=campaign_id,
                        world_version_id=world_version_id,
                        strategy_candidate_id=strategy.identifier,
                        scenario_seed_id=seed.identifier,
                        runtime_version=runtime_version,
                    ),
                    tenant_id=tenant_id,
                    campaign_id=campaign_id,
                    world_version_id=world_version_id,
                    strategy_candidate_id=strategy.identifier,
                    scenario_seed_id=seed.identifier,
                    runtime_version=runtime_version,
                    input_hash=run_input_hash(
                        world_content_hash=world_content_hash,
                        strategy=strategy,
                        seed=seed,
                        runtime_version=runtime_version,
                    ),
                    created_at=created_at,
                )
            )
    return tuple(plans)
