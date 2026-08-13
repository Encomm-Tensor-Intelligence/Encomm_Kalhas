"""Runtime-3.0.0 realization-aware campaign preparation and preflight (Phase 25).

``prepare_realization_campaign`` mirrors the historical
``prepare_campaign`` orchestration exactly (scenario/world ownership and
identity, compiled-world integrity before LEGION, strategy-request and
seed tenant checks, the five-candidate LEGION contract, in-memory
``CampaignSpec``/``CampaignStatus`` construction, then a single write
phase) and adds the Phase 24/25 realization seam: the verified embedded
world catalog is extracted, the stored-vs-embedded uncertainty-model
consistency is enforced in every direction, the
``CampaignWorldRealizationMatrix`` is built exactly once (one realization
per seed, never per strategy, never stored), and the runtime-3 run-plan
matrix is planned with ``plan_realization_runs`` so every strategy
sharing a seed is bound to the identical realization content hash.

``preflight_realization_run_plan_matrix`` is the read-only runtime-3
counterpart of the Phase 18 preflight: it re-derives the exact stored
plan matrix from immutable records and requires exact tuple equality,
then passes every expected run through the version-dispatched input
verifier. It never writes, never calls LEGION, and never evaluates a
trajectory.

Both services accept exactly runtime ``3.0.0``; any other value raises
:class:`UnsupportedRuntimeVersionError` before any store read, LEGION
call, realization build, or write. All failures before the write phase
produce zero campaign/run writes.
"""

from __future__ import annotations

