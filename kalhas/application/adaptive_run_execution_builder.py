"""Pure read-only runtime-4 multi-step aggregate builder (H28-S06C2C-C02).

Assembles exactly one immutable :class:`AdaptiveRunTrajectoryExecution`
aggregate for a complete adaptive run from explicitly supplied, already
verified upstream authorities and the real single-step causal orchestrator
(:func:`execute_adaptive_decision_step`). The builder begins from the exact
world-realization initial states, executes the decision steps exactly
``0..final_decision_step`` (one real orchestrator call per step, never a
preview and never a rerun), threads the immutable policy state, the complete
sourced-event ledger, and the per-model state collection across steps, and
collects every piece of nested causal evidence in exact returned order.

The aggregate is built, self-hashed through the frozen two-phase identity
construction, and verified against the same explicit authority verifier the
store uses before it is returned. The builder is strictly read-only: no
store write, no activity event, no run-status transition, no persistence,
no wall clock, no RNG beyond the already-contained observation primitive,
no network, provider, adapter, NEXUS, or LEGION dependency, no import from
tests, and no mutation of any input. Byte-equivalent inputs always produce
exactly equal aggregate bytes.

Every failure is atomic and typed: the orchestrator's and the verifier's
safe typed domain errors propagate unchanged, and only raw structural
failures at this boundary are converted to the safe typed validation
error. Any failure produces no aggregate, no partial step result, and no
effect of any kind.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import NoReturn

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_decision_step_service import (
    RUNTIME_VERSION,
    AdaptiveDecisionStepDraft,
    execute_adaptive_decision_step,
)
from kalhas.application.adaptive_policy_state_machine import (
    initialize_adaptive_policy_state,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.adaptive_trajectory_execution_identity import (
    adaptive_run_input_hash,
    adaptive_run_trajectory_execution_content_hash,
    adaptive_run_trajectory_execution_identifier,
)
from kalhas.application.adaptive_trajectory_execution_integrity import (
    AdaptiveRunExecutionAuthorities,
    verify_adaptive_run_trajectory_execution_authority,
)
from kalhas.application.domain_errors import KalhasDomainError
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.realization_trajectory_runtime import realized_initial_state
from kalhas.application.state_transition_engine import validate_state
from kalhas.application.strategy_trajectory_service import ModelTrajectoryCatalog
from kalhas.application.world_integrity import extract_world_catalog
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.adaptive_trajectory_execution import (
    AdaptiveRunTrajectoryExecution,
)
from kalhas.contracts.v1.campaign import CampaignSpec, CampaignState
from kalhas.contracts.v1.execution import RunStatus
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.run_plan import RunPlan
from kalhas.contracts.v1.runtime_observation import (
    ExternalObservationInputBundle,
    ExternalObservationSource,
    RuntimeObservationDeclaration,
    RuntimeObservationEvent,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.scenario import ScenarioSeed
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import DomainStateModel, _contains_non_finite
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan
from kalhas.contracts.v1.world import WorldVersion
from kalhas.contracts.v1.world_realization import WorldRealization

#: The application-local complete per-model state collection: exactly one
#: complete state mapping per required state-model identifier.
StateCollection = dict[str, dict[str, JsonValue]]

#: The self-covering placeholder content hash of the two-phase construction.
_PLACEHOLDER_HASH = "0" * 64


@dataclass(frozen=True, slots=True)
class AdaptiveRunExecutionBuildDraft:
    """The application-local caller-owned inputs of one complete run build.

    Carries only the strict non-negative integer ``final_decision_step``
    causal horizon of the run (bool, float, string, and negative values
    fail; the covered decision count is exactly ``final_decision_step +
    1``) and the optional already-accepted external input bundle draft
    that must resolve to the exact accepted stored bundle when present.
    No authoritative identity, hash, declaration, policy, seed, plan, or
    state value is accepted here; every authoritative value comes from the
    verified authorities. No wall clock, mutable metadata, or extra
    carrier exists; nothing is sorted, repaired, coerced, or mutated.
    """

    final_decision_step: int
    external_bundle_draft: ExternalObservationInputBundleDraft | None = None


def _reject_validation(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe validation error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionValidationError(tenant_id, run_id, reason)


def _reject_integrity(tenant_id: str, run_id: str, reason: str) -> NoReturn:
    """A generic, safe integrity error with an internal diagnostic reason."""
    raise AdaptiveRunTrajectoryExecutionIntegrityError(tenant_id, run_id, reason)


def _strictly_revalidate_detached(artifact: BaseModel, model_type: type[BaseModel]) -> None:
    """Strictly revalidate one supplied artifact from its detached serialization.

    The artifact's Python payload is re-derived with the established
    Pydantic serializer-warnings suppression and the exact model class is
    re-validated with ``strict=True``, so a validator-bypassed same-type
    instance is rejected before any field of it is trusted. The
    revalidation result is discarded; the artifact is never replaced,
    repaired, or mutated. Any failure raises ``ValueError`` for the caller
    to convert to the safe typed error.
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=r"Pydantic serializer warnings.*", category=UserWarning
            )
            serialized = artifact.model_dump(mode="python")
        model_type.model_validate(serialized, strict=True)
    except (ValidationError, TypeError, AttributeError):
        raise ValueError("artifact failed detached strict revalidation") from None


