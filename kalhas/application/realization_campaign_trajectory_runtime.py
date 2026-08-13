"""Pure deterministic runtime-3 realization-aware campaign trajectory matrix builder (Phase 25).

Builds the immutable ``RealizationCampaignTrajectoryMatrix`` of one
completed runtime-3.0.0 campaign from **already verified authoritative
records only**: the recorded ``CampaignSpec``, the verified compiled
``WorldVersion``, the exact stored ``StrategyCandidate`` tuple (campaign
strategy order), the campaign's shared ``ScenarioSeed`` ensemble (seed
order), the exact stored ``RunPlan`` tuple (authoritative RunPlan order),
the verified ``RealizationRunTrajectoryExecution`` artifacts of every run
(one per plan, in the same order), and the verified ``WorldRealization``
of every seed (exactly one per seed, in exact seed order - never K x S).

The module never loads the store, never calls LEGION or NEXUS, never uses
wall-clock time, randomness, network, providers, filesystem, or domain
packs, and never mutates any input. It performs no execution, replay,
transition evaluation, observation extraction, or outcome calculation of
any kind: the executions and realizations it binds are the already
verified artifacts, and the builder only verifies identities, preserves
exact orders, and hashes the structural matrix.

The builder enforces the complete fair-comparison structure:

- the realization trajectory runtime version (every plan must record
  exactly 3.0.0; any other runtime raises ``UnsupportedRuntimeVersionError``);
- the exact campaign strategy order and the exact shared seed order, with
  strategy and seed tenant ownership;
- the exact stored RunPlan order - one plan per (strategy, seed) pair in
  strategy-major, seed-minor order, with every plan's tenant/campaign/
  world/strategy/seed binding and its recomputed seed-aligned
  realization-aware input hash verified;
- exactly K realizations (one per seed, never K x S) in exact seed order,
  each fully provenance-valid against the authoritative world, seed, and
  embedded uncertainty model (or its verified absence) - any provenance
  failure converts to the safe matrix integrity error;
- exactly one execution per RunPlan in identical order, with every
  run/campaign/world/strategy/seed/input/runtime identity and the
  execution's realization equal to the seed-aligned realization of its
  cell;
- the ordered plan-set hash and ordered result content hashes of every
  execution preserved exactly;
- contiguous cell sequence positions with exact strategy/seed positions,
  and the aggregate ``ordered_world_realization_ids`` /
  ``ordered_world_realization_content_hashes`` tuples with exactly K
  entries.

Hash and identifier rules (repository-wide canonical JSON + SHA-256
conventions only, reusing the Phase 25 identity functions):

- ``realization_trajectory_matrix_identifier(...)``: deterministic from
  the campaign identity, the world identity, and the runtime version.
- ``realization_trajectory_matrix_content_hash(matrix)``: SHA-256 over
  the complete canonical matrix serialization excluding ``content_hash``.
- ``assembled_at`` is the recorded campaign ``created_at`` - never the
  wall clock.

All errors are safe typed domain errors; public messages never expose
state values, hashes, guards, targets, or validation details.
"""

from __future__ import annotations

