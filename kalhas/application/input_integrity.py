"""Deterministic run-input integrity verification.

Derives and verifies a run's recorded inputs using only recorded state:
RunPlan, immutable WorldVersion, the exact stored StrategyCandidate, the
ScenarioSeed from the campaign's recorded seed ensemble, RunStatus, campaign
identity, and the recorded runtime version. The recomputed SHA-256 input
hash must match the RunPlan and RunStatus input hashes exactly.

Never repairs, overwrites, normalizes, or silently accepts a mismatch: any
missing, inconsistent, or mismatched recorded input raises
:class:`RunInputIntegrityError`. The verifier is read-only with respect to
lifecycle and events - it only loads recorded state and returns a manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    RunInputIntegrityError,
    WorldNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier, run_input_hash
from kalhas.application.world_integrity import verify_world_snapshot
from kalhas.contracts.v1.execution import RunStatus
from kalhas.contracts.v1.integrity import RunInputIntegrityManifest
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion


@dataclass(frozen=True)
class VerifiedRunInputs:
    """The exact recorded inputs of a run, loaded and verified."""

    run_plan: RunPlan
    world: WorldVersion
    strategy: StrategyCandidate
    seed: ScenarioSeed
    status: RunStatus
    manifest: RunInputIntegrityManifest


def _integrity(run_id: str, reason: str) -> RunInputIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return RunInputIntegrityError(run_id, reason)


def verify_run_inputs(
    *, store: InMemoryScenarioStore, tenant_id: str, run_id: str
) -> VerifiedRunInputs:
    """Load and verify a run's recorded inputs; returns them for use.

    Raises RunInputIntegrityError (or the store's typed not-found error for
    an unknown or foreign run) on any missing, inconsistent, or mismatched
    recorded input.
    """
    status = store.get_run_status(tenant_id, run_id)
    if status.tenant_id != tenant_id:
        raise _integrity(run_id, "run status tenant mismatch")
    if status.identifier != f"status-{run_id}":
        raise _integrity(run_id, "run status identifier mismatch")

    plans = store.get_run_plans(tenant_id, status.campaign_id)
    run_plan = next((plan for plan in plans if plan.identifier == status.run_plan_id), None)
    if run_plan is None:
        raise _integrity(run_id, "run plan missing")
    if status.campaign_id != run_plan.campaign_id:
        raise _integrity(run_id, "run status campaign mismatch")
    if status.run_plan_id != run_plan.identifier:
        raise _integrity(run_id, "run plan reference mismatch")
    if status.runtime_version != run_plan.runtime_version:
        raise _integrity(run_id, "runtime version mismatch")
    if status.input_hash != run_plan.input_hash:
        raise _integrity(run_id, "input hash mismatch between status and plan")
    if run_plan.tenant_id != tenant_id:
        raise _integrity(run_id, "run plan tenant mismatch")
    if run_identifier(run_plan) != run_id:
        raise _integrity(run_id, "run identifier mismatch")

    try:
        campaign = store.get_campaign(tenant_id, run_plan.campaign_id)
    except CampaignNotFoundError:
        raise _integrity(run_id, "campaign missing") from None
    if campaign.tenant_id != tenant_id:
        raise _integrity(run_id, "campaign tenant mismatch")
    if campaign.identifier != run_plan.campaign_id:
        raise _integrity(run_id, "campaign identifier mismatch")
    if campaign.world_version_id != run_plan.world_version_id:
        raise _integrity(run_id, "campaign world version mismatch")

    try:
        world = store.get_world(tenant_id, run_plan.world_version_id)
    except WorldNotFoundError:
        raise _integrity(run_id, "world missing") from None
    if world.tenant_id != tenant_id:
        raise _integrity(run_id, "world tenant mismatch")
    if world.identifier != run_plan.world_version_id:
        raise _integrity(run_id, "world version mismatch")
    if world.source_scenario_id != campaign.scenario_id:
        raise _integrity(run_id, "world source scenario mismatch")

    # Compiled-world integrity is verified before the world is trusted
    # for input-hash recomputation: a corrupted or non-compiler world
    # raises WorldSnapshotIntegrityError and is never accepted.
    try:
        world_manifest = store.get_manifest(tenant_id, world.identifier)
    except WorldNotFoundError:
        raise _integrity(run_id, "world manifest missing") from None
    verify_world_snapshot(world, world_manifest)

    try:
        candidates = store.get_strategy_candidates(tenant_id, run_plan.campaign_id)
    except CampaignNotFoundError:
        raise _integrity(run_id, "strategy candidates missing") from None
    strategy = next(
        (
            candidate
            for candidate in candidates
            if candidate.identifier == run_plan.strategy_candidate_id
        ),
        None,
    )
    if strategy is None:
        raise _integrity(run_id, "strategy candidate missing")
    if strategy.tenant_id != tenant_id:
        raise _integrity(run_id, "strategy candidate tenant mismatch")
    if strategy.identifier not in campaign.strategy_candidate_ids:
        raise _integrity(run_id, "strategy not in campaign strategy set")

    seed = next(
        (seed for seed in campaign.seed_ensemble if seed.identifier == run_plan.scenario_seed_id),
        None,
    )
    if seed is None:
        raise _integrity(run_id, "scenario seed missing")
    if seed.tenant_id != tenant_id:
        raise _integrity(run_id, "scenario seed tenant mismatch")

    recomputed = run_input_hash(
        world_content_hash=world.content_hash,
        strategy=strategy,
        seed=seed,
        runtime_version=run_plan.runtime_version,
    )
    if recomputed != run_plan.input_hash:
        raise _integrity(run_id, "recomputed input hash mismatch")
    if recomputed != status.input_hash:
        raise _integrity(run_id, "recomputed input hash mismatch against status")

    integrity_manifest = RunInputIntegrityManifest(
        identifier=f"integrity-{run_id}",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=run_plan.campaign_id,
        run_plan_id=run_plan.identifier,
        world_version_id=world.identifier,
        strategy_candidate_id=strategy.identifier,
        scenario_seed_id=seed.identifier,
        runtime_version=run_plan.runtime_version,
        expected_input_hash=status.input_hash,
        recomputed_input_hash=recomputed,
        verification_classification="exact",
        recorded_at=run_plan.created_at,
    )
    return VerifiedRunInputs(
        run_plan=run_plan,
        world=world,
        strategy=strategy,
        seed=seed,
        status=status,
        manifest=integrity_manifest,
    )