def _strictly_validate_draft(draft: AdaptiveRunExecutionBuildDraft) -> None:
    """Validate the caller-owned build draft; raises ``ValueError``.

    Enforces the exact draft type and the exact non-negative integer
    ``final_decision_step`` horizon (bool, float, string, and negative
    values fail). The optional external bundle draft is exact-type checked
    here and detached-strictly revalidated by the observation primitive
    when a step consumes it. Nothing is sorted, repaired, or coerced.
    """
    if type(draft) is not AdaptiveRunExecutionBuildDraft:
        raise ValueError("draft must be a valid AdaptiveRunExecutionBuildDraft")
    if type(draft.final_decision_step) is not int or draft.final_decision_step < 0:
        raise ValueError("final_decision_step must be an exact non-negative integer")
    if draft.external_bundle_draft is not None and type(draft.external_bundle_draft) is not (
        ExternalObservationInputBundleDraft
    ):
        raise ValueError("external_bundle_draft must be a valid bundle draft")


def _declared_state_models(
    authorities: AdaptiveRunExecutionAuthorities,
) -> set[str]:
    """The state-model identifiers of every state-field observation declaration."""
    return {
        source.state_model_identifier
        for declaration in authorities.declarations.values()
        if isinstance((source := declaration.observation_source), StateFieldObservationSource)
    }


