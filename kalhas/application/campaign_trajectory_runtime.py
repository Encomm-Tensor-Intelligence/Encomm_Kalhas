"""Pure deterministic campaign trajectory matrix builder (Phase 18).

Builds the immutable ``CampaignTrajectoryMatrix`` of one completed
runtime-2.0.0 campaign from **already verified authoritative records
only**: the recorded ``CampaignSpec``, the verified compiled ``WorldVersion``,
the exact stored ``StrategyCandidate`` tuple (campaign strategy order),
the campaign's shared ``ScenarioSeed`` ensemble (seed order), the exact
stored ``RunPlan`` tuple (authoritative RunPlan order), and the verified
``RunTrajectoryExecution`` artifacts of every run (one per plan, in the
same order). The module never loads the store, never calls LEGION or
NEXUS, never uses wall-clock time, randomness, network, providers,
filesystem, or domain packs, and never mutates any input. It performs no
execution, replay, transition evaluation, or outcome calculation of any
kind: the executions it binds are the already-verified Phase 16
artifacts, and the builder only verifies identities, preserves exact
orders, and hashes the structural matrix.

The builder enforces the complete fair-comparison structure:

- the trajectory runtime version (every plan must record 2.0.0);
- the exact campaign strategy order (the supplied strategy tuple must
  equal ``campaign.strategy_candidate_ids`` exactly);
- the exact shared seed order (the supplied seeds must equal the
  campaign's ``seed_ensemble`` exactly);
- the exact stored RunPlan order - one plan per (strategy, seed) pair in
  strategy-major, seed-minor order, with every plan's identity, world,
  and recomputed input hash verified;
- the exact complete strategy x seed matrix - missing, additional,
  duplicated, reordered, or foreign runs are all rejected;
- every cell bound to its exact RunPlan and verified execution, with
  every run/campaign/world/strategy/seed/input identity verified;
- the ordered result content hashes of every execution preserved
  exactly.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only):

- ``campaign_trajectory_matrix_identifier(...)``: deterministic from the
  campaign identity, the world identity, and the runtime version, with a
  readable distinct prefix.
- ``campaign_trajectory_matrix_content_hash(matrix)``: SHA-256 over the
  complete canonical matrix serialization excluding ``content_hash``.
- ``assembled_at`` is the recorded campaign ``created_at`` - never the
  wall clock.

All errors are safe typed domain errors; public messages never expose
state values, hashes, guards, targets, or validation details.
"""

from __future__ import annotations

