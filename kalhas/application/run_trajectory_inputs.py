"""Run trajectory input verification and resolution (Phase 16).

Resolves the exact trajectory inputs of one recorded run, branching only
on the recorded runtime version. The verifier first calls the existing
run-input integrity verifier, then - for runtime version 2.0.0 - loads
the campaign's complete trajectory-plan collection through the Phase 15
service getter (full collection-level integrity verification), builds
the same closed compiled-world catalogs planning uses, and selects
exactly the plans whose strategy matches the run's recorded strategy:
one plan for every transition-capable state model in canonical order,
with missing, additional, duplicated, reordered, foreign, or mismatched
plans rejected. A verified world with no transition-capable state models
resolves to an empty plan tuple whether the prepared collection is
absent or the successfully prepared empty tuple; a transition-capable
world without a prepared collection raises a typed
``TrajectoryPlansRequiredError``. Legacy 1.0.0 runs preserve the
structural-only behavior and never consume trajectory plans; unsupported
versions are rejected safely.

This verifier is **read-only**: it never evaluates anything, never
records manifests, never changes lifecycle, and never exposes private
mutable store objects - every returned record is a fresh deep copy from
the store's snapshot-isolation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass

from kalhas.application.domain_errors import (
    RunTrajectoryExecutionIntegrityError,
    TrajectoryPlansNotFoundError,
    TrajectoryPlansRequiredError,
    UnsupportedRuntimeVersionError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.input_integrity import VerifiedRunInputs, verify_run_inputs
from kalhas.application.run_planner import (
    LEGACY_STRUCTURAL_RUNTIME_VERSION,
    TRAJECTORY_RUNTIME_VERSION,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    closed_world_catalogs,
    get_strategy_trajectory_plans,
    strategy_candidate_content_hash,
)
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan


@dataclass(frozen=True)
class VerifiedRunTrajectoryInputs:
    """The exact verified trajectory inputs of one run.

    ``inputs`` is the verified run-input set (identity, world, strategy,
    seed, status, integrity manifest). For trajectory-runtime runs,
    ``plans`` is the exact applicable plan tuple (the run's strategy
    subset, one plan per transition-capable state model in canonical
    order; empty for a world with no transition-capable models) and
    ``catalogs`` is the closed transition-capable catalog set of the
    verified compiled world (empty for legacy runs, which never consume
    trajectory plans).
    """

    inputs: VerifiedRunInputs
    plans: tuple[StrategyTrajectoryPlan, ...]
    catalogs: tuple[ModelTrajectoryCatalog, ...]


def _reject(run_id: str, reason: str) -> RunTrajectoryExecutionIntegrityError:
    """A generic, safe integrity error with an internal diagnostic reason."""
    return RunTrajectoryExecutionIntegrityError(run_id, reason)


def verify_run_trajectory_inputs(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    run_id: str,
) -> VerifiedRunTrajectoryInputs:
    """Load and verify a run's recorded trajectory inputs; returns them for use.

    Branches only on the recorded runtime version (never on a
    caller-supplied value). Raises the typed input-integrity error for
    inconsistent recorded inputs, ``TrajectoryPlansRequiredError`` for a
    transition-capable world without a prepared plan collection, and
    ``UnsupportedRuntimeVersionError`` for any other recorded version.
    Any tampered plan collection is rejected by the Phase 15 service
    getter with its own typed integrity error before a plan field is
    trusted. Read-only: nothing is evaluated, recorded, or changed.
    """
    verified = verify_run_inputs(store=store, tenant_id=tenant_id, run_id=run_id)
    recorded_version = verified.run_plan.runtime_version

    if recorded_version == LEGACY_STRUCTURAL_RUNTIME_VERSION:
        # Legacy structural-only behavior: trajectory plans are never
        # required, loaded, or consumed.
        return VerifiedRunTrajectoryInputs(inputs=verified, plans=(), catalogs=())

    if recorded_version != TRAJECTORY_RUNTIME_VERSION:
        raise UnsupportedRuntimeVersionError(recorded_version, operation="trajectory resolution")

    # Phase 15 collection-level integrity: the service getter verifies
    # the complete stored collection - matrix length and order, unique
    # identifiers and pairs, per-plan identifier/content hash, ownership,
    # and closed-catalog reference membership - before returning it. An
    # absent collection means "not prepared" (the prepared empty tuple
    # and "not prepared" are deliberately distinguishable).
    try:
        collection = get_strategy_trajectory_plans(
            store=store, tenant_id=tenant_id, campaign_id=verified.run_plan.campaign_id
        )
    except TrajectoryPlansNotFoundError:
        collection = None

    catalogs = closed_world_catalogs(verified.world)

    if not catalogs:
        # A verified world with no transition-capable state models: an
        # absent or successfully prepared empty collection resolves to an
        # empty plan tuple; the service getter already rejected any
        # non-empty collection for such a world (defense in depth here).
        if collection:
            raise _reject(run_id, "unexpected trajectory plans for a world with no transitions")
        return VerifiedRunTrajectoryInputs(inputs=verified, plans=(), catalogs=())

    if not collection:
        raise TrajectoryPlansRequiredError(run_id)

    selected = tuple(
        plan for plan in collection if plan.strategy_candidate_id == verified.strategy.identifier
    )
    expected_pairs = [
        (verified.strategy.identifier, catalog.state_model.identifier) for catalog in catalogs
    ]
    actual_pairs = [(plan.strategy_candidate_id, plan.state_model_identifier) for plan in selected]
    if actual_pairs != expected_pairs:
        raise _reject(run_id, "trajectory plan selection does not match the run strategy")
    for plan in selected:
        if plan.strategy_content_hash != strategy_candidate_content_hash(verified.strategy):
            raise _reject(run_id, "trajectory plan strategy content hash mismatch")

    return VerifiedRunTrajectoryInputs(inputs=verified, plans=selected, catalogs=catalogs)