def _authority_preflight(
    authorities: AdaptiveRunExecutionAuthorities,
    draft: AdaptiveRunExecutionBuildDraft,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
) -> None:
    """Complete fail-closed authority preflight before decision step 0.

    Enforces the exact authority/draft/catalog types, detached strict
    revalidation of every authoritative Pydantic member, runtime-4
    agreement, full tenant/campaign/run-plan/world/seed/realization/policy
    agreement, exact action-plan coverage of the policy's bound actions,
    external-bundle presence agreement with the accepted stored authority
    (both absent, or the draft resolving to the exact stored bundle, and
    an external observation source requiring its bundle), and the complete
    state-model authority of every action binding and every state-derived
    observation declaration. Nothing is duplicated from the owning
    verifiers; nothing is repaired. No partial step result exists before
    this preflight passes.
    """
    tenant_id = authorities.tenant_id
    run_id = authorities.run_id
    if type(authorities) is not AdaptiveRunExecutionAuthorities:
        _reject_validation(tenant_id, run_id, "authorities must be the exact authority type")
    _strictly_validate_draft(draft)
    if not isinstance(catalogs, tuple) or any(
        type(catalog) is not ModelTrajectoryCatalog for catalog in catalogs
    ):
        _reject_validation(tenant_id, run_id, "catalogs must be a tuple of exact catalogs")
    policy = authorities.policy
    if type(policy) is not AdaptivePolicy:
        _reject_validation(tenant_id, run_id, "policy must be an exact AdaptivePolicy")
    try:
        _strictly_revalidate_detached(policy, AdaptivePolicy)
        _strictly_revalidate_detached(authorities.run_plan, RunPlan)
        _strictly_revalidate_detached(authorities.campaign, CampaignSpec)
        _strictly_revalidate_detached(authorities.world, WorldVersion)
        _strictly_revalidate_detached(authorities.seed, ScenarioSeed)
        _strictly_revalidate_detached(authorities.realization, WorldRealization)
        _strictly_revalidate_detached(authorities.run_status, RunStatus)
    except ValueError:
        _reject_validation(tenant_id, run_id, "input failed detached strict revalidation")
    for declaration in authorities.declarations.values():
        if type(declaration) is not RuntimeObservationDeclaration:
            _reject_validation(
                tenant_id, run_id, "declarations must hold exact stored declarations"
            )
        try:
            _strictly_revalidate_detached(declaration, RuntimeObservationDeclaration)
        except ValueError:
            _reject_validation(tenant_id, run_id, "declaration failed detached strict revalidation")
    for plans in authorities.action_plans.values():
        if not isinstance(plans, tuple) or not all(
            type(plan) is StrategyTrajectoryPlan for plan in plans
        ):
            _reject_validation(tenant_id, run_id, "plans must be a tuple of exact plans")
        for plan in plans:
            try:
                _strictly_revalidate_detached(plan, StrategyTrajectoryPlan)
            except ValueError:
                _reject_validation(tenant_id, run_id, "plan failed detached strict revalidation")
    bundle = authorities.external_bundle
    if bundle is not None:
        if type(bundle) is not ExternalObservationInputBundle:
            _reject_validation(tenant_id, run_id, "external bundle must be the exact contract type")
        try:
            _strictly_revalidate_detached(bundle, ExternalObservationInputBundle)
        except ValueError:
            _reject_validation(
                tenant_id, run_id, "external bundle failed detached strict revalidation"
            )

    # Runtime-4 agreement across the policy, run plan, run status, and
    # campaign lifecycle authority.
    if policy.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "policy must be runtime 4")
    if authorities.run_plan.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "run plan must be runtime 4")
    if authorities.run_status.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "run status must be runtime 4")
    if authorities.campaign_status.state is not CampaignState.COMPILED:
        _reject_validation(tenant_id, run_id, "campaign must be exactly COMPILED")

    # Full identity agreement across every authority carrier.
    campaign = authorities.campaign
    world = authorities.world
    seed = authorities.seed
    realization = authorities.realization
    run_plan = authorities.run_plan
    if (
        run_plan.tenant_id != tenant_id
        or run_plan.campaign_id != campaign.identifier
        or run_plan.world_version_id != world.identifier
        or run_plan.scenario_seed_id != seed.identifier
        or campaign.world_version_id != world.identifier
        or campaign.scenario_id != world.source_scenario_id
        or realization.world_version_id != world.identifier
        or realization.world_content_hash != world.content_hash
        or realization.scenario_seed_id != seed.identifier
        or realization.seed_content_hash != seed_content_hash(seed)
        or policy.tenant_id != tenant_id
        or policy.campaign_id != campaign.identifier
        or policy.scenario_id != campaign.scenario_id
        or policy.world_version_id != world.identifier
        or policy.world_content_hash != world.content_hash
    ):
        _reject_integrity(
            tenant_id,
            run_id,
            "authorities disagree on tenant, run, campaign, world, seed, or realization",
        )

    # Exact action-plan coverage: the mapping keys are exactly the
    # policy's bound action identifiers, each mapping a tuple of exact
    # stored plans.
    actions_by_id = {action.action_id: action for action in policy.actions}
    action_plans = authorities.action_plans
    if set(action_plans) != set(actions_by_id):
        _reject_validation(
            tenant_id,
            run_id,
            "action-plan mapping must hold exactly the policy's bound actions",
        )

    # External-bundle presence agreement: both absent, or the draft
    # resolving to the exact accepted stored bundle; a policy bound to an
    # external observation source requires the accepted bundle; no
    # one-sided provenance anywhere.
    if (authorities.external_bundle is None) != (draft.external_bundle_draft is None):
        _reject_validation(
            tenant_id,
            run_id,
            "the external bundle draft and the accepted bundle authority must both be "
            "present or both be absent",
        )
    policy_has_external_source = any(
        isinstance(declaration.observation_source, ExternalObservationSource)
        for declaration in authorities.declarations.values()
    )
    if policy_has_external_source and authorities.external_bundle is None:
        _reject_validation(
            tenant_id,
            run_id,
            "bound external observation source requires the accepted external bundle",
        )

    # The complete state-model authority of every action binding and
    # every state-derived observation declaration.
    models_by_identifier: dict[str, DomainStateModel] = {}
    for embedded_model in extract_world_catalog(world).state_models:
        models_by_identifier.setdefault(embedded_model.identifier, embedded_model)
    required = {
        binding.state_model_identifier
        for action in policy.actions
        for binding in action.trajectory_plan_bindings
    } | _declared_state_models(authorities)
    for identifier in sorted(required):
        resolved_model = models_by_identifier.get(identifier)
        if resolved_model is None:
            _reject_integrity(
                tenant_id,
                run_id,
                "state-model authority is missing from the compiled world",
            )
        expected_hashes = {
            binding.state_model_content_hash
            for action in policy.actions
            for binding in action.trajectory_plan_bindings
            if binding.state_model_identifier == identifier
        } | {
            source.state_model_content_hash
            for declaration in authorities.declarations.values()
            if isinstance((source := declaration.observation_source), StateFieldObservationSource)
            and source.state_model_identifier == identifier
        }
        if expected_hashes != {resolved_model.content_hash}:
            _reject_integrity(
                tenant_id,
                run_id,
                "state-model authority disagrees with the compiled world",
            )