from kalhas.application.domain_errors import (
    CampaignTrajectoryMatrixIntegrityError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.hashing import canonical_json, sha256_hex
from kalhas.application.run_planner import (
    TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
    run_input_hash,
)
from kalhas.application.strategy_trajectory_service import (
    strategy_candidate_content_hash,
)
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.campaign_trajectory import (
    CampaignTrajectoryMatrix,
    CampaignTrajectoryRunCell,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.trajectory_execution import RunTrajectoryExecution
from kalhas.contracts.v1.world import WorldVersion

_MATRIX_ID_PREFIX = "trajectory-matrix-"
_ID_HASH_LENGTH = 16
_PLACEHOLDER_HASH = "0" * 64


def campaign_trajectory_matrix_identifier(
    *,
    campaign_id: str,
    world_version_id: str,
    runtime_version: str,
) -> str:
    """Deterministic matrix identifier from campaign, world, and runtime identity.

    Hash-derived from the canonical ``(campaign_id, world_version_id,
    runtime_version)`` identity with a readable, distinct prefix;
    identical inputs always yield the identical identifier.
    """
    canonical = canonical_json(
        {
            "campaign_id": campaign_id,
            "world_version_id": world_version_id,
            "runtime_version": runtime_version,
        }
    )
    return f"{_MATRIX_ID_PREFIX}{sha256_hex(canonical)[:_ID_HASH_LENGTH]}"


def campaign_trajectory_matrix_content_hash(matrix: CampaignTrajectoryMatrix) -> str:
    """Canonical SHA-256 of the complete matrix content, excluding content_hash."""
    payload = matrix.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_hex(canonical_json(payload))


def _reject(campaign_id: str, reason: str) -> CampaignTrajectoryMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return CampaignTrajectoryMatrixIntegrityError(campaign_id, reason)


def build_campaign_trajectory_matrix(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    strategies: tuple[StrategyCandidate, ...],
    seeds: tuple[ScenarioSeed, ...],
    run_plans: tuple[RunPlan, ...],
    executions: tuple[RunTrajectoryExecution, ...],
) -> CampaignTrajectoryMatrix:
    """Build and fully hash the deterministic campaign trajectory matrix.

    Requires the trajectory runtime version (every plan must record
    2.0.0; legacy and unsupported matrices raise
    :class:`UnsupportedRuntimeVersionError`), the exact campaign strategy
    order, the exact shared seed order, and the exact complete strategy x
    seed matrix in the exact stored RunPlan order - missing, additional,
    duplicated, reordered, or foreign runs are rejected. Every cell is
    bound to its exact RunPlan and verified execution, with every
    run/campaign/world/strategy/seed/input identity verified against the
    authoritative records. The ordered result content hashes of each
    execution are preserved exactly. ``assembled_at`` is the recorded
    campaign ``created_at`` - never the wall clock. Nothing here mutates
    any input, accesses the store, or performs execution, replay,
    transition evaluation, or outcome calculation.
    """
    strategy_ids = [strategy.identifier for strategy in strategies]
    seed_ids = [seed.identifier for seed in seeds]

    for plan in run_plans:
        if plan.runtime_version != TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="campaign trajectory matrix"
            )
    if strategy_ids != list(campaign.strategy_candidate_ids):
        raise _reject(campaign.identifier, "strategy candidate order mismatch")
    if any(strategy.tenant_id != campaign.tenant_id for strategy in strategies):
        raise _reject(campaign.identifier, "strategy candidate tenant mismatch")
    if seed_ids != [seed.identifier for seed in campaign.seed_ensemble]:
        raise _reject(campaign.identifier, "seed ensemble order mismatch")
    if any(seed.tenant_id != campaign.tenant_id for seed in seeds):
        raise _reject(campaign.identifier, "seed tenant mismatch")
    if campaign.world_version_id != world.identifier:
        raise _reject(campaign.identifier, "campaign world version mismatch")
    if campaign.scenario_id != world.source_scenario_id:
        raise _reject(campaign.identifier, "campaign scenario world mismatch")

    expected_count = len(strategy_ids) * len(seed_ids)
    if len(run_plans) != expected_count:
        raise _reject(campaign.identifier, "run plan matrix length mismatch")

    for position, plan in enumerate(run_plans):
        strategy_position = position // len(seed_ids)
        seed_position = position % len(seed_ids)
        strategy = strategies[strategy_position]
        seed = seeds[seed_position]
        if plan.tenant_id != campaign.tenant_id:
            raise _reject(campaign.identifier, "run plan tenant mismatch")
        if plan.campaign_id != campaign.identifier:
            raise _reject(campaign.identifier, "run plan campaign mismatch")
        if plan.world_version_id != world.identifier:
            raise _reject(campaign.identifier, "run plan world version mismatch")
        if plan.strategy_candidate_id != strategy.identifier:
            raise _reject(campaign.identifier, "run plan strategy position mismatch")
        if plan.scenario_seed_id != seed.identifier:
            raise _reject(campaign.identifier, "run plan seed position mismatch")
        recomputed_input_hash = run_input_hash(
            world_content_hash=world.content_hash,
            strategy=strategy,
            seed=seed,
            runtime_version=plan.runtime_version,
        )
        if recomputed_input_hash != plan.input_hash:
            raise _reject(campaign.identifier, "run plan input hash mismatch")

    if len(executions) != len(run_plans):
        raise _reject(campaign.identifier, "trajectory execution count mismatch")

    cells: list[CampaignTrajectoryRunCell] = []
    for position, (plan, execution) in enumerate(zip(run_plans, executions, strict=True)):
        strategy_position = position // len(seed_ids)
        seed_position = position % len(seed_ids)
        strategy = strategies[strategy_position]
        if execution.run_id != run_identifier(plan):
            raise _reject(campaign.identifier, "trajectory execution run identity mismatch")
        if execution.run_plan_id != plan.identifier:
            raise _reject(campaign.identifier, "trajectory execution run plan mismatch")
        if execution.campaign_id != campaign.identifier:
            raise _reject(campaign.identifier, "trajectory execution campaign mismatch")
        if execution.world_version_id != world.identifier:
            raise _reject(campaign.identifier, "trajectory execution world version mismatch")
        if execution.world_content_hash != world.content_hash:
            raise _reject(campaign.identifier, "trajectory execution world content hash mismatch")
        if execution.strategy_candidate_id != plan.strategy_candidate_id:
            raise _reject(campaign.identifier, "trajectory execution strategy mismatch")
        if execution.strategy_content_hash != strategy_candidate_content_hash(strategy):
            raise _reject(
                campaign.identifier, "trajectory execution strategy content hash mismatch"
            )
        if execution.scenario_seed_id != plan.scenario_seed_id:
            raise _reject(campaign.identifier, "trajectory execution scenario seed mismatch")
        if execution.input_hash != plan.input_hash:
            raise _reject(campaign.identifier, "trajectory execution input hash mismatch")
        if execution.runtime_version != TRAJECTORY_RUNTIME_VERSION:
            raise _reject(campaign.identifier, "trajectory execution runtime version mismatch")
        cells.append(
            CampaignTrajectoryRunCell(
                sequence_position=position,
                strategy_position=strategy_position,
                seed_position=seed_position,
                run_id=execution.run_id,
                run_plan_id=plan.identifier,
                strategy_candidate_id=plan.strategy_candidate_id,
                scenario_seed_id=plan.scenario_seed_id,
                input_hash=plan.input_hash,
                trajectory_execution_id=execution.identifier,
                trajectory_execution_content_hash=execution.content_hash,
                trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
                result_content_hashes=tuple(result.content_hash for result in execution.results),
            )
        )

    matrix = CampaignTrajectoryMatrix(
        identifier=campaign_trajectory_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        ordered_strategy_candidate_ids=tuple(strategy_ids),
        ordered_scenario_seed_ids=tuple(seed_ids),
        cells=tuple(cells),
        content_hash=_PLACEHOLDER_HASH,
        assembled_at=campaign.created_at,
    )
    return matrix.model_copy(
        update={"content_hash": campaign_trajectory_matrix_content_hash(matrix)}
    )
