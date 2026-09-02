"""Read-only runtime-4 adaptive campaign planning authority (H28-S08B).

This module is the deterministic, domain-neutral, **read-only** runtime-4
campaign planning seam for exactly one already-existing COMPILED campaign.
It derives the exact :class:`~kalhas.contracts.v1.run_plan.RunPlan` tuple
of the accepted pure planner (:func:`plan_adaptive_runs`, H28-S08A) from
**stored immutable authority only**. The one internal verification this
module performs - against the campaign's already-stored runtime-3 plan
matrix - is read-only and fail-closed: there is no persistence, no
execution, no replay, no query projection, and no historical-runtime
reinterpretation (ADR-004).

Derivation semantics (frozen by this slice):

- **Runtime gate before any store read.** Exactly ``4.0.0`` is accepted;
  the historical ``1.0.0``, ``2.0.0``, and ``3.0.0`` literals - and every
  unknown value - raise :class:`UnsupportedRuntimeVersionError` before
  the first store read, before any stored authority is inspected, and
  before any matrix or plan is built. Historical runtimes keep their
  exact meaning in their untouched services.

- **Stored authority only.** The exact tenant-scoped
  :class:`~kalhas.contracts.v1.campaign.CampaignSpec` and
  :class:`~kalhas.contracts.v1.campaign.CampaignStatus` (state exactly
  ``COMPILED``), the scenario, the compiled world and manifest
  (snapshot-verified), the verified embedded world catalog, the exact
  stored ordered :class:`~kalhas.contracts.v1.strategy.StrategyCandidate`
  collection, the stored :class:`~kalhas.contracts.v1.adaptive_policy.AdaptivePolicy`,
  and the stored-vs-embedded uncertainty-model consistency are loaded
  and validated - never accepted from the caller. The caller supplies
  only the deterministic tenant and campaign identifiers.

- **One matrix, one planner call.** The
  :class:`~kalhas.contracts.v1.world_realization.CampaignWorldRealizationMatrix`
  is built **exactly once** from the campaign's ordered seed ensemble,
  the verified world, and the catalog/uncertainty-model authority; the
  per-seed realization mapping is resolved from that single matrix; and
  :func:`plan_adaptive_runs` is called **exactly once**. One seed
  produces one shared strategy-independent
  :class:`~kalhas.contracts.v1.world_realization.WorldRealization`: no
  strategy, action, policy rule, branch count, or evaluation path can
  alter realization derivation, and ``K`` ordered seeds yield exactly
  ``K`` plans in the campaign's exact seed order (never ``K x S``).

- **Independent runtime-3 seed authority.** The runtime-3 RunPlan tuple
  written when the campaign was prepared predates this derivation and is
  therefore an independent authority over the exact seed content. Before
  any runtime-4 plan is built, the expected runtime-3 plan tuple is
  recomputed with the accepted pure runtime-3 planner
  (:func:`~kalhas.application.run_planner.plan_realization_runs` - the
  existing planning identity semantics, reused and not duplicated or
  altered) over the verified world, the exact stored runtime-3
  candidates, the campaign's ordered seed ensemble, the recorded
  ``campaign.created_at``, and the per-seed realizations of the single
  matrix this service already built; exact tuple equality with the
  stored tuple is required. A tampered, missing, extra, reordered,
  duplicated, or mixed-runtime seed therefore disagrees with the
  persisted original matrix and fails closed atomically. The stored
  tuple is only read: it is never reinterpreted, rewritten, repaired,
  or executed, and no second matrix and no additional runtime-4 planner
  call exist.

- **Campaign authority is never replaced.** The plan derivation uses the
  campaign's immutable identifier, tenant, world identity and verified
  content hash, the exact stored policy, and the recorded
  ``campaign.created_at`` - caller replacements for any recorded
  authority do not exist in the signature.

- **Fairness invariant (Phase 28 / ADR-004 D28-03).** The realization
  coordinate is strategy-independent by construction; the stored policy
  enters planning only through the accepted planner's binding of the
  policy authority into each plan's input hash. Policy rules are never
  evaluated, no branch is taken, no observation is drawn, and no
  execution occurs here; observation-noise derivation remains the
  authority of the existing runtime-observation surface and is never
  introduced in this module.

- **Fail closed, atomically.** Missing, foreign, corrupt, reordered,
  duplicated, mixed-runtime, or contradictory campaign/world/candidate/
  policy/uncertainty/realization authority fails closed with the
  narrowest established typed domain error before any tuple is
  returned: there is no partial output, no repair, no default, and no
  write of any kind. Raw ``AttributeError``/``KeyError``/``IndexError``/
  ``TypeError``/``ValueError`` escaping from untrusted or stored
  authority inspection are converted to the established safe typed
  error.

- **Forbidden surfaces.** No store write, update, or delete; no LEGION
  or NEXUS call; no execution; no replay; no policy evaluation or state
  transition; no observation or noise draw; no clock; no global RNG; no
  provider, network, callback, dynamic import, ``eval``, or ``exec``.
  The service is pure with respect to repository/application state and
  returns plans equal across repeated derivations and detached from any
  stored authority: mutating a returned plan object cannot alter the store
  fingerprint, a separately derived tuple, or a fresh later derivation.
"""

