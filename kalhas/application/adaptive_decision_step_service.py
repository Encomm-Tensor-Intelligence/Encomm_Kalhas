"""Pure read-only runtime-4 causal decision-step orchestrator (H28-S06C2B).

Connects the three already-complete runtime-4 primitives in the exact frozen
ADR-004 D28-02 within-step causal order for exactly one decision step:

1. complete fail-closed preflight of the draft, policy, policy state,
   complete action-plan catalog, and catalogs;
2. verification that the supplied policy exactly equals the stored
   adaptive-policy authority for the tenant/campaign;
3. derivation of the observation-visible state subset from the complete
   pre-action collection using the policy-bound stored
   ``RuntimeObservationDeclaration`` authorities;
4. rejection of missing, extra, foreign, mismatched, or divergent state
   authority before any behavior runs;
5. construction of the real application-local
   :class:`ObservationStepDraft` and exactly one real call to the pure
   :func:`derive_observation_step` primitive;
6. exactly one real call to :func:`advance_adaptive_policy_state` with the
   supplied verified policy, the supplied pre-decision snapshot, the exact
   scenario-seed identity and content hash, and exactly the derived
   ``ObservationStepResult.available_events``;
7. exactly one real call to :func:`apply_selected_adaptive_action` with the
   returned decision event, the selected action's exact plan tuple resolved
   internally from the verified complete action-plan catalog, and the same
   pre-action state values from which the observations were derived;
8. the frozen application-local :class:`AdaptiveDecisionStepResult` carrying
   the complete ordered causal evidence of the one step.

The orchestrator is a pure sequencing kernel: it independently reimplements
no observation cadence, delay, or noise logic, no condition evaluation, no
dwell/cooldown/budget eligibility, no trajectory-plan evaluation, and no
result hashing - each remains owned by its completed primitive. It reads
verified store authorities and never writes: no ``put_*`` call, no activity
event, no run-status transition, no aggregate construction, no wall clock,
no RNG beyond the already-contained observation primitive, no network,
provider, adapter, NEXUS, or LEGION dependency, no callback, expression, or
arbitrary executable policy content, and no import from tests.

Every failure is atomic and typed: existing observation, policy-state-machine,
and adaptive-execution domain errors propagate unchanged, only raw structural
failures at this boundary are converted to the safe typed adaptive-execution
validation error, public messages never leak tenant, run, campaign, seed,
policy, state, hash, observation, guard, or transition values, and any
failure produces no result, no store write, no activity event, and no
mutation of any input. Byte-equivalent inputs always produce exactly equal
results.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NoReturn

from pydantic import BaseModel, ValidationError

from kalhas.application.adaptive_action_trajectory_runtime import (
    apply_selected_adaptive_action,
)
from kalhas.application.adaptive_policy_state_machine import (
    advance_adaptive_policy_state,
)
from kalhas.application.adaptive_trajectory_execution_errors import (
    AdaptiveRunTrajectoryExecutionIntegrityError,
    AdaptiveRunTrajectoryExecutionValidationError,
)
from kalhas.application.domain_errors import CampaignNotFoundError
from kalhas.application.external_observation_input_service import (
    ExternalObservationInputBundleDraft,
)
from kalhas.application.in_memory_store import InMemoryScenarioStore
from kalhas.application.runtime_observation_declaration_errors import (
    RuntimeObservationDeclarationIntegrityError,
    RuntimeObservationDeclarationNotFoundError,
)
from kalhas.application.runtime_observation_event_errors import (
    RuntimeObservationEventIntegrityError,
    RuntimeObservationEventValidationError,
)
from kalhas.application.runtime_observation_event_service import (
    ObservationStepDraft,
    derive_observation_step,
)
from kalhas.application.strategy_trajectory_service import (
    ModelTrajectoryCatalog,
    trajectory_plan_content_hash,
)
from kalhas.application.world_uncertainty_identity import seed_content_hash
from kalhas.contracts.v1.adaptive_policy import AdaptivePolicy, BoundAdaptiveAction
from kalhas.contracts.v1.adaptive_policy_state import (
    AdaptivePolicyDecisionEvent,
    AdaptivePolicyStateSnapshot,
    AdaptivePolicySwitchEvent,
)
from kalhas.contracts.v1.realization_trajectory_execution import (
    RealizedStateTrajectoryResult,
)
from kalhas.contracts.v1.runtime_observation import (
    RuntimeObservationEvent,
    StateFieldObservationSource,
)
from kalhas.contracts.v1.shared import JsonValue
from kalhas.contracts.v1.state_model import _contains_non_finite
from kalhas.contracts.v1.trajectory import StrategyTrajectoryPlan

#: The exact runtime literal this orchestrator binds.
RUNTIME_VERSION: Literal["4.0.0"] = "4.0.0"

#: The complete caller-owned pre-action state collection: exactly one
#: complete state mapping per state-model identifier that the bound
#: observation declarations and the policy's bound actions need.
StateCollection = Mapping[str, Mapping[str, JsonValue]]

#: The complete caller-owned action-plan catalog: exactly one canonically
#: ordered plan tuple per policy-bound action identifier. The keys must be
#: exactly the policy's bound action identifiers; no decision-dependent
#: subset is accepted, so the orchestrator can resolve the selected
#: action's tuple internally after the policy has advanced.
ActionPlanCatalog = Mapping[str, tuple[StrategyTrajectoryPlan, ...]]


@dataclass(frozen=True, slots=True)
class AdaptiveDecisionStepDraft:
    """The application-local caller-owned inputs of exactly one decision step.

    Carries only caller-owned step inputs: the strict non-negative integer
    ``decision_step`` (bool, float, and string values fail), the strict
    non-negative integer ``final_decision_step`` horizon of the run that
    classifies terminality (``decision_step`` must never exceed it), the
    complete visible ``pre_action_states`` collection, the complete prior
    sourced-event ledger ``prior_observation_events`` in exact canonical
    causal order, and the optional already-accepted external input bundle
    draft. No authoritative identity, hash, declaration, policy, seed, or
    plan value is accepted here; every authoritative value is loaded from
    the store and independently verified. Nothing is sorted, repaired,
    coerced, or mutated.
    """

    decision_step: int
    final_decision_step: int
    pre_action_states: StateCollection
    prior_observation_events: tuple[RuntimeObservationEvent, ...] = ()
    external_bundle_draft: ExternalObservationInputBundleDraft | None = None


@dataclass(frozen=True, slots=True)
class AdaptiveDecisionStepResult:
    """The frozen outcome of exactly one causal adaptive decision step.

    ``new_observation_events`` holds the newly sourced events of this
    source step in canonical declaration-identity order;
    ``available_observation_events`` is the exact tuple the policy
    evaluation consumed; ``pre_decision_policy_state`` is the supplied
    pre-decision snapshot; ``decision_event`` and the optional
    ``switch_event`` are the state machine's evidence (``switch_event``
    is exactly ``None`` when the action did not change);
    ``next_policy_state`` is the following pre-decision snapshot; and
    ``trajectory_results`` holds the applied selected action's realized
    per-state-model results in canonical binding order. It is
    application-local evidence only - never an aggregate, persistence
    receipt, run status, activity event, recommendation, explanation, or
    API surface.
    """

    new_observation_events: tuple[RuntimeObservationEvent, ...]
    available_observation_events: tuple[RuntimeObservationEvent, ...]
    pre_decision_policy_state: AdaptivePolicyStateSnapshot
    decision_event: AdaptivePolicyDecisionEvent
    switch_event: AdaptivePolicySwitchEvent | None
    next_policy_state: AdaptivePolicyStateSnapshot
    trajectory_results: tuple[RealizedStateTrajectoryResult, ...]


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


def _strictly_validate_draft(draft: AdaptiveDecisionStepDraft) -> None:
    """Validate every caller-owned step input; raises ``ValueError``.

    Enforces the exact draft type, the exact non-negative integer
    ``decision_step`` and ``final_decision_step`` horizon (bool, float,
    string, and negative values fail), the horizon ordering, the genuine
    mapping shape of the complete collection and of every state, the exact
    tuple of exactly-typed and strictly revalidated prior events, and the
    exact optional bundle-draft type. Nothing is sorted, repaired, or
    coerced.
    """
    if type(draft) is not AdaptiveDecisionStepDraft:
        raise ValueError("draft must be a valid AdaptiveDecisionStepDraft")
    if type(draft.decision_step) is not int or draft.decision_step < 0:
        raise ValueError("decision_step must be an exact non-negative integer")
    if type(draft.final_decision_step) is not int or draft.final_decision_step < 0:
        raise ValueError("final_decision_step must be an exact non-negative integer")
    if draft.decision_step > draft.final_decision_step:
        raise ValueError("decision_step must not exceed final_decision_step")
    if not isinstance(draft.pre_action_states, Mapping):
        raise ValueError("pre_action_states must be a mapping of state-model identifiers")
    for key, value in draft.pre_action_states.items():
        if not isinstance(key, str) or not key:
            raise ValueError("state keys must be non-empty state-model identifiers")
        if not isinstance(value, Mapping):
            raise ValueError("every pre-action state must be a mapping of field values")
    if not isinstance(draft.prior_observation_events, tuple):
        raise ValueError("prior_observation_events must be a tuple of observation events")
    for event in draft.prior_observation_events:
        if type(event) is not RuntimeObservationEvent:
            raise ValueError("prior events must be exact runtime observation events")
        _strictly_revalidate_detached(event, RuntimeObservationEvent)
    if draft.external_bundle_draft is not None and type(draft.external_bundle_draft) is not (
        ExternalObservationInputBundleDraft
    ):
        raise ValueError("external_bundle_draft must be a valid bundle draft")


def _resolve_stored_policy(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
    campaign_id: str,
    policy: AdaptivePolicy,
) -> None:
    """Require the supplied policy to equal the stored adaptive authority.

    The stored policy for the tenant/campaign locality is fetched (the
    store getter strictly revalidates and cross-checks it) and the
    supplied policy must equal it exactly, field for field: a forged,
    stale, foreign, or disagreeing policy fails closed before any
    behavior-producing primitive runs.
    """
    stored = store.get_adaptive_policy(tenant_id, campaign_id)
    if policy != stored:
        _reject_integrity(tenant_id, run_id, "policy does not equal the stored authority")


def _observation_visible_models(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
    policy: AdaptivePolicy,
    pre_action_states: StateCollection,
) -> frozenset[str]:
    """Resolve the observation-visible state models of the bound declarations.

    Loads the exact stored declaration behind every policy observation
    binding (typed observation errors propagate safely) and collects the
    canonical state-model identifiers of the state-field sources. A
    declaration whose state model is absent from the complete collection
    fails closed; every complete state must be a finite JSON-compatible
    mapping. External-only policies yield an empty observation-visible set.
    """
    visible: set[str] = set()
    for binding in policy.observation_bindings:
        try:
            declaration = store.get_runtime_observation_declaration(
                tenant_id, policy.scenario_id, policy.world_version_id, binding.observation_id
            )
        except RuntimeObservationDeclarationNotFoundError as exc:
            raise RuntimeObservationEventValidationError(
                tenant_id, policy.campaign_id, reason="observation declaration authority missing"
            ) from exc
        except RuntimeObservationDeclarationIntegrityError as exc:
            raise RuntimeObservationEventIntegrityError(
                tenant_id, policy.campaign_id, reason="observation declaration authority corrupt"
            ) from exc
        source = declaration.observation_source
        if isinstance(source, StateFieldObservationSource):
            if source.state_model_identifier not in pre_action_states:
                raise RuntimeObservationEventValidationError(
                    tenant_id,
                    policy.campaign_id,
                    reason="declared observation state model is absent from the complete state",
                )
            visible.add(source.state_model_identifier)
    for state in pre_action_states.values():
        if not isinstance(state, Mapping) or _contains_non_finite(dict(state)):
            raise RuntimeObservationEventValidationError(
                tenant_id,
                policy.campaign_id,
                reason="pre-action state must contain only finite JSON values",
            )
    return frozenset(visible)


def _verified_seed_hash(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    campaign_id: str,
    scenario_seed_id: str,
) -> str:
    """The exact content hash of the verified campaign scenario seed.

    The seed locality is re-checked here against the stored campaign
    authority and its content hash is computed with the established
    deterministic helper. A missing or foreign campaign authority raises
    the safe typed C1 validation error with a generic public message; no
    raw store exception with identifier-bearing text escapes.
    """
    try:
        campaign = store.get_campaign(tenant_id, campaign_id)
    except CampaignNotFoundError:
        _reject_validation(tenant_id, campaign_id, "campaign authority missing")
    seed = next(
        (
            candidate
            for candidate in campaign.seed_ensemble
            if candidate.identifier == (scenario_seed_id)
        ),
        None,
    )
    if seed is None or seed.tenant_id != tenant_id:
        _reject_validation(tenant_id, campaign_id, "scenario seed authority missing")
    return seed_content_hash(seed)


def _selected_action(
    policy: AdaptivePolicy,
    decision_event: AdaptivePolicyDecisionEvent,
) -> BoundAdaptiveAction:
    """The exact bound action selected by the verified decision event."""
    selected = next(
        (
            action
            for action in policy.actions
            if action.action_id == decision_event.selected_action_id
        ),
        None,
    )
    if selected is None:
        raise AdaptiveRunTrajectoryExecutionIntegrityError(
            policy.campaign_id, "", reason="selected action is not bound by the policy"
        )
    return selected


def _verified_plan_catalog(
    *, tenant_id: str, run_id: str, policy: AdaptivePolicy, action_plans: ActionPlanCatalog
) -> dict[str, tuple[StrategyTrajectoryPlan, ...]]:
    """Verify the complete action-plan catalog against the policy; never repair.

    The catalog is decision-independent: its keys must be exactly the
    policy's bound action identifiers, so every action entry - including
    actions that are not selected at this step - is verified completely
    before any observation derivation, noise draw, or policy advancement
    runs. For every bound action the mapped tuple must match its
    ``trajectory_plan_bindings`` exactly: same cardinality, same canonical
    binding order, and exact plan / manifest / state-model / strategy
    identity and content hashes, with no plan identifier and no state-model
    identifier duplicated within one action. The mapping itself is never
    sorted, repaired, replaced, or mutated; the returned dictionary is a
    key-for-key view of the verified caller input.
    """
    actions_by_id = {action.action_id: action for action in policy.actions}
    if set(action_plans) != set(actions_by_id):
        _reject_validation(
            tenant_id,
            run_id,
            "action-plan catalog must hold exactly the policy's bound actions",
        )
    verified: dict[str, tuple[StrategyTrajectoryPlan, ...]] = {}
    for action_id in actions_by_id:
        action = actions_by_id[action_id]
        plans = action_plans[action_id]
        bindings = action.trajectory_plan_bindings
        # Uniqueness is per action: different bound actions intentionally
        # reference the same state-model identifiers with their own plans,
        # so neither set may outlive one action's exact tuple verification.
        seen_plan_identifiers: set[str] = set()
        seen_state_model_identifiers: set[str] = set()
        if len(plans) != len(bindings):
            _reject_integrity(
                tenant_id,
                run_id,
                "action plan collection cardinality mismatch",
            )
        for binding, plan in zip(bindings, plans, strict=True):
            if plan.identifier != binding.trajectory_plan_id:
                _reject_integrity(
                    tenant_id,
                    run_id,
                    "action plan collection is not in canonical binding order",
                )
            if plan.content_hash != binding.trajectory_plan_content_hash:
                _reject_integrity(tenant_id, run_id, "plan content hash does not match its binding")
            if plan.campaign_id != policy.campaign_id:
                _reject_integrity(tenant_id, run_id, "plan campaign mismatch")
            if plan.world_version_id != policy.world_version_id:
                _reject_integrity(tenant_id, run_id, "plan world identity mismatch")
            if plan.world_content_hash != policy.world_content_hash:
                _reject_integrity(tenant_id, run_id, "plan world content hash mismatch")
            if plan.strategy_candidate_id != action.strategy_candidate_id:
                _reject_integrity(tenant_id, run_id, "plan strategy identity mismatch")
            if plan.strategy_content_hash != action.strategy_content_hash:
                _reject_integrity(tenant_id, run_id, "plan strategy content hash mismatch")
            if plan.manifest_id != binding.manifest_id:
                _reject_integrity(tenant_id, run_id, "plan manifest mismatch")
            if plan.state_model_id != binding.state_model_id:
                _reject_integrity(tenant_id, run_id, "plan state model identity mismatch")
            if plan.state_model_identifier != binding.state_model_identifier:
                _reject_integrity(tenant_id, run_id, "plan state model identifier mismatch")
            if plan.state_model_content_hash != binding.state_model_content_hash:
                _reject_integrity(tenant_id, run_id, "plan state model content hash mismatch")
            if plan.identifier in seen_plan_identifiers:
                _reject_integrity(tenant_id, run_id, "plan identifier duplicated within an action")
            seen_plan_identifiers.add(plan.identifier)
            if plan.state_model_identifier in seen_state_model_identifiers:
                _reject_integrity(
                    tenant_id, run_id, "state-model identifier duplicated within an action"
                )
            seen_state_model_identifiers.add(plan.state_model_identifier)
        verified[action_id] = plans
    return verified


def _preflight(
    *,
    tenant_id: str,
    run_id: str,
    policy: AdaptivePolicy,
    policy_state: AdaptivePolicyStateSnapshot,
    action_plans: ActionPlanCatalog,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    draft: AdaptiveDecisionStepDraft,
) -> None:
    """Verify the complete orchestrator input atomically; never repair.

    Enforces the exact caller shapes, detached strict revalidation of every
    supplied artifact, runtime-literal agreement, the pre-decision snapshot
    step agreement with the draft, and the exact self-covering content hash
    of every supplied plan across the complete action-plan catalog.
    Catalog binding agreement, plan-set binding equality, and
    state-collection authority are verified by their owning primitives;
    nothing is duplicated or trusted early.
    """
    if not isinstance(tenant_id, str) or not isinstance(run_id, str) or not tenant_id or not run_id:
        raise AdaptiveRunTrajectoryExecutionValidationError(
            tenant_id if isinstance(tenant_id, str) else "",
            run_id if isinstance(run_id, str) else "",
            "tenant_id and run_id must be non-empty strings",
        )
    _strictly_validate_draft(draft)
    if type(policy) is not AdaptivePolicy:
        _reject_validation(tenant_id, run_id, "policy must be an exact AdaptivePolicy")
    if type(policy_state) is not AdaptivePolicyStateSnapshot:
        _reject_validation(
            tenant_id, run_id, "policy state must be an exact AdaptivePolicyStateSnapshot"
        )
    if not isinstance(action_plans, Mapping):
        _reject_validation(
            tenant_id, run_id, "action plans must be a mapping of action identifiers"
        )
    for plans in action_plans.values():
        if not isinstance(plans, tuple) or not all(
            type(plan) is StrategyTrajectoryPlan for plan in plans
        ):
            _reject_validation(tenant_id, run_id, "plans must be a tuple of exact plans")
    if not isinstance(catalogs, tuple) or not all(
        type(catalog) is ModelTrajectoryCatalog for catalog in catalogs
    ):
        _reject_validation(tenant_id, run_id, "catalogs must be a tuple of exact catalogs")
    for artifact, model_type in (
        (policy, AdaptivePolicy),
        (policy_state, AdaptivePolicyStateSnapshot),
    ):
        try:
            _strictly_revalidate_detached(artifact, model_type)
        except ValueError:
            _reject_validation(tenant_id, run_id, "input failed detached strict revalidation")
    for plans in action_plans.values():
        for plan in plans:
            try:
                _strictly_revalidate_detached(plan, StrategyTrajectoryPlan)
            except ValueError:
                _reject_validation(
                    tenant_id, run_id, "trajectory plan failed detached strict revalidation"
                )
            if plan.content_hash != trajectory_plan_content_hash(plan):
                _reject_integrity(tenant_id, run_id, "trajectory plan content hash mismatch")
    if policy.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "policy must be runtime 4")
    if policy_state.runtime_version != RUNTIME_VERSION:
        _reject_validation(tenant_id, run_id, "policy state must be runtime 4")
    if policy_state.decision_step != draft.decision_step:
        _reject_validation(
            tenant_id, run_id, "pre-decision snapshot step must equal the draft decision step"
        )


def execute_adaptive_decision_step(
    store: InMemoryScenarioStore,
    *,
    tenant_id: str,
    run_id: str,
    campaign_id: str,
    scenario_seed_id: str,
    policy: AdaptivePolicy,
    policy_state: AdaptivePolicyStateSnapshot,
    action_plans: ActionPlanCatalog,
    catalogs: tuple[ModelTrajectoryCatalog, ...],
    draft: AdaptiveDecisionStepDraft,
) -> AdaptiveDecisionStepResult:
    """Execute exactly one causal adaptive decision step; raises typed errors.

    Runs the frozen ADR-004 D28-02 within-step causal order over the three
    completed runtime-4 primitives: the complete fail-closed preflight
    including the complete decision-independent action-plan catalog, the
    stored-policy authority agreement, the observation-visible state
    subset, exactly one real observation derivation, exactly one real
    policy-state advancement over the derived available events, and
    exactly one real selected-action application whose plan tuple is
    resolved internally from the verified catalog against the same
    pre-action state values. Returns the frozen complete step result.

    Every failure is atomic: no result, no store write, no activity event,
    no input mutation, and no partial persisted or external effect exists.
    Byte-equivalent inputs always produce exactly equal results.
    """
    try:
        _preflight(
            tenant_id=tenant_id,
            run_id=run_id,
            policy=policy,
            policy_state=policy_state,
            action_plans=action_plans,
            catalogs=catalogs,
            draft=draft,
        )
        _resolve_stored_policy(
            store, tenant_id=tenant_id, run_id=run_id, campaign_id=campaign_id, policy=policy
        )
        verified_plans = _verified_plan_catalog(
            tenant_id=tenant_id, run_id=run_id, policy=policy, action_plans=action_plans
        )
        visible = _observation_visible_models(
            store,
            tenant_id=tenant_id,
            run_id=run_id,
            policy=policy,
            pre_action_states=draft.pre_action_states,
        )
        bound_models = {
            binding.state_model_identifier
            for action in policy.actions
            for binding in action.trajectory_plan_bindings
        }
        if set(draft.pre_action_states.keys()) != visible | bound_models:
            _reject_validation(
                tenant_id,
                run_id,
                "pre-action state collection must hold exactly the declared and bound states",
            )
        observation_draft = ObservationStepDraft(
            decision_step=draft.decision_step,
            final_decision_step=draft.final_decision_step,
            state={
                identifier: draft.pre_action_states[identifier] for identifier in sorted(visible)
            },
            prior_events=draft.prior_observation_events,
            external_bundle_draft=draft.external_bundle_draft,
        )
        observations = derive_observation_step(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
            draft=observation_draft,
        )
        seed_hash = _verified_seed_hash(
            store,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            scenario_seed_id=scenario_seed_id,
        )
        policy_step = advance_adaptive_policy_state(
            policy=policy,
            state=policy_state,
            events=observations.available_events,
            scenario_seed_id=scenario_seed_id,
            seed_content_hash=seed_hash,
        )
        selected_plans = verified_plans[policy_step.decision_event.selected_action_id]
        selected = _selected_action(policy, policy_step.decision_event)
        action_states = {
            identifier: draft.pre_action_states[identifier]
            for identifier in sorted(
                binding.state_model_identifier for binding in selected.trajectory_plan_bindings
            )
        }
        applied = apply_selected_adaptive_action(
            tenant_id=tenant_id,
            run_id=run_id,
            policy=policy,
            decision_event=policy_step.decision_event,
            plans=selected_plans,
            catalogs=catalogs,
            pre_action_states=action_states,
        )
        return AdaptiveDecisionStepResult(
            new_observation_events=observations.new_events,
            available_observation_events=observations.available_events,
            pre_decision_policy_state=policy_state,
            decision_event=policy_step.decision_event,
            switch_event=policy_step.switch_event,
            next_policy_state=policy_step.next_state,
            trajectory_results=applied.trajectory_results,
        )
    except (AttributeError, TypeError, KeyError, IndexError, ValueError):
        # A validator-bypassed same-type instance can carry raw dumped
        # dictionaries where nested contracts belong, and any other raw
        # structural failure at this boundary is converted to the safe
        # typed validation error exactly like the established store and
        # primitive boundaries. Typed domain errors are not in this tuple
        # and propagate unchanged.
        _reject_validation(tenant_id, run_id, "input violates its contract")


__all__ = [
    "RUNTIME_VERSION",
    "ActionPlanCatalog",
    "AdaptiveDecisionStepDraft",
    "AdaptiveDecisionStepResult",
    "execute_adaptive_decision_step",
]
