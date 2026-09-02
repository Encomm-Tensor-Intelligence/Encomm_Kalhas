"""Runtime-4 deterministic per-run execution service (H28-S06C2C-C03A).

Owns the complete lifecycle of exactly one planned runtime-4 (``4.0.0``)
adaptive run and the single :class:`AdaptiveRunTrajectoryExecution`
persistence write of that run. The service accepts only the store, the
deterministic ``tenant_id``/``run_id`` identifiers, and the caller-owned
:class:`AdaptiveRunExecutionBuildDraft` - no authorities, catalogs,
policy, plans, declarations, states, realization, timestamps, hashes,
status, callbacks, or metadata may be supplied by the caller. Every
authoritative value is loaded from the store, verified, and passed to
the pure deterministic builder (:func:`build_adaptive_run_trajectory_execution`)
which is called exactly once.

The fixed per-run sequence is:

1. strictly validate ``tenant_id``, ``run_id``, and the exact draft type;
2. load the recorded :class:`RunStatus` and require the exact ``4.0.0``
   runtime literal, the exact deterministic status identifier, exact
   tenant/run ownership, state exactly PLANNED, and ``event_hash`` None;
3. resolve the exact stored :class:`RunPlan` through the recorded
   campaign plan set and verify the run identifier, run-plan identity,
   planning input hash, and tenant/campaign/world/seed/runtime agreement
   through the complete loadable authority chain;
4. require that no :class:`AdaptiveRunTrajectoryExecution` already
   exists for the run (a duplicate is never overwritten);
5. load and independently verify the complete stored authority chain:
   campaign, campaign status exactly COMPILED, the compiled world and
   manifest, the derived canonical closed model-trajectory catalogs, the
   scenario seed from the campaign ensemble, the stored adaptive policy,
   every bound runtime observation declaration, every exact action-bound
   stored strategy trajectory plan, the stored/embedded uncertainty
   model agreement, the deterministically rebuilt world realization, and
   the accepted external observation input bundle when a bound external
   declaration requires it;
6. derive the detached local RUNNING :class:`RunStatus` from recorded
   authority only (same deterministic identity, ``created_at`` and
   ``changed_at`` both equal to ``run_plan.created_at``, ``event_hash``
   None - never a wall clock);
7. build and verify the complete immutable aggregate through the pure
   builder exactly once, finishing every validation before the first
   repository write;
8. perform the writes in the fixed order: RUNNING status, the exact
   built aggregate, then the COMPLETE status;
9. return the exact completed status and the exact built aggregate.

The final COMPLETE status keeps the deterministic identity and authority
fields, state COMPLETE, and ``event_hash`` None - the frozen run-status
``event_hash`` is never reinterpreted as the adaptive aggregate content
hash; :class:`AdaptiveRunTrajectoryExecution` is the runtime-4
authority.

Every failure before the write sequence leaves the run exactly PLANNED
with zero adaptive execution, zero run events, zero activity, the
campaign status unchanged, and every authority and caller input
byte-identical. Missing, foreign, corrupt, or old-domain getter failures
are converted into the established safe adaptive validation/integrity
errors; public messages never leak tenant IDs, run IDs, hashes,
thresholds, state values, or external values. The service never writes
run events, input-integrity manifests, operational activity, or
campaign statuses; never mutates policies, plans, declarations, worlds,
seeds, or realizations; never calls NEXUS or LEGION; and never uses a
clock, randomness, UUID, network, filesystem, provider, retry, repair,
update, or delete surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from kalhas.application.adaptive_policy_binding_errors import (
    AdaptivePolicyIntegrityError,
    AdaptivePolicyNotFoundError,
)
from kalhas.application.adaptive_run_execution_builder import (
    RUNTIME_VERSION,
    AdaptiveRunExecutionBuildDraft,
    build_adaptive_run_trajectory_execution,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionAlreadyExistsError,
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionNotFoundError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    AdaptiveRunExecutionAuthorities,
)
from kalhas.application.domain_errors import (
    CampaignNotFoundError,
    KalhasDomainError,
    RunNotFoundError,
    TrajectoryPlansNotFoundError,
    WorldNotFoundError,
    WorldSnapshotIntegrityError,
)
from kalhas.application.external_observation_input_errors import (
    ExternalObservationInputIntegrityError,
    ExternalObservationInputNotFoundError,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.run_planner import run_identifier
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.strategy_trajectory_service import ModelTrajectoryCatalog
from kalhas.application.world_integrity import (
    extract_world_catalog,
    verify_world_snapshot,
)
from kalhas.application.world_realization_builder import build_world_realization
from kalhas.application.world_uncertainty_errors import (
    WorldRealizationIntegrityError,
    WorldRealizationSamplingError,
    WorldUncertaintyModelIntegrityError,
    WorldUncertaintyModelNotFoundError,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import AdaptiveRunTrajectoryExecution
from kalhas.contracts.v1.campaign import CampaignState
from kalhas.contracts.v1.execution import RunState, RunStatus
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationSource,
    RuntimeObservationDeclaration,
)
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldUncertaintyModel


@dataclass(frozen=True, slots=True)
class AdaptiveRunExecutionResult:
    """The frozen, slotted completed outcome of exactly one executed run.

    ``status`` is the exact COMPLETE :class:`RunStatus` written last and
    ``execution`` the exact built aggregate that was persisted exactly
    once.
    """

    status: RunStatus
    execution: AdaptiveRunTrajectoryExecution


def _reject_validation(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A safe validation error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionValidationError(tenant_id, run_id, reason)


def _reject_integrity(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A safe integrity error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionIntegrityError(tenant_id, run_id, reason)


def _load_run_authority(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
) -> tuple[RunStatus, RunPlan]:
    """Load and verify the recorded run status and its exact run plan.

    The recorded :class:`RunStatus` must belong to the tenant/run, carry
    the exact deterministic status identifier and the exact ``4.0.0``
    runtime literal, and be exactly PLANNED with no event hash. The
    referenced :class:`RunPlan` must exist in the recorded campaign plan
    set, match the status runtime and planning input hash, resolve to
    the deterministic run identifier, and carry the exact recorded
    tenant/campaign ownership. Unknown or foreign runs raise the typed
    validation error; any recorded-state mismatch raises the typed
    integrity error. Nothing is written, repaired, or executed.
    """
    try:
        status = store.get_run_status(tenant_id, run_id)
    except RunNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="recorded run authority missing"
        ) from exc
    if (
        status.tenant_id != tenant_id
        or status.identifier != f"status-{run_id}"
        or status.runtime_version != RUNTIME_VERSION
    ):
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="recorded run authority missing"
        )
    if status.state is not RunState.PLANNED or status.event_hash is not None:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run state mismatch"
        )
    if status.run_id != run_id:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run authority mismatch"
        )
    try:
        plans = store.get_run_plans(tenant_id, status.campaign_id)
    except CampaignNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="recorded run authority missing"
        ) from exc
    run_plan = next(
        (plan for plan in plans if plan.identifier == status.run_plan_id),
        None,
    )
    if (
        run_plan is None
        or run_plan.identifier != status.run_plan_id
        or run_plan.runtime_version != status.runtime_version
        or run_identifier(run_plan) != run_id
    ):
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run authority mismatch"
        )
    if run_plan.input_hash != status.input_hash:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run authority mismatch"
        )
    if run_plan.tenant_id != tenant_id or run_plan.campaign_id != status.campaign_id:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run authority mismatch"
        )
    return status, run_plan


def _derived_catalogs(world: WorldVersion) -> tuple[ModelTrajectoryCatalog, ...]:
    """The closed canonical model-trajectory catalogs of the compiled world.

    Derived exclusively from the verified compiled world in the
    orchestrator's canonical ascending state-model-identifier order:
    exactly one :class:`ModelTrajectoryCatalog` per embedded state model
    with its exact embedded transitions. Nothing is duplicated from the
    worlds, merged, or repaired.
    """
    entries = extract_world_catalog(world)
    return tuple(
        sorted(
            (
                ModelTrajectoryCatalog(
                    state_model=model,
                    transitions=tuple(
                        transition
                        for transition in entries.transitions
                        if transition.state_model_id == model.state_model_id
                    ),
                )
                for model in entries.state_models
            ),
            key=lambda catalog: catalog.state_model.identifier,
        )
    )


def _load_authorities(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
    run_plan: RunPlan,
    run_status: RunStatus,
) -> AdaptiveRunExecutionAuthorities:
    """Load and independently verify the complete stored authority chain.

    Mirrors the store's own runtime-4 authority loader driven by the
    recorded run plan and the detached local RUNNING status: the
    campaign and its exactly-COMPILED lifecycle status, the compiled
    world and manifest, the scenario seed from the campaign ensemble,
    the stored adaptive policy, every policy-bound observation
    declaration, the exact action-bound stored strategy trajectory
    plans, the accepted external bundle when a bound external
    declaration requires it, the stored/embedded uncertainty-model
    agreement, and the deterministically rebuilt world realization.
    Missing authorities raise the typed validation error; corrupt or
    disagreeing authorities raise the typed integrity error. Nothing is
    written, repaired, or executed.
    """
    campaign_id = run_plan.campaign_id
    try:
        campaign = store.get_campaign(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign authority missing"
        ) from exc
    if campaign.tenant_id != tenant_id or campaign.identifier != campaign_id:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign authority missing"
        )
    try:
        campaign_status = store.get_campaign_status(tenant_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign status authority missing"
        ) from exc
    if campaign_status.state is not CampaignState.COMPILED:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign must be exactly COMPILED"
        )
    try:
        world = store.get_world(tenant_id, campaign.world_version_id)
        manifest = store.get_manifest(tenant_id, campaign.world_version_id)
    except WorldNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="world authority missing"
        ) from exc
    try:
        verify_world_snapshot(world, manifest)
    except WorldSnapshotIntegrityError as exc:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="world authority corrupt"
        ) from exc
    if world.tenant_id != tenant_id or world.source_scenario_id != campaign.scenario_id:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign/scenario/world identity mismatch"
        )
    if run_plan.world_version_id != world.identifier:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="recorded run authority mismatch"
        )
    seed = next(
        (
            candidate
            for candidate in campaign.seed_ensemble
            if candidate.identifier == run_plan.scenario_seed_id
        ),
        None,
    )
    if seed is None:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="scenario seed authority missing"
        )
    if seed.tenant_id != tenant_id:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="scenario seed tenant mismatch"
        )
    try:
        policy = store.get_adaptive_policy(tenant_id, campaign_id)
    except AdaptivePolicyNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="adaptive policy authority missing"
        ) from exc
    except AdaptivePolicyIntegrityError as exc:
        # The store's read-time policy verification collapses every
        # disagreeing bound authority into AdaptivePolicyIntegrityError but
        # preserves the discriminating cause: a NotFound-family cause is a
        # genuinely missing bound authority (validation), every other cause
        # (or a direct raise) is a corrupt or disagreeing stored authority
        # (integrity).
        if isinstance(
            exc.__cause__,
            (
                CampaignNotFoundError,
                WorldNotFoundError,
                TrajectoryPlansNotFoundError,
                RuntimeObservationDeclarationNotFoundError,
            ),
        ):
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="adaptive policy bound authority missing"
            ) from exc
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="adaptive policy authority corrupt"
        ) from exc
    if (
        policy.runtime_version != RUNTIME_VERSION
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign_id
        or policy.scenario_id != campaign.scenario_id
        or policy.world_version_id != world.identifier
        or policy.world_content_hash != world.content_hash
    ):
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="campaign/policy/scenario/world identity mismatch"
        )
    catalog = extract_world_catalog(world)
    declarations: dict[str, RuntimeObservationDeclaration] = {}
    for binding in policy.observation_bindings:
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, campaign.scenario_id, world.identifier, binding.observation_id
            )
        except RuntimeObservationDeclarationNotFoundError as exc:
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="observation declaration authority missing"
            ) from exc
        except RuntimeObservationDeclarationIntegrityError as exc:
            raise AdaptiveRunTrajectoryExecutionIntegrityError(
                tenant_id, run_id, reason="observation declaration authority corrupt"
            ) from exc
        if (
            declaration.runtime_version != RUNTIME_VERSION
            or declaration.tenant_id != tenant_id
            or declaration.scenario_id != campaign.scenario_id
            or declaration.world_version_id != world.identifier
            or declaration.world_content_hash != world.content_hash
            or binding.runtime_observation_declaration_id != declaration.identifier
            or binding.runtime_observation_declaration_content_hash != declaration.content_hash
            or binding.observed_value_kind != declaration.observed_value_kind
            or binding.unit != declaration.unit
            or binding.missing_behavior != declaration.missing_behavior
        ):
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="policy binding disagrees with stored authority"
            )
        declarations[binding.observation_id] = declaration
    try:
        stored_plans = store.get_strategy_trajectory_plans(tenant_id, campaign_id)
    except TrajectoryPlansNotFoundError as exc:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id, run_id, reason="trajectory plan authority missing"
        ) from exc
    plans_by_id = {plan.identifier: plan for plan in stored_plans}
    action_plans: dict[str, tuple[StrategyTrajectoryPlan, ...]] = {}
    for action in policy.actions:
        bound_plans: list[StrategyTrajectoryPlan] = []
        for plan_binding in action.trajectory_plan_bindings:
            plan = plans_by_id.get(plan_binding.trajectory_plan_id)
            if plan is None:
                raise AdaptiveRunTrajectoryExecutionValidationError(
                    tenant_id, run_id, reason="action plan authority missing"
                )
            if (
                plan.content_hash != plan_binding.trajectory_plan_content_hash
                or plan.state_model_identifier != plan_binding.state_model_identifier
                or plan.state_model_id != plan_binding.state_model_id
                or plan.state_model_content_hash != plan_binding.state_model_content_hash
            ):
                raise AdaptiveRunTrajectoryExecutionIntegrityError(
                    tenant_id, run_id, reason="action plan authority mismatch"
                )
            bound_plans.append(plan)
        action_plans[action.action_id] = tuple(bound_plans)
    requires_bundle = any(
        isinstance(declaration.observation_source, ExternalObservationSource)
        for declaration in declarations.values()
    )
    bundle = None
    if requires_bundle:
        try:
            bundle = store.get_external_observation_input_bundle(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                scenario_seed_id=seed.identifier,
            )
        except ExternalObservationInputNotFoundError as exc:
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="external bundle authority missing"
            ) from exc
        except ExternalObservationInputIntegrityError as exc:
            raise AdaptiveRunTrajectoryExecutionIntegrityError(
                tenant_id, run_id, reason="external bundle authority corrupt"
            ) from exc
    embedded_model = catalog.uncertainty_model
    model: WorldUncertaintyModel | None = None
    if embedded_model is not None:
        try:
            model = store.get_world_uncertainty_model(tenant_id, campaign.scenario_id)
        except WorldUncertaintyModelNotFoundError as exc:
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="stored uncertainty model missing"
            ) from exc
        except WorldUncertaintyModelIntegrityError as exc:
            raise AdaptiveRunTrajectoryExecutionIntegrityError(
                tenant_id, run_id, reason="stored uncertainty model corrupt"
            ) from exc
        if (
            model.tenant_id != tenant_id
            or model.scenario_id != campaign.scenario_id
            or model.model_dump(mode="json") != embedded_model.model_dump(mode="json")
        ):
            raise AdaptiveRunTrajectoryExecutionIntegrityError(
                tenant_id, run_id, reason="stored and embedded uncertainty model mismatch"
            )
    try:
        realization = build_world_realization(
            world=world,
            state_models=catalog.state_models,
            model=model,
            seed=seed,
            realized_at=campaign.created_at,
        )
    except WorldRealizationIntegrityError as exc:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="world realization derivation failed"
        ) from exc
    except WorldRealizationSamplingError as exc:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            tenant_id, run_id, reason="world realization derivation failed"
        ) from exc
    return AdaptiveRunExecutionAuthorities(
        tenant_id=tenant_id,
        run_id=run_id,
        campaign=campaign,
        campaign_status=campaign_status,
        run_status=run_status,
        run_plan=run_plan,
        world=world,
        seed=seed,
        realization=realization,
        uncertainty_model=model,
        policy=policy,
        declarations=declarations,
        action_plans=action_plans,
        external_bundle=bundle,
    )


def execute_adaptive_run(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
    draft: AdaptiveRunExecutionBuildDraft,
) -> AdaptiveRunExecutionResult:
    """Execute exactly one planned runtime-4 adaptive run.

    Accepts only the store, the deterministic tenant/run identifiers,
    and the caller-owned build draft. Every authority is loaded from the
    store and verified; the pure builder is called exactly once; the
    writes happen in the fixed RUNNING -> aggregate -> COMPLETE order;
    and the exact completed status and built aggregate are returned.
    Every failure before the write sequence is atomic. See the module
    docstring for the precise lifecycle and the forbidden effects.
    """
    try:
        if type(tenant_id) is not str or type(run_id) is not str or not tenant_id or not run_id:
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id if isinstance(tenant_id, str) else "",
                run_id if isinstance(run_id, str) else "",
                reason="tenant_id and run_id must be exact non-empty strings",
            )
        if type(draft) is not AdaptiveRunExecutionBuildDraft:
            raise AdaptiveRunTrajectoryExecutionValidationError(
                tenant_id, run_id, reason="draft must be a valid AdaptiveRunExecutionBuildDraft"
            )
        status, run_plan = _load_run_authority(store, tenant_id=tenant_id, run_id=run_id)
        # Exactly one runtime-4 adaptive execution may exist per run; a
        # pre-existing execution - even an identical artifact - is never
        # overwritten, repaired, or re-derived.
        try:
            store.get_adaptive_run_trajectory_execution(tenant_id=tenant_id, run_id=run_id)
        except AdaptiveRunTrajectoryExecutionNotFoundError:
            pass
        else:
            raise AdaptiveRunTrajectoryExecutionAlreadyExistsError(tenant_id, run_id)
        running = RunStatus(
            identifier=status.identifier,
            tenant_id=tenant_id,
            run_id=run_id,
            campaign_id=run_plan.campaign_id,
            run_plan_id=run_plan.identifier,
            state=RunState.RUNNING,
            runtime_version=RUNTIME_VERSION,
            input_hash=run_plan.input_hash,
            event_hash=None,
            created_at=run_plan.created_at,
            changed_at=run_plan.created_at,
        )
        authorities = _load_authorities(
            store,
            tenant_id=tenant_id,
            run_id=run_id,
            run_plan=run_plan,
            run_status=running,
        )
        catalogs = _derived_catalogs(authorities.world)
        # The complete aggregate and every validation finish before the
        # first repository write; the builder and its final verifier
        # raise only the safe typed errors.
        aggregate = build_adaptive_run_trajectory_execution(
            store,
            authorities=authorities,
            catalogs=catalogs,
            draft=draft,
        )
        store.put_run_status(tenant_id, run_id, running)
        store.put_adaptive_run_trajectory_execution(
            tenant_id=tenant_id, run_id=run_id, execution=aggregate
        )
        complete = RunStatus(
            identifier=status.identifier,
            tenant_id=tenant_id,
            run_id=run_id,
            campaign_id=run_plan.campaign_id,
            run_plan_id=run_plan.identifier,
            state=RunState.COMPLETE,
            runtime_version=RUNTIME_VERSION,
            input_hash=run_plan.input_hash,
            event_hash=None,
            created_at=run_plan.created_at,
            changed_at=run_plan.created_at,
        )
        store.put_run_status(tenant_id, run_id, complete)
        return AdaptiveRunExecutionResult(status=complete, execution=aggregate)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id if isinstance(tenant_id, str) else "",
            run_id if isinstance(run_id, str) else "",
            reason="input violates its contract",
        ) from exc


__all__ = [
    "AdaptiveRunExecutionResult",
    "execute_adaptive_run",
]