def _required_model_identifiers(
    authorities: AdaptiveRunExecutionAuthorities,
) -> set[str]:
    """The complete required initial-state-model set of the run."""
    return {
        binding.state_model_identifier
        for action in authorities.policy.actions
        for binding in action.trajectory_plan_bindings
    } | _declared_state_models(authorities)


def _complete_initial_states(
    authorities: AdaptiveRunExecutionAuthorities,
) -> StateCollection:
    """Derive the complete realization-derived initial-state collection.

    For every required state-model identifier the embedded compiled-world
    model is resolved exactly once by its deterministic identifier; its
    complete realized initial state is derived with the established
    helper, checked for finiteness, and validated by the engine against
    the exact embedded model. Observation-only models without action
    transitions remain in the complete collection unchanged. Model
    declared defaults are never silently substituted: a required model
    absent from the compiled world, a duplicate embedded model
    identifier, or a realization override targeting a field the resolved
    model does not declare fails closed.
    """
    tenant_id = authorities.tenant_id
    run_id = authorities.run_id
    catalog_models: dict[str, DomainStateModel] = {}
    for embedded_model in extract_world_catalog(authorities.world).state_models:
        if embedded_model.identifier in catalog_models:
            _reject_integrity(
                tenant_id,
                run_id,
                "required state model is duplicated in the compiled world",
            )
        catalog_models[embedded_model.identifier] = embedded_model
    states: StateCollection = {}
    for identifier in sorted(_required_model_identifiers(authorities)):
        resolved_model = catalog_models.get(identifier)
        if resolved_model is None:
            _reject_integrity(
                tenant_id,
                run_id,
                "required state model is missing from the compiled world",
            )
        try:
            initial = realized_initial_state(
                state_model=resolved_model,
                realization=authorities.realization,
                run_id=run_id,
            )
            validate_state(initial, resolved_model)
        except KalhasDomainError:
            raise
        except (TypeError, ValueError, AttributeError) as exc:
            raise AdaptiveRunTrajectoryExecutionIntegrityError(
                tenant_id,
                run_id,
                reason="realized initial state violates its state model",
            ) from exc
        if _contains_non_finite(initial):
            _reject_integrity(
                tenant_id,
                run_id,
                "realized initial state contains non-finite values",
            )
        states[identifier] = initial
    return states