from __future__ import annotations

from typing import Any, Literal

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyBindingValidationError,
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.adaptive_policy_identity import (
    verify_adaptive_policy_identity,
)
from kalhas.application.adaptive_run_planner import (
    ADAPTIVE_RUNTIME_VERSION,
    plan_adaptive_runs,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    KalhasDomainError,
    ScenarioNotFoundError,
    TrajectoryPlansNotFoundError,
    UnsupportedRuntimeVersionError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.in_memory_store import (
    InMemoryScenarioStore,
    revalidate_stored_world_uncertainty_model,
)
from kalhas.application.run_planner import (
    REALIZATION_TRAJECTORY_RUNTIME_VERSION,
    plan_realization_runs,
)
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.application.world_realization_builder import (
    build_campaign_world_realization_matrix,
)
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.application.world_uncertainty_identity import (
    verify_world_uncertainty_model_identity,
)
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.strategy import StrategyCandidate
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import (
    CampaignWorldRealizationMatrix as _CampaignWorldRealizationMatrix,
)
from kalhas.contracts.v1.world_realization import WorldUncertaintyModel

#: The additive adaptive runtime version. Exactly ``4.0.0`` is accepted
#: for adaptive campaign planning authority; every other value - including
#: the historical ``1.0.0``, ``2.0.0``, and ``3.0.0`` literals owned by
#: :mod:`kalhas.application.run_planner` - is rejected before any store
#: read or other authority inspection.
RUNTIME_VERSION: Literal["4.0.0"] = ADAPTIVE_RUNTIME_VERSION


def _reject(tenant_id: str, campaign_id: str, reason: str) -> AdaptivePolicyBindingValidationError:
    """A safe typed planning-authority failure with an internal reason."""
    return AdaptivePolicyBindingValidationError(tenant_id, campaign_id, reason=reason)


def _load_verified_world(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
) -> WorldVersion:
    """Load and verify the campaign's exact scenario/world/manifest authority.

    ``campaign`` is the already-verified tenant-scoped
    :class:`~kalhas.contracts.v1.campaign.CampaignSpec` whose
    ``world_version_id`` selects the world and manifest authority;
    ``campaign_id`` remains the rejection-context identifier.
    """
    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="world authority missing") from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="world authority corrupt") from exc
    return world