from kalhas.adapters.legion import LegionAdapter
from kalhas.application.campaign_service import EXPECTED_STRATEGY_SET_SIZE, PreparedCampaign
from kalhas.application.domain_errors import (
    CampaignPreparationError,
    RunInputIntegrityError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldScenarioMismatchError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_world_uncertainty_model,
)
from kalhas.application.input_integrity import verify_run_inputs
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
    run_identifier,
)
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
)
from kalhas.application.world_uncertainty_errors import (
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_identity import (
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState, CampaignStatus
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import AwareDatetime
from kalhas.contracts.v1.strategy import StrategyRequest
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization


def _verify_stored_embedded_model_consistency(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
    world: WorldVersion,
) -> None:
    """Enforce the stored-vs-embedded uncertainty-model consistency rules.

    When the verified compiled world embeds an uncertainty model, the
    stored declaration must exist, strictly revalidate against its
    contract, pass deterministic identity verification, and be exactly
    JSON-equal to the embedded snapshot. When the world embeds no model,
    no stored declaration may exist. Corrupt stored models keep their
    existing :class:`WorldUncertaintyModelIntegrityError`; missing or
    mismatched stored-vs-embedded state fails closed with the safe
    :class:`RunInputIntegrityError` (the ``campaign_id`` fills the
    error's identifier slot; the public message stays generic). This is
    the campaign-scoped counterpart of the run-scoped reconstruction
    rule - preparation never builds per-run realizations here.
    """
    catalog = extract_world_catalog(world)
    embedded = catalog.uncertainty_model
    scenario_id = world.source_scenario_id
    if embedded is not None:
        try:
            stored = store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError:
            raise RunInputIntegrityError(
                campaign_id, reason="stored uncertainty model missing"
            ) from None
        revalidate_stored_world_uncertainty_model(stored, tenant_id, scenario_id)
        verify_world_uncertainty_model_identity(
            stored, tenant_id=tenant_id, scenario_id=scenario_id
        )
        if stored.model_dump(mode="json") != embedded.model_dump(mode="json"):
            raise RunInputIntegrityError(
                campaign_id, reason="stored and embedded uncertainty model mismatch"
            )
    else:
        try:
            store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError:
            pass
        else:
            raise RunInputIntegrityError(
                campaign_id,
                reason="stored uncertainty model exists without an embedded model",
            )


def prepare_realization_campaign(
    *,
    store: InMemoryScenarioStore,
    legion: LegionAdapter,
    tenant_id: str,
    scenario_id: str,
    world_version_id: str,
    strategy_request: StrategyRequest,
    campaign_id: str,
    campaign_name: str,
    seed_ensemble: tuple[ScenarioSeed, ...],
    created_at: AwareDatetime,
    runtime_version: str = REALIZATION_TRAJECTORY_RUNTIME_VERSION,
) -> PreparedCampaign:
    """Prepare a runtime-3.0.0 campaign: verify, realize, plan, then store.

    The runtime gate runs before any store read, world verification,
    LEGION call, realization build, or write: exactly ``3.0.0`` is
    accepted; ``1.0.0``, ``2.0.0``, and every unknown value raise a
    typed :class:`UnsupportedRuntimeVersionError`. The pipeline mirrors
    ``prepare_campaign`` (scenario/world ownership and identity,
    compiled-world integrity, strategy-request/seed tenant checks, the
    five-candidate LEGION contract with unique identifiers and identical
    ordered observation permissions), then enforces the stored-vs-embedded
    uncertainty-model consistency, builds the
    ``CampaignWorldRealizationMatrix`` exactly once (K seeds produce
    exactly K realizations, never K x S; the matrix is derived in memory
    and never stored), plans the strategy-major/seed-minor run matrix with
    :func:`plan_realization_runs` (every strategy sharing a seed binds the
    identical realization content hash into its runtime-3 input hash), and
    only then writes the campaign + COMPILED status, ordered run plans,
    ordered strategy candidates, and one PLANNED ``RunStatus`` per plan.
    Any failure before the write phase produces zero writes; no input is
    mutated; no trajectory is evaluated.
    """
    if runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            runtime_version, operation="realization campaign preparation"
        )
    scenario = store.get_scenario(tenant_id, scenario_id)
    world = store.get_world(tenant_id, world_version_id)
    if world.source_scenario_id != scenario.identifier:
        raise WorldScenarioMismatchError(world_version_id, scenario.identifier)
    # Compiled-world integrity is verified before LEGION is called and
    # before any campaign/run state is written: a corrupted or
    # non-compiler world must never be planned against.
    try:
        manifest = store.get_manifest(tenant_id, world_version_id)
    except WorldNotFoundError:
        raise WorldSnapshotIntegrityError(
            world_version_id, reason="world manifest missing"
        ) from None
    verify_world_snapshot(world, manifest)
    if strategy_request.scenario_id != scenario.identifier:
        raise CampaignPreparationError(
            f"strategy_request.scenario_id {strategy_request.scenario_id!r} does not match "
            f"scenario {scenario.identifier!r}"
        )
    if strategy_request.tenant_id != tenant_id:
        raise CampaignPreparationError(
            f"strategy_request tenant_id {strategy_request.tenant_id!r} does not match "
            f"tenant {tenant_id!r}"
        )
    for seed in seed_ensemble:
        if seed.tenant_id != tenant_id:
            raise CampaignPreparationError(
                f"seed {seed.identifier!r} tenant_id {seed.tenant_id!r} does not match "
                f"tenant {tenant_id!r}"
            )

    catalog = extract_world_catalog(world)
    _verify_stored_embedded_model_consistency(
        store=store,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        world=world,
    )

    candidates = legion.request_strategies(strategy_request)
    if len(candidates) != EXPECTED_STRATEGY_SET_SIZE:
        raise CampaignPreparationError(
            f"expected {EXPECTED_STRATEGY_SET_SIZE} strategy candidates, got {len(candidates)}"
        )
    candidate_ids = [candidate.identifier for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise CampaignPreparationError("returned strategy candidate identifiers must be unique")
    expected_observations = [obs.model_dump() for obs in strategy_request.required_observations]
    for candidate in candidates:
        if candidate.tenant_id != tenant_id:
            raise CampaignPreparationError(
                f"candidate {candidate.identifier!r} tenant_id {candidate.tenant_id!r} does not "
                f"match tenant {tenant_id!r}"
            )
        if [obs.model_dump() for obs in candidate.required_observations] != expected_observations:
            raise CampaignPreparationError(
                f"candidate {candidate.identifier!r} does not share identical ordered "
                "observation permissions with the requested strategy set"
            )

    campaign = CampaignSpec(
        identifier=campaign_id,
        tenant_id=tenant_id,
        name=campaign_name,
        scenario_id=scenario.identifier,
        world_version_id=world.identifier,
        strategy_candidate_ids=candidate_ids,
        seed_ensemble=seed_ensemble,
        created_at=created_at,
    )
    status = CampaignStatus(
        identifier=f"status-{campaign_id}",
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        state=CampaignState.COMPILED,
        changed_at=created_at,
        message="campaign prepared",
    )
    matrix = build_campaign_world_realization_matrix(
        campaign=campaign,
        world=world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
    )
    realizations: dict[str, WorldRealization] = {
        realization.scenario_seed_id: realization for realization in matrix.realizations
    }
    plans = plan_realization_runs(
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=candidates,
        seeds=seed_ensemble,
        created_at=created_at,
        realizations=realizations,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    )
    store.put_campaign(campaign, status)
    store.put_run_plans(tenant_id, campaign_id, plans)
    store.put_strategy_candidates(tenant_id, campaign_id, candidates)
    for plan in plans:
        run_id = run_identifier(plan)
        store.put_run_status(
            tenant_id,
            run_id,
            RunStatus(
                identifier=f"status-{run_id}",
                tenant_id=tenant_id,
                run_id=run_id,
                campaign_id=campaign_id,
                run_plan_id=plan.identifier,
                state=RunState.PLANNED,
                runtime_version=plan.runtime_version,
                input_hash=plan.input_hash,
                created_at=plan.created_at,
                changed_at=plan.created_at,
            ),
        )
    return PreparedCampaign(campaign=campaign, status=status, run_plans=plans)


def preflight_realization_run_plan_matrix(
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
) -> None:
    """Verify the campaign's exact stored runtime-3 run-plan matrix.

    The read-only runtime-3 counterpart of the Phase 18 preflight: the
    stored strategy candidate tuple must equal the campaign's
    ``strategy_candidate_ids`` exactly (identifiers and order); the
    stored run-plan matrix must be present and record exactly ``3.0.0``;
    the verified embedded catalog is re-extracted and the stored-vs-
    embedded uncertainty-model consistency is re-enforced; the
    ``CampaignWorldRealizationMatrix`` is rebuilt deterministically from
    ``campaign.created_at``; the expected runtime-3 plan matrix is
    recomputed with :func:`plan_realization_runs` over the exact
    campaign identity, the verified world, the exact stored candidates,
    the campaign seed ensemble, the rebuilt per-seed realizations, and
    the recorded runtime; and exact tuple equality is required - missing,
    additional, duplicated, reordered, mixed-runtime, or tampered plans
    are rejected with safe typed errors. Every expected run then passes
    the existing version-dispatched input verification. Verification is
    read-only: no manifest, event, lifecycle transition, or artifact is
    written, LEGION is never called, and no trajectory is evaluated.
    """
    stored_candidates = store.get_strategy_candidates(tenant_id, campaign.identifier)
    if [candidate.identifier for candidate in stored_candidates] != list(
        campaign.strategy_candidate_ids
    ):
        raise RunInputIntegrityError(
            campaign.identifier, reason="stored strategy candidate collection mismatch"
        )
    stored_plans = store.get_run_plans(tenant_id, campaign.identifier)
    if not stored_plans:
        raise RunInputIntegrityError(campaign.identifier, reason="stored run-plan matrix missing")
    recorded_version = stored_plans[0].runtime_version
    if recorded_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(
            recorded_version, operation="trajectory plan preparation"
        )
    catalog = extract_world_catalog(world)
    _verify_stored_embedded_model_consistency(
        store=store,
        tenant_id=tenant_id,
        campaign_id=campaign.identifier,
        world=world,
    )
    matrix = build_campaign_world_realization_matrix(
        campaign=campaign,
        world=world,
        state_models=catalog.state_models,
        model=catalog.uncertainty_model,
    )
    realizations: dict[str, WorldRealization] = {
        realization.scenario_seed_id: realization for realization in matrix.realizations
    }
    expected_plans = plan_realization_runs(
        campaign_id=campaign.identifier,
        tenant_id=tenant_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        strategies=stored_candidates,
        seeds=campaign.seed_ensemble,
        created_at=campaign.created_at,
        realizations=realizations,
        runtime_version=REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    )
    if stored_plans != expected_plans:
        raise RunInputIntegrityError(campaign.identifier, reason="stored run-plan matrix mismatch")
    for plan in expected_plans:
        verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_identifier(plan))