from kalhas.application.domain_errors import UnsupportedRuntimeVersionError
from kalhas.application.hashing import canonical_json
from kalhas.application.realization_errors import (
    RealizationCampaignTrajectoryMatrixIntegrityError,
    RealizationRunTrajectoryExecutionIntegrityError,
)
from kalhas.application.realization_identity import (
    realization_run_trajectory_execution_content_hash,
    realization_run_trajectory_execution_identifier,
    realization_trajectory_matrix_content_hash,
    realization_trajectory_matrix_identifier,
    verify_realization_provenance,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    run_identifier,
    run_realization_input_hash,
)
from kalhas.application.strategy_trajectory_service import (
    strategy_candidate_content_hash,
)
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.contracts.v1.campaign import CampaignSpec
from kalhas.contracts.v1.realization_campaign_trajectory import (
    RealizationCampaignTrajectoryMatrix,
    RealizationCampaignTrajectoryRunCell,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizationRunTrajectoryExecution,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization

_PLACEHOLDER_HASH = "0" * 64


def _reject(campaign_id: str, reason: str) -> RealizationCampaignTrajectoryMatrixIntegrityError:
    """A generic, safe matrix integrity error with an internal diagnostic reason."""
    return RealizationCampaignTrajectoryMatrixIntegrityError(campaign_id, reason)


def _verify_realization_provenance_converted(
    campaign_id: str,
    run_id: str,
    *,
    world: WorldVersion,
    seed: ScenarioSeed,
    realization: WorldRealization,
) -> None:
    """Verify one realization's provenance; convert failures to the safe matrix error."""
    catalog = extract_world_catalog(world)
    try:
        verify_realization_provenance(
            run_id=run_id,
            world=world,
            seed=seed,
            realization=realization,
            uncertainty_model=catalog.uncertainty_model,
        )
    except RealizationRunTrajectoryExecutionIntegrityError:
        raise _reject(campaign_id, "world realization provenance mismatch") from None


def build_realization_campaign_trajectory_matrix(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    strategies: tuple[StrategyCandidate, ...],
    seeds: tuple[ScenarioSeed, ...],
    run_plans: tuple[RunPlan, ...],
    executions: tuple[RealizationRunTrajectoryExecution, ...],
    realizations: tuple[WorldRealization, ...],
) -> RealizationCampaignTrajectoryMatrix:
    """Build and fully hash the deterministic realization-aware trajectory matrix.

    Requires the realization trajectory runtime version (every plan must
    record exactly 3.0.0; legacy and unsupported matrices raise
    ``UnsupportedRuntimeVersionError``), the exact campaign strategy
    order, the exact shared seed order, and the exact complete strategy x
    seed matrix in the exact stored RunPlan order - missing, additional,
    duplicated, reordered, or foreign runs are rejected. Every plan's
    seed-aligned realization-aware input hash is recomputed with
    ``run_realization_input_hash``. Exactly K realizations (one per seed,
    never K x S) in exact seed order must each be fully provenance-valid
    against the authoritative world, seed, and embedded uncertainty model
    (or its verified absence); every cell binds to its exact RunPlan,
    verified execution, and seed-aligned realization, with every
    run/campaign/world/strategy/seed/input/runtime identity verified.
    The ordered plan-set hash and ordered result content hashes of each
    execution are preserved exactly, and the aggregate
    ``ordered_world_realization_ids`` /
    ``ordered_world_realization_content_hashes`` tuples contain exactly K
    entries. ``assembled_at`` is the recorded campaign ``created_at`` -
    never the wall clock. Nothing here mutates any input, accesses the
    store, or performs execution, replay, transition evaluation,
    observation extraction, or outcome calculation.
    """
    strategy_ids = [strategy.identifier for strategy in strategies]
    seed_ids = [seed.identifier for seed in seeds]

    for plan in run_plans:
        if plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                plan.runtime_version, operation="realization campaign trajectory matrix"
            )
    if strategy_ids != list(campaign.strategy_candidate_ids):
        raise _reject(campaign.identifier, "strategy candidate order mismatch")
    if any(strategy.tenant_id != campaign.tenant_id for strategy in strategies):
        raise _reject(campaign.identifier, "strategy candidate tenant mismatch")
    if seed_ids != [seed.identifier for seed in campaign.seed_ensemble]:
        raise _reject(campaign.identifier, "seed ensemble order mismatch")
    if any(seed.tenant_id != campaign.tenant_id for seed in seeds):
        raise _reject(campaign.identifier, "seed tenant mismatch")
    # Exact canonical seed-content binding: the supplied seeds must be
    # the complete campaign seed objects - not merely same identifiers -
    # so alternate seed material (same id/tenant, different content)
    # can never pass. Canonical JSON serialization keeps bool/int and
    # metadata representation differences fail-closed.
    if canonical_json([seed.model_dump(mode="json") for seed in seeds]) != canonical_json(
        [seed.model_dump(mode="json") for seed in campaign.seed_ensemble]
    ):
        raise _reject(campaign.identifier, "seed ensemble content mismatch")
    if campaign.world_version_id != world.identifier:
        raise _reject(campaign.identifier, "campaign world version mismatch")
    if world.tenant_id != campaign.tenant_id:
        raise _reject(campaign.identifier, "campaign world tenant mismatch")
    if campaign.scenario_id != world.source_scenario_id:
        raise _reject(campaign.identifier, "campaign scenario world mismatch")

    expected_count = len(strategy_ids) * len(seed_ids)
    if len(run_plans) != expected_count:
        raise _reject(campaign.identifier, "run plan matrix length mismatch")
    if len(realizations) != len(seed_ids):
        raise _reject(campaign.identifier, "world realization count mismatch")

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
        realization = realizations[seed_position]
        recomputed_input_hash = run_realization_input_hash(
            runtime_version=plan.runtime_version,
            seed=seed,
            strategy=strategy,
            world_content_hash=world.content_hash,
            world_realization_content_hash=realization.content_hash,
        )
        if recomputed_input_hash != plan.input_hash:
            raise _reject(campaign.identifier, "run plan input hash mismatch")

    if len(realizations) != len(seed_ids):
        raise _reject(campaign.identifier, "world realization count mismatch")
    for position, seed in enumerate(seeds):
        realization = realizations[position]
        if realization.scenario_seed_id != seed.identifier:
            raise _reject(campaign.identifier, "world realization seed order mismatch")
        _verify_realization_provenance_converted(
            campaign.identifier,
            run_identifier(run_plans[position]),
            world=world,
            seed=seed,
            realization=realization,
        )

    if len(executions) != len(run_plans):
        raise _reject(campaign.identifier, "realization execution count mismatch")

    cells: list[RealizationCampaignTrajectoryRunCell] = []
    for position, (plan, execution) in enumerate(zip(run_plans, executions, strict=True)):
        strategy_position = position // len(seed_ids)
        seed_position = position % len(seed_ids)
        strategy = strategies[strategy_position]
        seed = seeds[seed_position]
        realization = realizations[seed_position]
        if execution.run_id != run_identifier(plan):
            raise _reject(campaign.identifier, "realization execution run identity mismatch")
        if execution.run_plan_id != plan.identifier:
            raise _reject(campaign.identifier, "realization execution run plan mismatch")
        if execution.tenant_id != campaign.tenant_id:
            raise _reject(campaign.identifier, "realization execution tenant mismatch")
        if execution.campaign_id != campaign.identifier:
            raise _reject(campaign.identifier, "realization execution campaign mismatch")
        if execution.world_version_id != world.identifier:
            raise _reject(campaign.identifier, "realization execution world version mismatch")
        if execution.world_content_hash != world.content_hash:
            raise _reject(campaign.identifier, "realization execution world content hash mismatch")
        if execution.strategy_candidate_id != plan.strategy_candidate_id:
            raise _reject(campaign.identifier, "realization execution strategy mismatch")
        if execution.strategy_content_hash != strategy_candidate_content_hash(strategy):
            raise _reject(
                campaign.identifier,
                "realization execution strategy content hash mismatch",
            )
        if execution.scenario_seed_id != plan.scenario_seed_id:
            raise _reject(campaign.identifier, "realization execution scenario seed mismatch")
        if execution.input_hash != plan.input_hash:
            raise _reject(campaign.identifier, "realization execution input hash mismatch")
        if execution.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
            raise _reject(campaign.identifier, "realization execution runtime version mismatch")
        if execution.identifier != realization_run_trajectory_execution_identifier(
            run_id=execution.run_id,
            runtime_version=execution.runtime_version,
        ):
            raise _reject(campaign.identifier, "realization execution identifier mismatch")
        if execution.content_hash != realization_run_trajectory_execution_content_hash(execution):
            raise _reject(campaign.identifier, "realization execution content hash mismatch")
        if execution.world_realization_id != realization.identifier:
            raise _reject(campaign.identifier, "realization execution realization mismatch")
        if execution.world_realization_content_hash != realization.content_hash:
            raise _reject(
                campaign.identifier, "realization execution realization content hash mismatch"
            )
        cells.append(
            RealizationCampaignTrajectoryRunCell(
                sequence_position=position,
                strategy_position=strategy_position,
                seed_position=seed_position,
                run_id=execution.run_id,
                run_plan_id=plan.identifier,
                strategy_candidate_id=plan.strategy_candidate_id,
                scenario_seed_id=plan.scenario_seed_id,
                input_hash=plan.input_hash,
                realization_run_trajectory_execution_id=execution.identifier,
                realization_run_trajectory_execution_content_hash=execution.content_hash,
                trajectory_plan_set_hash=execution.trajectory_plan_set_hash,
                result_content_hashes=tuple(result.content_hash for result in execution.results),
                world_realization_id=realization.identifier,
                world_realization_content_hash=realization.content_hash,
            )
        )

    matrix = RealizationCampaignTrajectoryMatrix(
        identifier=realization_trajectory_matrix_identifier(
            campaign_id=campaign.identifier,
            world_version_id=world.identifier,
            runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        ),
        tenant_id=campaign.tenant_id,
        campaign_id=campaign.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
        ordered_strategy_candidate_ids=tuple(strategy_ids),
        ordered_scenario_seed_ids=tuple(seed_ids),
        ordered_world_realization_ids=tuple(realization.identifier for realization in realizations),
        ordered_world_realization_content_hashes=tuple(
            realization.content_hash for realization in realizations
        ),
        cells=tuple(cells),
        content_hash=_PLACEHOLDER_HASH,
        assembled_at=campaign.created_at,
    )
    return matrix.model_copy(
        update={"content_hash": realization_trajectory_matrix_content_hash(matrix)}
    )