def _verify_stored_embedded_model_consistency(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_id: str,
    embedded: WorldUncertaintyModel | None,
) -> WorldUncertaintyModel | None:
    """Enforce the established stored-vs-embedded uncertainty-model rules.

    When the verified compiled world embeds an uncertainty model, the
    stored declaration must exist, strictly revalidate against its
    contract, pass deterministic identity verification, and be exactly
    JSON-equal to the embedded snapshot. When the world embeds no model,
    no stored declaration may exist. Corrupt stored models keep their
    existing :class:`WorldUncertaintyModelIntegrityError`; missing or
    mismatched state fails closed with the safe typed validation error.
    """
    if embedded is not None:
        try:
            stored = store.get_world_uncertainty_model(tenant_id, scenario_id)
        except WorldUncertaintyModelNotFoundError as exc:
            raise _reject(
                tenant_id, campaign_id, reason="stored uncertainty model missing"
            ) from exc
        revalidate_stored_world_uncertainty_model(stored, tenant_id, scenario_id)
        verify_world_uncertainty_model_identity(
            stored, tenant_id=tenant_id, scenario_id=scenario_id
        )
        if stored.model_dump(mode="json") != embedded.model_dump(mode="json"):
            raise _reject(
                tenant_id, campaign_id, reason="stored and embedded uncertainty model mismatch"
            )
        return stored
    try:
        store.get_world_uncertainty_model(tenant_id, scenario_id)
    except WorldUncertaintyModelNotFoundError:
        return None
    raise _reject(
        tenant_id, campaign_id, reason="stored uncertainty model exists without an embedded model"
    )


def _load_and_verify_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
) -> AdaptivePolicy:
    """Load and verify the exact stored policy for this authority chain.

    The store's read-time revalidation and authority cross-check run
    first (missing raises the typed not-found error, corrupt raises the
    typed integrity error); the service then requires exact agreement
    with the tenant, campaign, scenario, world identity/hash, and the
    exact ``4.0.0`` runtime literal, plus independent identity
    verification of the returned authority. Any disagreement fails
    closed; the policy is never repaired, replaced, or evaluated.
    """
    try:
        policy = store.get_adaptive_policy(tenant_id, campaign_id)
    except AdaptivePolicyNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy authority missing") from exc
    except AdaptivePolicyIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy authority corrupt") from exc
    if (
        policy.runtime_version != RUNTIME_VERSION
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != campaign.scenario_id
        or policy.world_version_id != world.identifier
        or policy.world_content_hash != world.content_hash
    ):
        raise _reject(
            tenant_id,
            campaign_id,
            reason="campaign/policy/scenario/world/runtime identity mismatch",
        )
    try:
        verify_adaptive_policy_identity(
            policy,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=campaign.scenario_id,
            world_version_id=world.identifier,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
        )
    except AdaptivePolicyIntegrityError as exc:
        raise _reject(tenant_id, campaign_id, reason="adaptive policy identity mismatch") from exc
    return policy


def _load_exact_candidates(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
) -> tuple[StrategyCandidate, ...]:
    """Load the exact stored ordered candidate collection.

    The stored collection must resolve uniquely, be non-empty, carry the
    exact campaign tenant on every member, and equal
    ``campaign.strategy_candidate_ids`` in identifiers **and** order -
    reordered, extra, missing, or duplicated candidates fail closed
    exactly as the established runtime-3 preflight requires.
    """
    try:
        stored_candidates = store.get_strategy_candidates(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise _reject(
            tenant_id, campaign_id, reason="strategy candidate authority missing"
        ) from exc
    if not stored_candidates:
        raise _reject(tenant_id, campaign_id, reason="strategy candidate authority missing")
    for candidate in stored_candidates:
        if candidate.tenant_id != tenant_id:
            raise _reject(tenant_id, campaign_id, reason="strategy candidate tenant mismatch")
    if [candidate.identifier for candidate in stored_candidates] != list(
        campaign.strategy_candidate_ids
    ):
        raise _reject(
            tenant_id, campaign_id, reason="stored strategy candidate collection mismatch"
        )
    return stored_candidates


def _load_exact_trajectory_plan_order(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    stored_candidates: tuple[StrategyCandidate, ...],
) -> None:
    """Require the stored plan order to equal the campaign candidate order.

    The stored trajectory-plan collection must exist; its order must
    exactly match the verified stored candidate order (each candidate in
    ``campaign.strategy_candidate_ids`` order, then the canonical
    state-model order inside each strategy). A reordered, incomplete, or
    contradictory plan order is contradictory campaign authority and
    fails closed. The plans are only read and never executed.
    """
    try:
        stored_plans = store.get_strategy_trajectory_plans(tenant_id, campaign_id)
    except TrajectoryPlansNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="trajectory plan authority missing") from exc
    plan_strategy_order: list[str] = []
    for plan in stored_plans:
        if not plan_strategy_order or plan_strategy_order[-1] != plan.strategy_candidate_id:
            plan_strategy_order.append(plan.strategy_candidate_id)
    if plan_strategy_order != [candidate.identifier for candidate in stored_candidates]:
        raise _reject(tenant_id, campaign_id, reason="stored trajectory plan order mismatch")


