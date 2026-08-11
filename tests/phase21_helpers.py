"""Shared helpers for Phase 21 campaign metric-observation matrix tests.

Builds real compiler-consistent runtime-2.0.0 campaigns over a world
embedding Phase 19 ``DomainMetricObservationBinding`` snapshots: prepared
trajectory-plan collections through the Phase 15 service, started
campaigns, every planned run executed COMPLETE with a stored verified
``RunTrajectoryExecution``, and - when requested - an explicit Phase 20
``extract_run_metric_observations`` for every run, so the complete
verified Phase 20 collection exists exactly once per trajectory cell.

The helpers never hide setup failures: every step uses the real
services and store getters, and a failing extraction propagates its
typed error.
"""

from __future__ import annotations

from kalhas.adapters.mocks import MockLegionAdapter
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_metric_observation_service import (
    extract_run_metric_observations,
)
from kalhas.application.run_planner import TRAJECTORY_RUNTIME_VERSION, run_identifier
from kalhas.application.strategy_trajectory_service import (
    prepare_strategy_trajectory_plans,
)
from kalhas.application.structural_runtime import execute_campaign
from kalhas.contracts.v1.scenario import ScenarioSeed

from tests.phase4_helpers import TENANT, build_seed, prepare, start
from tests.phase20_helpers import build_observation_store, compile_observation_world


def complete_observation_campaign(
    *,
    store: InMemoryScenarioStore | None = None,
    seeds: tuple[ScenarioSeed, ...] = (build_seed(),),
    campaign_id: str = "campaign-1",
    with_bindings: bool = True,
    with_transition: bool = True,
    execute: bool = True,
    extract: bool = True,
) -> tuple[InMemoryScenarioStore, str, tuple[str, ...]]:
    """A COMPLETE runtime-2.0.0 campaign with verified observation sets.

    Returns ``(store, world_version_id, run_ids)`` where ``run_ids`` are
    the deterministic run identifiers in exact stored RunPlan order
    (strategy-major, seed-minor). The campaign is prepared under runtime
    2.0.0 with the mock strategy ensemble and the supplied shared seed
    ensemble, its complete trajectory-plan collection is prepared
    through the Phase 15 service, the campaign is started, every planned
    run is executed (COMPLETE with a stored ``RunTrajectoryExecution``)
    unless ``execute`` is false, and - when ``extract`` is true - the
    explicit Phase 20 extraction runs for every planned run so the
    complete verified ``RunMetricObservationSet`` collection exists.
    With ``with_bindings`` false the compiled world embeds no
    observation bindings and every extracted set is empty.
    """
    effective_store = build_observation_store(
        store=store,
        with_bindings=with_bindings,
        with_transition=with_transition,
    )
    world_version_id = compile_observation_world(effective_store)
    prepare(
        effective_store,
        world_version_id,
        runtime_version=TRAJECTORY_RUNTIME_VERSION,
        legion=MockLegionAdapter(),
        seeds=seeds,
        campaign_id=campaign_id,
    )
    prepare_strategy_trajectory_plans(
        store=effective_store,
        legion=MockLegionAdapter(),
        tenant_id=TENANT,
        campaign_id=campaign_id,
    )
    start(effective_store, campaign_id)
    if execute:
        execute_campaign(store=effective_store, tenant_id=TENANT, campaign_id=campaign_id)
    run_ids = tuple(
        run_identifier(plan) for plan in effective_store.get_run_plans(TENANT, campaign_id)
    )
    if extract and execute:
        for run_id in run_ids:
            extract_run_metric_observations(store=effective_store, tenant_id=TENANT, run_id=run_id)
    return effective_store, world_version_id, run_ids