def build_adaptive_run_trajectory_execution(
    store: InMemoryScenarioStore,
    *,
    authorities: AdaptiveRunExecutionAuthorities,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    draft: AdaptiveRunExecutionBuildDraft,
) -> AdaptiveRunTrajectoryExecution:
    """Build and self-hash the deterministic aggregate of one adaptive run.

    Runs the complete authority preflight, derives the complete
    realization-derived initial-state collection, executes the decision
    steps exactly ``0..draft.final_decision_step`` through the real
    single-step orchestrator (exactly one call per step), threads the
    immutable policy state, the complete sourced-event ledger, and the
    per-model state collection across steps, and builds exactly one
    self-hashed aggregate. The aggregate is verified against the exact
    explicit authority verifier the store uses before it is returned.
    """
    tenant_id = authorities.tenant_id
    run_id = authorities.run_id
    try:
        return _build(store=store, authorities=authorities, catalogs=catalogs, draft=draft)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, KalhasDomainError):
            raise
        _reject_validation(tenant_id, run_id, "input violates its contract")


def _build(
    store: InMemoryScenarioStore,
    *,
    authorities: AdaptiveRunExecutionAuthorities,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    draft: AdaptiveRunExecutionBuildDraft,
) -> AdaptiveRunTrajectoryExecution:
    """The exact deterministic build path; raises typed errors only."""
    tenant_id = authorities.tenant_id
    run_id = authorities.run_id
    policy = authorities.policy
    action_plans = authorities.action_plans
    _authority_preflight(authorities, draft, catalogs)

    complete_states = _complete_initial_states(authorities)
    policy_state: AdaptivePolicyStateSnapshot = initialize_adaptive_policy_state(policy)
    prior_observation_events: tuple[RuntimeObservationEvent, ...] = ()
    observation_events: list[RuntimeObservationEvent] = []
    policy_state_snapshots: list[AdaptivePolicyStateSnapshot] = []
    decision_events: list[AdaptivePolicyDecisionEvent] = []
    switch_events: list[AdaptivePolicySwitchEvent] = []
    trajectory_results_by_decision: list[tuple[RealizedStateTrajectoryResult, ...]] = []

    for decision_step in range(0, draft.final_decision_step + 1):
        # The pre-decision snapshot of this step, appended before any
        # causal work of the step runs.
        policy_state_snapshots.append(policy_state)
        # A detached working view of the complete pre-action state
        # collection; the orchestrator and its primitives never mutate it
        # and the builder's threaded collection is never aliased into a
        # step draft.
        working_states: StateCollection = {
            identifier: dict(states) for identifier, states in complete_states.items()
        }
        step_draft = AdaptiveDecisionStepDraft(
            decision_step=decision_step,
            final_decision_step=draft.final_decision_step,
            pre_action_states=working_states,
            prior_observation_events=prior_observation_events,
            external_bundle_draft=draft.external_bundle_draft,
        )
        # Exactly one real orchestrator call per decision step.
        step = execute_adaptive_decision_step(
            store,
            tenant_id=tenant_id,
            run_id=run_id,
            campaign_id=authorities.campaign.identifier,
            scenario_seed_id=authorities.seed.identifier,
            policy=policy,
            policy_state=policy_state,
            action_plans=action_plans,
            catalogs=catalogs,
            draft=step_draft,
        )
        observation_events.extend(step.new_observation_events)
        decision_events.append(step.decision_event)
        if step.switch_event is not None:
            switch_events.append(step.switch_event)
        trajectory_results_by_decision.append(step.trajectory_results)
        for result in step.trajectory_results:
            complete_states[result.state_model_identifier] = {
                key: _copy_value(value) for key, value in result.final_state.items()
            }
        policy_state = step.next_policy_state
        prior_observation_events = (*prior_observation_events, *step.new_observation_events)

    # The aggregate plan-set hash covers every bound action's plans - the
    # flattened, canonically ordered complete action-plan catalog - not
    # only the actions selected during this run, exactly as the integrity
    # verifier recomputes it.
    from kalhas.application.run_trajectory_runtime import trajectory_plan_set_hash

    plans: list[StrategyTrajectoryPlan] = [
        plan for bound_plans in action_plans.values() for plan in bound_plans
    ]
    ordered_plans = tuple(
        sorted(plans, key=lambda plan: (plan.strategy_candidate_id, plan.state_model_identifier))
    )
    plan_set_hash_value = trajectory_plan_set_hash(ordered_plans)
    seed_hash = seed_content_hash(authorities.seed)
    run_plan = authorities.run_plan
    world = authorities.world
    realization = authorities.realization
    campaign = authorities.campaign
    bundle = authorities.external_bundle
    bundle_id = bundle.identifier if bundle is not None else None
    bundle_hash = bundle.content_hash if bundle is not None else None
    input_hash_value = adaptive_run_input_hash(
        run_plan_id=run_plan.identifier,
        run_plan_input_hash=run_plan.input_hash,
        campaign_id=campaign.identifier,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=authorities.seed.identifier,
        seed_content_hash_value=seed_hash,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        adaptive_policy_identifier=policy.identifier,
        adaptive_policy_content_hash=policy.content_hash,
        trajectory_plan_set_hash=plan_set_hash_value,
        external_observation_input_bundle_id=bundle_id,
        external_observation_input_bundle_content_hash=bundle_hash,
        final_decision_step=draft.final_decision_step,
    )
    aggregate = AdaptiveRunTrajectoryExecution(
        identifier="",
        tenant_id=tenant_id,
        run_id=run_id,
        campaign_id=campaign.identifier,
        run_plan_id=run_plan.identifier,
        scenario_id=campaign.scenario_id,
        world_version_id=world.identifier,
        world_content_hash=world.content_hash,
        scenario_seed_id=authorities.seed.identifier,
        seed_content_hash=seed_hash,
        world_realization_id=realization.identifier,
        world_realization_content_hash=realization.content_hash,
        runtime_version=RUNTIME_VERSION,
        adaptive_policy_identifier=policy.identifier,
        policy_id=policy.policy_id,
        adaptive_policy_content_hash=policy.content_hash,
        external_observation_input_bundle_id=bundle_id,
        external_observation_input_bundle_content_hash=bundle_hash,
        input_hash=input_hash_value,
        trajectory_plan_set_hash=plan_set_hash_value,
        observation_events=tuple(observation_events),
        policy_state_snapshots=tuple(policy_state_snapshots),
        decision_events=tuple(decision_events),
        switch_events=tuple(switch_events),
        trajectory_results_by_decision=tuple(trajectory_results_by_decision),
        content_hash=_PLACEHOLDER_HASH,
        executed_at=run_plan.created_at,
    )
    identified = aggregate.model_copy(
        update={
            "identifier": adaptive_run_trajectory_execution_identifier(
                run_id=run_id, runtime_version=RUNTIME_VERSION
            )
        }
    )
    finalized = identified.model_copy(
        update={"content_hash": adaptive_run_trajectory_execution_content_hash(identified)}
    )
    # The completed aggregate must pass the exact verifier the store
    # uses, against the exact explicit authorities, before it is
    # returned; a failure propagates as the safe typed integrity error.
    verify_adaptive_run_trajectory_execution_authority(finalized, authorities=authorities)
    return finalized


def _copy_value(value: JsonValue) -> JsonValue:
    """A detached copy of one JSON-compatible state value."""
    if isinstance(value, dict):
        return {key: _copy_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_value(item) for item in value)
    return value


__all__ = [
    "RUNTIME_VERSION",
    "AdaptiveRunExecutionBuildDraft",
    "build_adaptive_run_trajectory_execution",
]