def _build_matrix_exactly_once(
    *,
    campaign: CampaignSpec,
    world: WorldVersion,
    state_models: tuple[Any, ...],
    model: WorldUncertaintyModel | None,
    tenant_id: str,
    campaign_id: str,
) -> _CampaignWorldRealizationMatrix:
    """Build the campaign realization matrix exactly once; typed failures only."""
    try:
        return build_campaign_world_realization_matrix(
            campaign=campaign,
            world=world,
            state_models=state_models,
            model=model,
        )
    except (WorldRealizationIntegrityError, WorldRealizationSamplingError) as exc:
        raise _reject(tenant_id, campaign_id, reason="world realization derivation failed") from exc


def _verify_stored_runtime3_seed_authority(
    *,
    store: InMemoryScenarioStore,
    tenant_id: str,
    campaign_id: str,
    campaign: CampaignSpec,
    world: WorldVersion,
    matrix: _CampaignWorldRealizationMatrix,
) -> None:
    """Verify the campaign seeds against the stored runtime-3 plan matrix.

    The runtime-3 RunPlan tuple written when the campaign was prepared
    predates this derivation and is therefore an independent authority
    over the exact seed content. The expected runtime-3 plan tuple is
    recomputed with the accepted pure planner
    (:func:`~kalhas.application.run_planner.plan_realization_runs` - the
    existing runtime-3 planning identity semantics, reused and not
    duplicated or altered) over the verified world, the exact stored
    runtime-3 candidates, the campaign's ordered seed ensemble, the
    recorded ``campaign.created_at``, and the per-seed realizations of
    the single matrix this service already built. Exact tuple equality
    with the stored tuple is then required - order, cardinality, runtime
    literal, identity, ``input_hash``, ``created_at``, and
    strategy/seed/world provenance included - so a tampered, missing,
    extra, reordered, duplicated, or mixed-runtime seed disagrees with
    the persisted original matrix and fails closed atomically. The
    stored tuple is only read: it is never reinterpreted, rewritten,
    repaired, or executed, and no second matrix and no additional
    runtime-4 planner call exist.
    """
    try:
        stored_plans = store.get_run_plans(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise _reject(tenant_id, campaign_id, reason="stored run-plan authority missing") from exc
    if not stored_plans:
        raise _reject(tenant_id, campaign_id, reason="stored run-plan authority missing")
    if any(plan.runtime_version != REALIZATION_TRAJECTORY_RUNTIME_VERSION for plan in stored_plans):
        raise _reject(tenant_id, campaign_id, reason="stored run-plan runtime mismatch")
    realizations = {
        realization.scenario_seed_id: realization for realization in matrix.realizations
    }
    stored_candidates = store.get_strategy_candidates(tenant_id, campaign_id)
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
        raise _reject(tenant_id, campaign_id, reason="campaign seed authority mismatch")


def derive_adaptive_campaign_planning_authority(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    runtime_version: str = RUNTIME_VERSION,
) -> tuple[RunPlan, ...]:
    """Derive the exact adaptive RunPlan tuple of one COMPILED campaign.

    The single read-only entry point: the exact ``4.0.0`` runtime gate
    runs first; the complete stored authority chain is
    then loaded and verified; the campaign realization matrix is built
    exactly once; the campaign's seeds are verified against the
    independent stored runtime-3 plan matrix; and the accepted pure planner
    :func:`~kalhas.application.adaptive_run_planner.plan_adaptive_runs`
    is called exactly once with the campaign's ordered seed ensemble,
    the exact stored policy, the per-seed shared realization mapping,
    and the recorded ``campaign.created_at``. ``K`` ordered seeds yield
    exactly ``K`` plans in the campaign's exact seed order. Every
    failure is atomic, typed, and write-free; the function is pure with
    respect to repository and application state. See the module
    docstring for the complete derivation semantics and forbidden
    surfaces.
    """
    try:
        if runtime_version != RUNTIME_VERSION:
            raise UnsupportedRuntimeVersionError(
                runtime_version, operation="adaptive campaign planning authority"
            )
        if (
            type(tenant_id) is not str
            or type(campaign_id) is not str
            or not tenant_id
            or not campaign_id
        ):
            raise _reject(
                tenant_id if type(tenant_id) is str else "",
                campaign_id if type(campaign_id) is str else "",
                reason="tenant_id and campaign_id must be exact non-empty strings",
            )
        try:
            campaign = store.get_campaign(tenant_id, campaign_id)
        except CampaignNotFoundError as exc:
            raise _reject(tenant_id, campaign_id, reason="campaign authority missing") from exc
        if campaign.tenant_id != tenant_id or campaign.identifier != campaign_id:
            raise _reject(tenant_id, campaign_id, reason="campaign authority missing")
        try:
            status = store.get_campaign_status(tenant_id, campaign_id)
        except CampaignNotFoundError as exc:
            raise _reject(
                tenant_id, campaign_id, reason="campaign status authority missing"
            ) from exc
        if status.campaign_id != campaign_id or status.tenant_id != tenant_id:
            raise _reject(tenant_id, campaign_id, reason="campaign status authority mismatch")
        if status.state is not CampaignState.COMPILED:
            raise _reject(tenant_id, campaign_id, reason="campaign must be exactly COMPILED")
        try:
            store.get_scenario(tenant_id, campaign.scenario_id)
        except ScenarioNotFoundError as exc:
            raise _reject(tenant_id, campaign_id, reason="scenario authority missing") from exc
        world = _load_verified_world(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign
        )
        if world.tenant_id != tenant_id or world.source_scenario_id != campaign.scenario_id:
            raise _reject(
                tenant_id, campaign_id, reason="campaign/scenario/world identity mismatch"
            )
        if campaign.world_version_id != world.identifier:
            raise _reject(tenant_id, campaign_id, reason="campaign world reference mismatch")
        stored_candidates = _load_exact_candidates(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign
        )
        _load_exact_trajectory_plan_order(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            stored_candidates=stored_candidates,
        )
        policy = _load_and_verify_policy(
            store, tenant_id=tenant_id, campaign_id=campaign_id, campaign=campaign, world=world
        )
        catalog = extract_world_catalog(world)
        model = _verify_stored_embedded_model_consistency(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_id=campaign.scenario_id,
            embedded=catalog.uncertainty_model,
        )
        matrix = _build_matrix_exactly_once(
            campaign=campaign,
            world=world,
            state_models=catalog.state_models,
            model=model,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
        )
        _verify_stored_runtime3_seed_authority(
            store=store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            campaign=campaign,
            world=world,
            matrix=matrix,
        )
        realizations = {
            realization.scenario_seed_id: realization for realization in matrix.realizations
        }
        return plan_adaptive_runs(
            campaign_id=campaign.identifier,
            tenant_id=tenant_id,
            world_version_id=world.identifier,
            world_content_hash=world.content_hash,
            policy=policy,
            seeds=campaign.seed_ensemble,
            created_at=campaign.created_at,
            realizations=realizations,
            runtime_version=runtime_version,
        )
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        raise _reject(
            tenant_id if type(tenant_id) is str else "",
            campaign_id if type(campaign_id) is str else "",
            reason="planning authority inspection violated its contract",
        ) from exc


__all__ = [
    "RUNTIME_VERSION",
    "derive_adaptive_campaign_planning_authority",
]
